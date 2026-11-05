"""Visible operator journeys and reply targets after interface navigation."""

import pytest

from .conftest import ADMIN, CLIENT
from .payment_helpers import legacy_ticket
from .test_upgrade import callbacks, last, order, sent


async def press(env, uid, callback, *, card=970):
    assert callback in callbacks(last(env, uid)), callbacks(last(env, uid))
    await env.callback(uid, callback, card=card)


async def test_accept_order_keeps_visible_operator_card_as_native_reply_target(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:view:{ticket.id}", card=970)
    await press(env, ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    target = env.store.reply_ticket(ADMIN, 970)
    assert target is not None and target.id == ticket.id
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    await env.message(ADMIN, "Реквизиты после согласования условий", reply_to=970, message_id=971)
    row = env.store.find_source(ADMIN, 971)
    assert row is not None and row["ticket_id"] == ticket.id
    assert "Реквизиты после согласования условий" in last(env, CLIENT)["text"]
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"


async def test_operator_can_reach_history_client_and_cancellation_through_visible_buttons(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:view:{ticket.id}")
    await press(env, ADMIN, f"a:details:{ticket.id}")
    details = callbacks(last(env, ADMIN))
    assert {f"a:history:{ticket.id}:0", f"a:client:{CLIENT}", f"a:status:{ticket.id}"} <= set(details)
    await press(env, ADMIN, f"a:history:{ticket.id}:0")
    await press(env, ADMIN, f"a:view:{ticket.id}")
    await press(env, ADMIN, f"a:details:{ticket.id}")
    await press(env, ADMIN, f"a:status:{ticket.id}")
    before = len(sent(env, CLIENT))
    await press(env, ADMIN, f"a:set:{ticket.id}:{ticket.version}:cancelled")
    assert env.store.ticket(ticket.id).status == "new"
    assert len(sent(env, CLIENT)) == before
    await press(env, ADMIN, f"a:confirm:{ticket.id}:{ticket.version}:cancelled")
    assert env.store.ticket(ticket.id).status == "cancelled"
    assert "отмен" in last(env, CLIENT)["text"].lower()
    assert f"a:details:{ticket.id}" in callbacks(last(env, ADMIN))
    assert "a:home" in callbacks(last(env, ADMIN))


@pytest.mark.parametrize("status", ["resolved", "cancelled"])
async def test_closed_operator_card_keeps_history_reachable_without_write_actions(env, status):
    ticket = legacy_ticket(env.store, await order(env))
    ticket = env.store.set_status(ticket.id, ticket.version, status, ADMIN)
    await env.callback(ADMIN, f"a:view:{ticket.id}")
    assert f"a:reply:{ticket.id}" not in callbacks(last(env, ADMIN))
    assert "a:home" in callbacks(last(env, ADMIN))
    await press(env, ADMIN, f"a:details:{ticket.id}")
    assert f"a:history:{ticket.id}:0" in callbacks(last(env, ADMIN))
    assert f"a:status:{ticket.id}" not in callbacks(last(env, ADMIN))
    await press(env, ADMIN, f"a:history:{ticket.id}:0")
    await press(env, ADMIN, f"a:view:{ticket.id}")
    assert env.store.ticket(ticket.id).status == status


async def test_successful_paid_reply_receipt_has_explicit_order_and_cabinet_return(env):
    ticket = legacy_ticket(env.store, await order(env))
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Уточните текст ошибки", message_id=972)
    assert env.store.ticket(ticket.id).status == "waiting_user"
    assert f"a:view:{ticket.id}" in callbacks(last(env, ADMIN))
    assert "a:home" in callbacks(last(env, ADMIN))
    await press(env, ADMIN, f"a:view:{ticket.id}")
    await press(env, ADMIN, f"a:details:{ticket.id}")
    assert f"a:history:{ticket.id}:0" in callbacks(last(env, ADMIN))
    assert env.store.db.execute("SELECT COUNT(*) FROM messages WHERE role='operator'").fetchone()[0] == 1


@pytest.mark.parametrize("service", ["localbitcoins", "chatgpt", "gemini"])
async def test_unavailable_order_screen_cannot_become_reply_target_for_another_order(env, service):
    ticket = await order(env)
    await env.callback(CLIENT, f"c:view:{ticket.id}", card=980)
    assert env.store.customer_reply_ticket(CLIENT, 980).id == ticket.id
    await env.callback(CLIENT, f"c:order:{service}:standard", card=980)
    assert env.store.customer_reply_ticket(CLIENT, 980) is None
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Вопрос к недоступному экрану", reply_to=980, message_id=981)
    assert env.store.find_source(CLIENT, 981) is None
    assert len(sent(env, ADMIN)) == before
    assert env.store.ticket(ticket.id).service_code == "claude"


async def test_malformed_history_recovery_screen_has_no_hidden_reply_destination(env):
    ticket = await order(env)
    await env.callback(CLIENT, f"c:view:{ticket.id}", card=982)
    await env.callback(CLIENT, f"c:history:{ticket.id}:not_a_page", card=982)
    assert env.store.customer_reply_ticket(CLIENT, 982) is None
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Ответ на экран ошибки", reply_to=982, message_id=983)
    assert env.store.find_source(CLIENT, 983) is None
    assert len(sent(env, ADMIN)) == before


async def test_existing_order_warning_explicitly_preserves_its_reply_target(env):
    ticket = await order(env)
    await env.callback(CLIENT, "c:order:alipay:standard", card=984)
    assert f"c:view:{ticket.id}" in callbacks(last(env, CLIENT))
    target = env.store.customer_reply_ticket(CLIENT, 984)
    assert target is not None and target.id == ticket.id
    await env.message(CLIENT, "Уточнение по существующему заказу", reply_to=984, message_id=985)
    assert env.store.find_source(CLIENT, 985)["ticket_id"] == ticket.id
    assert env.store.ticket(ticket.id).service_code == "claude"
    assert env.store.profile(CLIENT).total_tickets == 1


@pytest.mark.parametrize("viewer,prefix", [(CLIENT, "c"), (ADMIN, "a")])
@pytest.mark.parametrize("role", ["user", "operator"])
async def test_history_attachments_show_original_author_for_both_viewer_roles(env, viewer, prefix, role):
    ticket = await order(env)
    actor = CLIENT if role == "user" else ADMIN
    message_id, _ = env.store.add_message(ticket.id, role, "Историческое вложение", actor, actor, 986)
    file_kind = "photo" if role == "user" else "document"
    env.store.attach_message(message_id, "saved_history_attachment", file_kind)
    before = len(env.request.calls)
    await env.callback(viewer, f"{prefix}:message:{ticket.id}:{message_id}", card=987)
    media = [(name, params) for name, params in env.request.calls[before:]
             if name in {"sendPhoto", "sendDocument"}]
    assert len(media) == 1
    _, params = media[0]
    author = "Оператор" if role == "operator" else "Вы" if viewer == CLIENT else ticket.display_name
    assert params["caption"].startswith(f"{author} · ")
    assert f"{prefix}:history:{ticket.id}:0" in callbacks(params)
    assert not any(data.startswith("a:" if prefix == "c" else "c:") for data in callbacks(params))
    text_author = "Оператор" if role == "operator" else "Вы" if viewer == CLIENT else "Клиент"
    assert f"\n{text_author} · " in last(env, viewer)["text"]


async def test_rejected_proof_requests_replacement_without_returning_to_initial_payment_instructions(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    assert "Ожидает оплаты" in last(env, CLIENT)["text"]
    assert "Нужен другой чек" not in last(env, CLIENT)["text"]
    await env.proof(CLIENT, photo=True, message_id=990)
    current = env.store.ticket(ticket.id)
    await env.callback(ADMIN, f"a:reject_payment:{ticket.id}:{current.version}")
    assert "Нужен другой чек" in last(env, CLIENT)["text"]
    assert "Дождитесь реквизитов" not in last(env, CLIENT)["text"]
    assert not any(data.startswith("c:cancel:") for data in callbacks(last(env, CLIENT)))
    for destination in ("c:home", "c:profile", "c:current"):
        await env.callback(CLIENT, destination)
        assert "Нужен другой чек" in last(env, CLIENT)["text"]
        assert not any(data.startswith("c:cancel:") for data in callbacks(last(env, CLIENT)))
    await env.proof(CLIENT, photo=True, message_id=991)
    await env.callback(CLIENT, "c:current")
    assert "Проверяем оплату" in last(env, CLIENT)["text"]
    assert "Нужен другой чек" not in last(env, CLIENT)["text"]
    assert len(env.store.payment_proofs(ticket.id)) == 2
    assert env.store.ticket(ticket.id).payment_stage == "review"


async def test_invalid_review_comment_offers_visible_skip_and_does_not_become_chat_message(env):
    ticket = legacy_ticket(env.store, await order(env))
    ticket = env.store.set_status(ticket.id, ticket.version, "resolved", ADMIN)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:4")
    await env.message(CLIENT, "я" * 1201, message_id=992)
    assert {f"c:review_skip:{ticket.id}", "c:home"} <= set(callbacks(last(env, CLIENT)))
    assert env.store.pending_review(CLIENT)["ticket_id"] == ticket.id
    assert env.store.find_source(CLIENT, 992) is None
    await press(env, CLIENT, f"c:review_skip:{ticket.id}")
    review = env.store.review(ticket.id)
    assert review["stars"] == 4
    assert not review["comment"]
    assert review["finished_at"] is not None
    assert env.store.pending_review(CLIENT) is None
