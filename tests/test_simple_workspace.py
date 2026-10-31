"""Compact direct chats, explicit recipient selection, and operator safeguards."""

from dataclasses import replace

import pytest
from telegram.error import TimedOut

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last, order, sent


async def payment(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    return env.store.ticket(ticket.id)


async def test_customer_can_write_directly_and_payment_is_readable_without_opening_menus(env):
    await env.message(CLIENT, "/start")
    assert {"c:catalog", "c:profile", "c:rules", "c:wholesale"} <= set(callbacks(last(env, CLIENT)))
    ticket = await order(env)
    data = callbacks(last(env, CLIENT))
    assert f"c:cancel:{ticket.id}:{ticket.version}" in data
    assert not any(v.startswith(("c:write:", "c:proof_prompt:", "c:send_draft:")) for v in data)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    card = last(env, CLIENT)
    assert "Оператор принял сделку" in card["text"]
    assert "Дождитесь реквизитов" in card["text"]
    assert "$45" in card["text"] and "DEMO-" not in card["text"]
    assert f"c:cancel:{ticket.id}:{env.store.ticket(ticket.id).version}" in callbacks(card)
    assert not any(v.startswith(("c:write:", "c:proof_prompt:", "c:send_draft:")) for v in callbacks(card))


async def test_photo_is_forwarded_once_and_never_confirms_payment_automatically(env):
    ticket = await payment(env)
    await env.message(CLIENT, photo=True, caption="Фото подтверждения", message_id=970)
    current = env.store.ticket(ticket.id)
    assert current.payment_stage == "review" and current.status == "new"
    assert len(env.store.payment_proofs(ticket.id)) == 1
    assert any(name == "sendPhoto" and params["chat_id"] == ADMIN for name, params in env.request.calls)
    assert env.store.draft(CLIENT) is None
    before = len(env.request.calls)
    await env.message(CLIENT, photo=True, caption="Фото подтверждения", message_id=970)
    assert len(env.request.calls) == before
    assert len(env.store.payment_proofs(ticket.id)) == 1


async def test_review_arrives_with_direct_decisions_and_payment_sends_wait_instruction(env):
    ticket = await payment(env)
    await env.proof(CLIENT, photo=True)
    current = env.store.ticket(ticket.id)
    assert f"a:confirm_payment:{ticket.id}:{current.version}" in callbacks(last(env, ADMIN))
    assert f"a:reply:{ticket.id}" in callbacks(last(env, ADMIN))
    assert any(name == "sendPhoto" and data["chat_id"] == ADMIN for name, data in env.request.calls)
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{current.version}")
    text = last(env, CLIENT)["text"]
    assert "Оплата подтверждена" in text and "В работе" in text
    assert "самостоятельной проверки" in text
    assert "Ссылку KYC, документы и коды входа сюда не отправляйте" in text
    assert "c:guide:claude" in callbacks(last(env, CLIENT))
    assert not any(v.startswith(("c:proof_prompt:", "c:send_draft:")) for v in callbacks(last(env, CLIENT)))
    assert any(v.endswith(":resolved") for v in callbacks(last(env, ADMIN)))


async def test_plain_operator_input_is_sent_once_to_explicitly_selected_customer(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    before = len(sent(env, CLIENT))
    await env.message(ADMIN, "Ваш ответ готов", message_id=980)
    assert len(sent(env, CLIENT)) == before + 1
    assert "Клиент 101" in last(env, ADMIN)["text"]
    assert "Ваш ответ готов" in last(env, CLIENT)["text"]
    assert env.store.draft(ADMIN) is None
    await env.message(ADMIN, "Ваш ответ готов", message_id=980)
    rows = env.store.db.execute("SELECT body FROM messages WHERE role='operator'").fetchall()
    assert [row["body"] for row in rows] == ["Ваш ответ готов"]


async def test_another_notification_does_not_change_the_selected_reply_recipient(env):
    first = await order(env)
    await env.callback(ADMIN, f"a:reply:{first.id}")
    second = await order(env, uid=OTHER)
    await env.message(OTHER, "Это второй клиент")
    assert env.store.focused_ticket(ADMIN).id == first.id
    await env.message(ADMIN, "Ответ первому клиенту")
    assert env.store.draft(ADMIN) is None
    assert env.store.db.execute(
        "SELECT ticket_id FROM messages WHERE body='Ответ первому клиенту'"
    ).fetchone()[0] == first.id
    assert env.store.ticket(second.id).status == "new"


@pytest.mark.parametrize("destination", ["a:home", "a:list:active:0", "a:mode:client"])
async def test_navigation_clears_recipient_and_old_send_button_cannot_send_hidden_text(env, destination):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    draft = env.store.save_draft(ADMIN, ticket.id, "operator", "Старый черновик", ADMIN, 981)
    await env.callback(ADMIN, destination)
    assert env.store.focused_ticket(ADMIN) is None
    assert env.store.draft(ADMIN) is None
    await env.callback(ADMIN, f"a:send_draft:{ticket.id}:{draft['token']}")
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()
    if destination != "a:mode:client":
        await env.message(ADMIN, "Получатель больше не выбран")
        assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_expired_reply_mode_requires_choosing_customer_again(env, monkeypatch):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    monkeypatch.setattr("verifydesk.store.time.time", lambda: 10**12)
    await env.message(ADMIN, "Старый получатель больше не выбран")
    assert env.store.draft(ADMIN) is None
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_new_proof_invalidates_old_payment_decision_and_old_send_buttons_do_nothing(env):
    ticket = await payment(env)
    await env.message(CLIENT, "https://example.org/old", message_id=982)
    first = env.store.ticket(ticket.id)
    await env.message(CLIENT, "https://example.org/new", message_id=983)
    latest = env.store.ticket(ticket.id)
    assert len(env.store.payment_proofs(ticket.id)) == 2
    await env.callback(CLIENT, f"c:send_draft:{ticket.id}:aaaaaaaaaaaa")
    assert len(env.store.payment_proofs(ticket.id)) == 2
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{first.version}")
    assert env.store.ticket(ticket.id).payment_stage == "review"
    assert env.store.ticket(ticket.id).version == latest.version
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{latest.version}")
    assert env.store.ticket(ticket.id).payment_stage == "confirmed"


async def test_forged_send_button_or_customer_namespace_cannot_send_old_operators_draft(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    draft = env.store.save_draft(ADMIN, ticket.id, "operator", "Приватный черновик", ADMIN, 984)
    await env.callback(OTHER, f"c:send_draft:{ticket.id}:{draft['token']}")
    await env.callback(ADMIN, f"c:send_draft:{ticket.id}:{draft['token']}")
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()
    assert env.store.draft(ADMIN) is None


@pytest.mark.parametrize("text", ["1", "123456", "?", "🙂", "Меню", "Назад"])
async def test_short_customer_messages_are_delivered_without_filtering_or_changing_payment(env, text):
    ticket = await order(env)
    await env.message(CLIENT, text)
    current = env.store.ticket(ticket.id)
    assert current.status == ticket.status and current.payment_stage == ticket.payment_stage
    rows = env.store.db.execute("SELECT body FROM messages WHERE role='user'").fetchall()
    assert [row["body"] for row in rows] == [text]
    assert text in last(env, ADMIN)["text"]


async def test_uncertain_direct_operator_delivery_is_never_resent(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    env.request.fail_chat, env.request.fail_error = CLIENT, TimedOut()
    await env.message(ADMIN, "Проверка доставки", message_id=985)
    await env.message(ADMIN, "Проверка доставки", message_id=985)
    row = env.store.db.execute("SELECT delivery FROM messages WHERE role='operator'").fetchone()
    assert row["delivery"] == "uncertain"
    attempts = [p for name, p in env.request.calls if name == "sendMessage" and p["chat_id"] == CLIENT and "Проверка доставки" in p["text"]]
    assert len(attempts) == 1


async def test_closed_order_rejects_new_photo_and_old_proof_send_buttons(env):
    ticket = await payment(env)
    env.store.map_customer_reply(CLIENT, 986, ticket.id)
    env.store.set_status(ticket.id, ticket.version, "cancelled", CLIENT)
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, photo=True, reply_to=986, message_id=987)
    await env.callback(CLIENT, f"c:send_draft:{ticket.id}:aaaaaaaaaaaa")
    assert not env.store.payment_proofs(ticket.id)
    assert env.store.find_source(CLIENT, 987) is None
    assert len(sent(env, ADMIN)) == before


async def test_restart_clears_old_unsent_previews_and_reply_modes(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    env.store.save_draft(ADMIN, ticket.id, "operator", "Не отправлять после перезапуска", ADMIN, 988)
    await env.app.post_init(env.app)
    assert env.store.focused_ticket(ADMIN) is None
    assert env.store.draft(ADMIN) is None
    await env.message(ADMIN, "Нет выбранного получателя")
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_competing_operator_cannot_take_over_an_active_direct_reply(env):
    second = 9002
    desk = env.app.handlers[0][0].callback.__self__
    desk.config = replace(desk.config, admin_ids=(ADMIN, second))
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Ответ от первого оператора")
    await env.callback(second, f"a:reply:{ticket.id}")
    assert env.store.focused_ticket(second) is None
    assert env.store.focused_ticket(ADMIN).id == ticket.id
    assert "Ответ от первого оператора" in last(env, CLIENT)["text"]
    await env.message(second, "Чужой ответ отправляться не должен")
    rows = env.store.db.execute("SELECT body FROM messages WHERE role='operator'").fetchall()
    assert [row["body"] for row in rows] == ["Ответ от первого оператора"]


@pytest.mark.parametrize("token", ["bad", "🙂", "a" * 12])
async def test_invalid_old_send_tokens_cannot_create_duplicate_payment_proofs(env, token):
    ticket = await payment(env)
    await env.message(CLIENT, photo=True, message_id=989)
    before = env.store.ticket(ticket.id)
    await env.callback(CLIENT, f"c:send_draft:{ticket.id}:{token}")
    assert len(env.store.payment_proofs(ticket.id)) == 1
    assert env.store.ticket(ticket.id).version == before.version
