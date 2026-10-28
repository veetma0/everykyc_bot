"""Minimal screens, explicit send intent, and a fast operator workspace."""

from dataclasses import replace

import pytest
from telegram.error import TimedOut

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last, order, sent


async def payment(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    return env.store.ticket(ticket.id)


async def test_customer_can_reply_or_cancel_and_payment_is_readable_without_opening_menus(env):
    await env.message(CLIENT, "/start")
    assert callbacks(last(env, CLIENT)) == ["c:service:claude"]
    ticket = await order(env)
    assert callbacks(last(env, CLIENT)) == [f"c:write:{ticket.id}", f"c:cancel:{ticket.id}:{ticket.version}"]
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    card = last(env, CLIENT)
    assert "Реальные реквизиты ещё не подключены" in card["text"]
    assert "Деньги переводить не нужно" in card["text"]
    assert "$35" in card["text"] and "DEMO-" not in card["text"]
    assert callbacks(card) == [f"c:proof_prompt:{ticket.id}", f"c:cancel:{ticket.id}:{env.store.ticket(ticket.id).version}"]


async def test_accidental_photo_is_never_forwarded_before_customer_confirms(env):
    ticket = await payment(env)
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, photo=True, caption="случайное фото")
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    assert not env.store.payment_proofs(ticket.id)
    assert len(sent(env, ADMIN)) == before
    assert not any(name == "sendPhoto" for name, _ in env.request.calls)
    draft = env.store.draft(CLIENT)
    await env.callback(CLIENT, f"c:discard_draft:{ticket.id}:{draft['token']}")
    assert env.store.draft(CLIENT) is None
    assert not env.store.payment_proofs(ticket.id)


async def test_review_arrives_with_direct_decisions_and_payment_sends_wait_instruction(env):
    ticket = await payment(env)
    await env.proof(CLIENT, photo=True)
    current = env.store.ticket(ticket.id)
    assert f"a:confirm_payment:{ticket.id}:{current.version}" in callbacks(last(env, ADMIN))
    assert len(callbacks(last(env, ADMIN))) == 3
    assert any(name == "sendPhoto" and data["chat_id"] == ADMIN for name, data in env.request.calls)
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{current.version}")
    text = last(env, CLIENT)["text"]
    assert "Оплата подтверждена" in text
    assert "В работе" in text
    assert "самостоятельной проверки" in text
    assert "Ссылку KYC, документы и коды входа сюда не отправляйте" in text
    assert callbacks(last(env, CLIENT)) == ["c:guide:claude"]
    assert len(callbacks(last(env, ADMIN))) == 3
    assert any(v.endswith(":resolved") for v in callbacks(last(env, ADMIN)))


async def test_plain_operator_input_is_previewed_and_sent_once_to_named_customer(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    before = len(sent(env, CLIENT))
    await env.message(ADMIN, "Ваш ответ готов", message_id=980)
    assert len(sent(env, CLIENT)) == before
    assert "Клиент 101" in last(env, ADMIN)["text"]
    draft = env.store.draft(ADMIN)
    button = f"a:send_draft:{ticket.id}:{draft['token']}"
    await env.callback(ADMIN, button)
    assert "Ваш ответ готов" in last(env, CLIENT)["text"]
    await env.callback(ADMIN, button)
    rows = env.store.db.execute("SELECT body FROM messages WHERE role='operator'").fetchall()
    assert [row["body"] for row in rows] == ["Ваш ответ готов"]


async def test_another_notification_does_not_change_the_selected_reply_recipient(env):
    first = await order(env)
    await env.callback(ADMIN, f"a:reply:{first.id}")
    second = await order(env, uid=OTHER)
    await env.message(OTHER, "Это второй клиент")
    await env.message(ADMIN, "Ответ первому клиенту")
    draft = env.store.draft(ADMIN)
    assert draft["ticket_id"] == first.id
    await env.confirm_draft(ADMIN)
    assert env.store.db.execute(
        "SELECT ticket_id FROM messages WHERE body='Ответ первому клиенту'"
    ).fetchone()[0] == first.id
    assert env.store.ticket(second.id).status == "new"


@pytest.mark.parametrize("destination", ["a:home", "a:list:active:0", "a:mode:client"])
async def test_navigation_discards_preview_and_cannot_send_to_hidden_recipient(env, destination):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Не отправлять после выхода")
    draft = env.store.draft(ADMIN)
    await env.callback(ADMIN, destination)
    assert env.store.focused_ticket(ADMIN) is None
    assert env.store.draft(ADMIN) is None
    await env.callback(ADMIN, f"a:send_draft:{ticket.id}:{draft['token']}")
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_expired_reply_mode_requires_choosing_customer_again(env, monkeypatch):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    monkeypatch.setattr("verifydesk.store.time.time", lambda: 10**12)
    await env.message(ADMIN, "Старый получатель больше не выбран")
    assert env.store.draft(ADMIN) is None
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_new_proof_replaces_old_draft_and_old_button_cannot_send_either(env):
    ticket = await payment(env)
    await env.message(CLIENT, "https://example.org/old")
    old = env.store.draft(CLIENT)
    await env.message(CLIENT, "https://example.org/new")
    new = env.store.draft(CLIENT)
    await env.callback(CLIENT, f"c:send_draft:{ticket.id}:{old['token']}")
    assert not env.store.payment_proofs(ticket.id)
    assert env.store.draft(CLIENT)["token"] == new["token"]
    await env.confirm_draft(CLIENT)
    assert env.store.payment_proofs(ticket.id)[0]["body"] == "https://example.org/new"


async def test_forged_draft_or_customer_mode_cannot_send_operators_preview(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Приватный черновик")
    draft = env.store.draft(ADMIN)
    await env.callback(OTHER, f"c:send_draft:{ticket.id}:{draft['token']}")
    await env.callback(ADMIN, f"c:send_draft:{ticket.id}:{draft['token']}")
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


@pytest.mark.parametrize("noise", ["1", "123456", "?", "🙂", "Меню", "Назад"])
async def test_accidental_customer_input_does_not_create_messages_or_change_status(env, noise):
    ticket = await order(env)
    before = tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone())
    await env.message(CLIENT, noise)
    assert tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone()) == before
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchall()


async def test_uncertain_operator_draft_delivery_is_never_resent(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Проверка доставки")
    draft = env.store.draft(ADMIN)
    data = f"a:send_draft:{ticket.id}:{draft['token']}"
    env.request.fail_chat, env.request.fail_error = CLIENT, TimedOut()
    await env.callback(ADMIN, data)
    await env.callback(ADMIN, data)
    row = env.store.db.execute("SELECT delivery FROM messages WHERE role='operator'").fetchone()
    assert row["delivery"] == "uncertain"
    attempts = [p for name, p in env.request.calls if name == "sendMessage" and p["chat_id"] == CLIENT and "Проверка доставки" in p["text"]]
    assert len(attempts) == 1


async def test_closed_order_cannot_receive_pending_proof_draft(env):
    ticket = await payment(env)
    await env.message(CLIENT, photo=True)
    draft = env.store.draft(CLIENT)
    env.store.set_status(ticket.id, ticket.version, "cancelled", CLIENT)
    await env.callback(CLIENT, f"c:send_draft:{ticket.id}:{draft['token']}")
    assert not env.store.payment_proofs(ticket.id)


async def test_restart_clears_unsent_previews_and_reply_modes(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Не отправлять после перезапуска")
    await env.app.post_init(env.app)
    assert env.store.focused_ticket(ADMIN) is None
    assert env.store.draft(ADMIN) is None


async def test_competing_operator_cannot_take_over_an_active_reply_preview(env):
    second = 9002
    desk = env.app.handlers[0][0].callback.__self__
    desk.config = replace(desk.config, admin_ids=(ADMIN, second))
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Ответ от первого оператора")
    await env.callback(second, f"a:reply:{ticket.id}")
    assert env.store.focused_ticket(second) is None
    await env.confirm_draft(ADMIN)
    assert "Ответ от первого оператора" in last(env, CLIENT)["text"]


@pytest.mark.parametrize("token", ["bad", "🙂", "a" * 12])
async def test_invalid_draft_tokens_are_handled_without_errors(env, token):
    ticket = await payment(env)
    await env.message(CLIENT, photo=True)
    await env.callback(CLIENT, f"c:send_draft:{ticket.id}:{token}")
    assert not env.store.payment_proofs(ticket.id)
