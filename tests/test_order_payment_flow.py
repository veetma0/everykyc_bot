"""Payment proof is a customer submission; only an operator can start the order."""

from dataclasses import replace

import pytest
from telegram.error import Forbidden, TimedOut

from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import buttons, callbacks, last, order, sent


async def request_payment(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    return env.store.ticket(ticket.id)


async def test_visible_order_journey_requires_payment_review_before_work(env):
    await env.message(CLIENT, "/start")
    assert len(buttons(last(env, CLIENT))) == 4
    for data in ("c:catalog", "c:category:other", "c:service:claude", "c:order:claude:standard"):
        assert data in callbacks(last(env, CLIENT))
        await env.callback(CLIENT, data)
    ticket = env.store.for_user(CLIENT)
    assert "⏳ Ожидает оператора" in last(env, CLIENT)["text"]
    await env.message(ADMIN, "/next")
    accept = f"a:request_payment:{ticket.id}:{ticket.version}"
    assert accept in callbacks(last(env, ADMIN))
    assert env.store.ticket(ticket.id).status == "new"
    await env.callback(ADMIN, accept)
    assert "Оператор принял сделку" in last(env, CLIENT)["text"]
    assert "Дождитесь реквизитов" in last(env, CLIENT)["text"]
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    before = len(sent(env, CLIENT))
    await env.callback(ADMIN, accept)
    assert len(sent(env, CLIENT)) == before, "Stale accept must not resend requisites"

    await env.proof(CLIENT, photo=True, caption="Тестовое подтверждение")
    ticket = env.store.ticket(ticket.id)
    assert ticket.payment_stage == "review" and ticket.status == "new"
    assert "Подтверждение сохранено" in last(env, CLIENT)["text"]
    assert any(v.startswith("a:confirm_payment:") for v in callbacks(last(env, ADMIN)))
    await env.callback(ADMIN, f"a:proofs:{ticket.id}")
    confirm = f"a:confirm_payment:{ticket.id}:{ticket.version}"
    assert confirm in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, confirm)
    ticket = env.store.ticket(ticket.id)
    assert ticket.status == "in_progress" and ticket.payment_stage == "confirmed"
    assert "🛠 В работе" in last(env, CLIENT)["text"]
    assert "Оплата подтверждена. Ожидайте сообщения от оператора." in last(env, CLIENT)["text"]
    finish = f"a:set:{ticket.id}:{ticket.version}:resolved"
    assert finish in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, finish)
    assert env.store.ticket(ticket.id).status == "in_progress"
    await env.callback(ADMIN, f"a:confirm:{ticket.id}:{ticket.version}:resolved")
    assert env.store.ticket(ticket.id).status == "resolved"
    assert any("✅ Заказ выполнен" in row["text"] for row in sent(env, CLIENT))
    assert not any(method in {"sendInvoice", "createInvoiceLink", "getFile"} for method, _ in env.request.calls)


async def test_links_are_saved_without_fetching_and_duplicate_proof_is_idempotent(env):
    ticket = await request_payment(env)
    await env.proof(CLIENT, "Тест: https://example.com/receipt/123", message_id=902)
    current = env.store.ticket(ticket.id)
    before = len(env.request.calls)
    await env.message(CLIENT, "Тест: https://example.com/receipt/123", message_id=902)
    assert len(env.request.calls) == before
    assert (env.store.ticket(ticket.id).status, env.store.ticket(ticket.id).version) == (current.status, current.version)
    assert len(env.store.payment_proofs(ticket.id)) == 1
    assert env.store.payment_proofs(ticket.id)[0]["file_id"] is None
    await env.callback(ADMIN, f"a:proofs:{ticket.id}")
    assert "https://example.com/receipt/123" in last(env, ADMIN)["text"]
    assert last(env, ADMIN)["link_preview_options"]["is_disabled"]


async def test_plain_chat_does_not_count_as_payment_or_start_work(env):
    ticket = await request_payment(env)
    await env.message(CLIENT, "Оплатил")
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    assert not env.store.payment_proofs(ticket.id)
    target = env.store.db.execute(
        "SELECT MAX(message_id) FROM reply_targets WHERE chat_id=?", (ADMIN,)
    ).fetchone()[0]
    await env.message(ADMIN, "Пришлите подтверждение", reply_to=target)
    current = env.store.ticket(ticket.id)
    assert current.status == "new" and current.payment_stage == "awaiting_payment"
    assert "💳 Ожидает оплаты" in last(env, CLIENT)["text"]


@pytest.mark.parametrize("action", ["in_progress", "waiting_user", "resolved"])
async def test_old_status_buttons_cannot_bypass_payment(env, action):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:confirm:{ticket.id}:{ticket.version}:{action}")
    assert env.store.ticket(ticket.id).status == "new"
    assert env.store.ticket(ticket.id).payment_stage == "not_requested"


async def test_rejection_requires_new_proof_and_stale_confirmation_cannot_start_work(env):
    ticket = await request_payment(env)
    await env.proof(CLIENT, "https://example.com/first")
    review = env.store.ticket(ticket.id)
    await env.callback(ADMIN, f"a:reject_payment:{ticket.id}:{review.version}")
    assert "новый" in last(env, CLIENT)["text"]
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{review.version}")
    assert env.store.ticket(ticket.id).status == "new"
    await env.proof(CLIENT, "https://example.com/second")
    latest = env.store.ticket(ticket.id)
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{review.version}")
    assert env.store.ticket(ticket.id).payment_stage == "review"
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{latest.version}")
    assert env.store.ticket(ticket.id).status == "in_progress"


async def test_proof_is_private_and_cannot_approve_another_customers_order(env):
    ticket = await request_payment(env)
    await env.proof(CLIENT, photo=True, caption="PRIVATE PAYMENT")
    review = env.store.ticket(ticket.id)
    for data in (f"a:proofs:{ticket.id}", f"a:confirm_payment:{ticket.id}:{review.version}"):
        await env.callback(OTHER, data)
        assert "PRIVATE PAYMENT" not in last(env, OTHER)["text"]
    assert not any(method == "sendPhoto" and params["chat_id"] == OTHER for method, params in env.request.calls)
    assert env.store.ticket(ticket.id).payment_stage == "review"


async def test_payment_proof_reply_cannot_attach_to_a_new_order(env):
    old = await request_payment(env)
    old_card = env.store.db.execute(
        "SELECT MAX(message_id) FROM customer_reply_targets WHERE chat_id=?", (CLIENT,)
    ).fetchone()[0]
    env.store.set_status(old.id, old.version, "cancelled", CLIENT)
    current = await request_payment(env)
    await env.message(CLIENT, photo=True, reply_to=old_card)
    assert not env.store.payment_proofs(current.id)
    assert not env.store.payment_proofs(old.id)
    assert "закрыт" in last(env, CLIENT)["text"]


@pytest.mark.parametrize("error", [Forbidden("Blocked"), TimedOut()])
async def test_failed_requisites_delivery_keeps_recoverable_payment_stage(env, error):
    ticket = await order(env)
    env.request.fail_chat, env.request.fail_error = CLIENT, error
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    assert "не подтверждена" in last(env, ADMIN)["text"]
    env.request.fail_chat = None
    await env.callback(CLIENT, f"c:requisites:{ticket.id}")
    assert "Оператор принял сделку" in last(env, CLIENT)["text"]
    assert "DEMO-" not in last(env, CLIENT)["text"]


async def test_image_failure_prevents_visible_approval_until_evidence_is_opened(env):
    ticket = await request_payment(env)
    await env.proof(CLIENT, photo=True)
    original = env.request.do_request

    async def fail_image(url, method, request_data=None, **kwargs):
        if url.endswith("/sendPhoto"):
            raise TimedOut()
        return await original(url, method, request_data, **kwargs)

    env.request.do_request = fail_image
    await env.callback(ADMIN, f"a:proofs:{ticket.id}")
    assert "не загрузился" in last(env, ADMIN)["text"]
    assert not any(data.startswith("a:confirm_payment:") for data in callbacks(last(env, ADMIN)))
    assert env.store.ticket(ticket.id).payment_stage == "review"


async def test_screenshot_as_image_document_survives_reopening(env):
    ticket = await request_payment(env)
    await env.proof(CLIENT, document={
        "file_id": "test-image-file", "file_unique_id": "image-unique", "file_name": "receipt.png",
        "mime_type": "image/png", "file_size": 5000,
    })
    path = env.store.db.execute("PRAGMA database_list").fetchone()["file"]
    from pathlib import Path
    reopened = Store(Path(path))
    try:
        assert reopened.ticket(ticket.id).payment_stage == "review"
        proof = reopened.payment_proofs(ticket.id)[0]
        assert (proof["file_id"], proof["file_kind"]) == ("test-image-file", "document")
    finally:
        reopened.close()
    assert any(method == "sendDocument" for method, _ in env.request.calls)


async def test_photos_outside_payment_stage_are_relayed_as_chat_attachments(env):
    ticket = await order(env)
    await env.message(CLIENT, photo=True)
    assert not env.store.payment_proofs(ticket.id)
    assert any(method == "sendPhoto" for method, _ in env.request.calls)
    assert not any(method == "getFile" for method, _ in env.request.calls)


async def test_second_operator_cannot_approve_payment_claimed_for_review(env):
    second = 9002
    desk = env.app.handlers[0][0].callback.__self__
    desk.config = replace(desk.config, admin_ids=(ADMIN, second))
    ticket = await request_payment(env)
    await env.proof(CLIENT, "https://example.com/demo")
    await env.message(ADMIN, "/next")
    review = env.store.ticket(ticket.id)
    await env.callback(second, f"a:confirm_payment:{ticket.id}:{review.version}")
    assert env.store.ticket(ticket.id).payment_stage == "review"


async def test_status_notification_reply_is_mapped_and_more_screen_clears_admin_target(env):
    ticket = await request_payment(env)
    await env.proof(CLIENT, "https://example.com/demo")
    review = env.store.ticket(ticket.id)
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{review.version}")
    notification = env.store.db.execute(
        "SELECT MAX(message_id) FROM customer_reply_targets WHERE chat_id=?", (CLIENT,)
    ).fetchone()[0]
    await env.message(CLIENT, "Уточнение по заказу", reply_to=notification)
    assert env.store.db.execute("SELECT ticket_id FROM messages WHERE body='Уточнение по заказу'").fetchone()[0] == ticket.id
    await env.callback(ADMIN, f"a:view:{ticket.id}", card=700)
    assert env.store.reply_ticket(ADMIN, 700)
    await env.callback(ADMIN, "a:more", card=700)
    assert env.store.reply_ticket(ADMIN, 700) is None
