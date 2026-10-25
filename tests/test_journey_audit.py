"""Button-driven regression checks for complete client and operator journeys.

These use isolated SQLite and Telegram's update parser; no live bot or client data.
"""

import re

import pytest
from telegram import Update

from verifydesk import catalog

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last, order, sent
from .payment_helpers import legacy_ticket


async def press(env, uid, data, card=500):
    """Follow only a button actually offered on the current screen."""
    assert data in callbacks(last(env, uid)), (data, callbacks(last(env, uid)))
    before = len(sent(env, uid))
    await env.callback(uid, data, card=card)
    assert len(sent(env, uid)) > before, f"Button produced no screen: {data}"
    assert not env.errors


async def reply_to_own_text(env, text, source_message, message_id=99000):
    user = {"id": CLIENT, "is_bot": False, "first_name": "Клиент"}
    chat = {"id": CLIENT, "type": "private", "first_name": "Клиент"}
    update = Update.de_json(
        {
            "update_id": message_id,
            "message": {
                "message_id": message_id,
                "date": 1700000000,
                "from": user,
                "chat": chat,
                "text": text,
                "reply_to_message": {
                    "message_id": source_message,
                    "date": 1700000000,
                    "from": user,
                    "chat": chat,
                    "text": "Мой предыдущий вопрос",
                },
            },
        },
        env.app.bot,
    )
    await env.app.process_update(update)
    assert not env.errors


async def test_complete_priced_order_manual_payment_reply_and_completion(env):
    await env.message(CLIENT, "/start")
    await press(env, CLIENT, "c:service:claude")
    await press(env, CLIENT, "c:offer:claude:armenia")
    await press(env, CLIENT, "c:order:claude:armenia")
    ticket = env.store.for_user(CLIENT)
    assert (ticket.price_usd, ticket.status, ticket.payment_stage) == ("35.00", "new", "not_requested")
    assert "Ожидает оператора" in last(env, CLIENT)["text"]

    await env.message(CLIENT, "На втором шаге появляется ошибка проверки")
    assert env.store.ticket(ticket.id).unread == 1
    await env.message(ADMIN, "/admin")
    await press(env, ADMIN, "a:next")
    current = env.store.ticket(ticket.id)
    assert current.status == "new"  # Opening a new order does not start unpaid work.
    await press(env, ADMIN, f"a:request_payment:{ticket.id}:{current.version}")
    assert env.store.ticket(ticket.id).payment_stage == "awaiting_payment"
    assert "тестовый режим" in last(env, CLIENT)["text"]
    assert "переводить не нужно" in last(env, CLIENT)["text"].lower()

    await env.proof(CLIENT, "Тестовое подтверждение: https://example.org/mock-proof/123")
    current = env.store.ticket(ticket.id)
    assert current.status == "new" and current.payment_stage == "review"
    assert "https://example.org/mock-proof/123" in last(env, ADMIN)["text"]
    await press(env, ADMIN, f"a:confirm_payment:{ticket.id}:{current.version}")
    current = env.store.ticket(ticket.id)
    assert current.status == "in_progress" and current.payment_stage == "confirmed"
    assert "В работе" in last(env, CLIENT)["text"]

    await press(env, ADMIN, f"a:reply:{ticket.id}")
    prompt_id = env.store.db.execute(
        "SELECT MAX(message_id) FROM reply_targets WHERE chat_id=?", (ADMIN,),
    ).fetchone()[0]
    await env.message(ADMIN, "Пришлите текст ошибки без личных данных", reply_to=prompt_id)
    assert env.store.ticket(ticket.id).status == "waiting_user"
    assert "Пришлите текст ошибки" in last(env, CLIENT)["text"]
    assert "В работе" in last(env, CLIENT)["text"]
    await env.message(CLIENT, "Страница сообщает, что ссылка истекла")
    assert env.store.ticket(ticket.id).status == "in_progress"

    await press(env, CLIENT, f"c:view:{ticket.id}")
    await press(env, CLIENT, "c:guide:claude")
    assert "Строго следуйте нашей инструкции" in last(env, CLIENT)["text"]
    await press(env, CLIENT, "c:current")

    await env.callback(ADMIN, f"a:view:{ticket.id}")
    version = env.store.ticket(ticket.id).version
    await press(env, ADMIN, f"a:set:{ticket.id}:{version}:resolved")
    assert env.store.ticket(ticket.id).status == "in_progress"
    await press(env, ADMIN, f"a:confirm:{ticket.id}:{version}:resolved")
    assert env.store.ticket(ticket.id).status == "resolved"
    assert "Заказ выполнен" in last(env, CLIENT)["text"]
    assert not any(":cancel:" in value for value in callbacks(last(env, CLIENT)))
    await env.message(CLIENT, "/profile")
    profile = env.store.profile(CLIENT)
    assert (profile.total_tickets, profile.active_tickets, profile.resolved_tickets) == (1, 0, 1)
    await press(env, CLIENT, "c:orders:0")
    await press(env, CLIENT, f"c:view:{ticket.id}")
    await press(env, CLIENT, "c:service:claude")
    await press(env, CLIENT, "c:offer:claude:europe")
    await press(env, CLIENT, "c:order:claude:europe")
    followup = env.store.for_user(CLIENT)
    assert followup.id != ticket.id and (followup.service_code, followup.plan_code) == ("claude", "europe")
    assert followup.price_usd == "50.00" and followup.payment_stage == "not_requested"


async def test_every_retired_network_button_returns_to_single_current_order_action(env):
    ticket = await order(env)
    before = env.store.ticket(ticket.id)
    for network in catalog.NETWORKS:
        await env.callback(CLIENT, f"c:network:{ticket.id}:{network.code}")
        assert len(callbacks(last(env, CLIENT))) == 1
        assert not any(":network" in value for value in callbacks(last(env, CLIENT)))
        assert env.store.ticket(ticket.id) == before
    assert not any(method in {"sendInvoice", "createInvoiceLink"} for method, _ in env.request.calls)


@pytest.mark.parametrize("admin", [False, True])
async def test_history_navigation_reaches_all_own_tickets_over_three_pages(env, admin):
    env.store.remember_user(CLIENT, CLIENT, "Клиент", None)
    expected = set()
    for index in range(18):
        ticket, _ = env.store.create_ticket(CLIENT, "claude", "armenia", "35.00")
        expected.add(ticket.id)
        if index < 17:
            legacy_ticket(env.store, ticket)
            env.store.set_status(ticket.id, ticket.version, "resolved", ADMIN)
    stranger = await order(env, OTHER)
    uid, prefix = (ADMIN, "a") if admin else (CLIENT, "c")
    base = f"a:orders:{CLIENT}" if admin else "c:orders"
    await env.callback(uid, base + ":0")
    found = set()
    for offset in (0, 8, 16):
        screen = last(env, uid)
        found.update(
            int(value.rsplit(":", 1)[-1])
            for value in callbacks(screen)
            if value.startswith(prefix + ":view:")
        )
        assert f"{prefix}:view:{stranger.id}" not in callbacks(screen)
        if offset < 16:
            await press(env, uid, f"{base}:{offset + 8}")
    assert found == expected
    await press(env, uid, f"{base}:8")
    await press(env, uid, f"{base}:0")
    await press(env, uid, f"a:client:{CLIENT}" if admin else "c:profile")


async def test_client_list_pagination_reaches_all_real_clients_and_preserves_empty_state(env):
    await env.callback(ADMIN, "a:clients:0")
    assert not any(value.startswith("a:client:") for value in callbacks(last(env, ADMIN)))
    clients = set(range(200, 218))
    for uid in clients:
        env.store.remember_user(uid, uid, f"Клиент {uid}", None)
    await env.callback(ADMIN, "a:clients:0")
    seen = set()
    for offset in (0, 8, 16):
        seen.update(
            int(value.rsplit(":", 1)[-1])
            for value in callbacks(last(env, ADMIN))
            if value.startswith("a:client:")
        )
        if offset < 16:
            await press(env, ADMIN, f"a:clients:{offset + 8}")
    assert seen == clients
    await press(env, ADMIN, "a:clients:8")
    await press(env, ADMIN, "a:clients:0")
    await press(env, ADMIN, "a:home")


@pytest.mark.parametrize("destination", ["a:home", "a:more", "a:details:{ticket_id}", "a:clients:0", f"a:client:{CLIENT}", "a:preview"])
async def test_repurposed_operator_card_cannot_keep_old_customer_reply_target(env, destination):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:view:{ticket.id}", card=700)
    assert env.store.reply_ticket(ADMIN, 700).id == ticket.id
    await env.callback(ADMIN, destination.format(ticket_id=ticket.id), card=700)
    assert env.store.reply_ticket(ADMIN, 700) is None
    count = len(sent(env, CLIENT))
    await env.message(ADMIN, "Не должно уйти клиенту из другого экрана", reply_to=700)
    assert len(sent(env, CLIENT)) == count
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_closed_ticket_reply_prompt_cannot_send_to_new_active_ticket(env):
    first = await order(env)
    await env.callback(ADMIN, f"a:reply:{first.id}")
    prompt = env.store.db.execute("SELECT MAX(message_id) FROM reply_targets WHERE chat_id=?", (ADMIN,)).fetchone()[0]
    legacy_ticket(env.store, first)
    env.store.set_status(first.id, first.version, "resolved", ADMIN)
    second = await order(env, plan="europe")
    before = len(sent(env, CLIENT))
    await env.message(ADMIN, "Ответ по старой заявке", reply_to=prompt)
    assert len(sent(env, CLIENT)) == before
    assert env.store.ticket(second.id).status == "new"
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_operator_confirmation_cannot_close_after_customer_changed_waiting_status(env):
    ticket = await order(env)
    legacy_ticket(env.store, ticket)
    waiting = env.store.set_status(ticket.id, ticket.version, "waiting_user", ADMIN)
    await env.callback(ADMIN, f"a:set:{ticket.id}:{waiting.version}:resolved")
    confirmation = f"a:confirm:{ticket.id}:{waiting.version}:resolved"
    assert confirmation in callbacks(last(env, ADMIN))
    await env.message(CLIENT, "У меня появился новый вопрос")
    await env.callback(ADMIN, confirmation)
    assert env.store.ticket(ticket.id).status == "in_progress"
    assert env.store.ticket(ticket.id).unread == 1


async def test_closed_ticket_buttons_remain_read_only_after_a_new_request(env):
    first = await order(env)
    legacy_ticket(env.store, first)
    first = env.store.set_status(first.id, first.version, "resolved", ADMIN)
    current = await order(env, plan="europe")
    snapshot = tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (first.id,)).fetchone())
    for data in (
        f"c:pay:{first.id}",
        f"c:networks:{first.id}:usdt0:0",
        f"c:network:{first.id}:usdt_tron",
        f"c:cancel:{first.id}:{first.version}",
        f"c:close:{first.id}:{first.version}",
        f"a:reply:{first.id}",
        f"a:set:{first.id}:{first.version}:in_progress",
    ):
        await env.callback(ADMIN if data.startswith("a:") else CLIENT, data)
    assert tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (first.id,)).fetchone()) == snapshot
    assert env.store.for_user(CLIENT, active_only=True).id == current.id


async def test_malformed_or_unknown_button_arguments_do_not_mutate_order(env):
    ticket = await order(env)
    before = tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone())
    for data in (
        "c:view:not_a_number", "c:order:missing:standard", "c:offer", "c:network:1:no_such_network",
        f"c:networks:{ticket.id}:unknown:0", f"a:set:{ticket.id}:{ticket.version}:not_a_status",
        "a:list:unknown:0", "a:client:not_a_number", "a:note:999999999", "c:orders:bad",
    ):
        uid = ADMIN if data.startswith("a:") else CLIENT
        await env.callback(uid, data)
        assert not env.errors
        assert callbacks(last(env, uid)), "Invalid input must have actionable recovery"
    after = tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone())
    assert before == after


async def test_every_generated_callback_stays_within_telegram_size_limit(env):
    ticket = await order(env)
    for data in (
        "c:home", "c:catalog", "c:profile", "c:orders:0", "c:help", "c:privacy",
        "a:home", "a:clients:0", f"a:client:{CLIENT}", f"a:orders:{CLIENT}:0",
        f"a:view:{ticket.id}", f"a:status:{ticket.id}", f"c:pay:{ticket.id}",
    ):
        await env.callback(ADMIN if data.startswith("a:") else CLIENT, data)
    for params in sent(env):
        for value in callbacks(params):
            assert 1 <= len(value.encode()) <= 64
            assert re.match(r"[cap]:[a-z_]+(?::[a-z0-9_]+)*$", value)


async def test_legacy_create_button_leads_to_current_offers_before_order_creation(env):
    await env.callback(CLIENT, "c:create")
    assert env.store.for_user(CLIENT) is None
    assert "c:service:claude" in callbacks(last(env, CLIENT))
    await press(env, CLIENT, "c:service:claude")
    assert "c:offer:claude:armenia" in callbacks(last(env, CLIENT))
    assert "c:offer:claude:europe" in callbacks(last(env, CLIENT))
    assert "c:create" not in callbacks(last(env, CLIENT))


@pytest.mark.parametrize("plan", ["armenia", "europe"])
async def test_instructions_keep_selected_claude_plan_as_return_destination(env, plan):
    await env.callback(CLIENT, f"c:offer:claude:{plan}")
    guide = f"c:guide:claude:{plan}"
    await env.callback(CLIENT, guide)
    assert f"c:offer:claude:{plan}" in callbacks(last(env, CLIENT))
    await press(env, CLIENT, f"c:offer:claude:{plan}")
    assert f"c:order:claude:{plan}" in callbacks(last(env, CLIENT))


async def test_latest_admin_history_marks_seen_messages_read_but_older_page_does_not(env):
    ticket = await order(env)
    for index in range(6):
        await env.message(CLIENT, f"Сообщение {index}")
    assert env.store.ticket(ticket.id).unread == 6
    await env.callback(ADMIN, f"a:history:{ticket.id}:1")
    assert env.store.ticket(ticket.id).unread == 6
    await env.callback(ADMIN, f"a:history:{ticket.id}:0")
    assert env.store.ticket(ticket.id).unread == 0


async def test_explicit_customer_prompt_allows_operator_to_test_a_real_own_request(env):
    ticket = await order(env, uid=ADMIN)
    # The self-test account also receives the operator notification after order creation.
    await env.callback(ADMIN, f"c:view:{ticket.id}")
    assert f"c:write:{ticket.id}" in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, f"c:write:{ticket.id}")
    assert last(env, ADMIN)["reply_markup"]["force_reply"]
    prompt = env.store.db.execute(
        "SELECT MAX(message_id) FROM customer_reply_targets WHERE chat_id=?", (ADMIN,)
    ).fetchone()[0]
    assert env.store.customer_reply_ticket(ADMIN, prompt).id == ticket.id
    await env.message(ADMIN, "Проверяю собственную заявку как клиент", reply_to=prompt)
    row = env.store.db.execute("SELECT role,body FROM messages WHERE source_chat=?", (ADMIN,)).fetchone()
    assert row["role"] == "user" and row["body"] == "Проверяю собственную заявку как клиент"
    assert env.store.ticket(ticket.id).unread == 1


async def test_customer_reply_to_closed_operator_message_cannot_go_to_new_active_request(env):
    first = await order(env)
    env.store.map_reply(ADMIN, 777, first.id)
    await env.message(ADMIN, "Ответ по первой заявке", reply_to=777)
    old_response = env.store.db.execute(
        "SELECT MAX(message_id) FROM customer_reply_targets WHERE chat_id=?", (CLIENT,)
    ).fetchone()[0]
    assert env.store.customer_reply_ticket(CLIENT, old_response).id == first.id
    updated = env.store.ticket(first.id)
    legacy_ticket(env.store, first)
    env.store.set_status(first.id, updated.version, "resolved", ADMIN)
    second = await order(env, plan="europe")
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Это ответ на старую переписку", reply_to=old_response)
    assert len(sent(env, ADMIN)) == before
    assert not env.store.db.execute("SELECT id FROM messages WHERE body=?", ("Это ответ на старую переписку",)).fetchall()
    assert env.store.for_user(CLIENT, active_only=True).id == second.id
    assert callbacks(last(env, CLIENT)), "Recovery must offer a button, not require memorizing a command"


async def test_forged_write_button_never_opens_another_customers_reply_prompt(env):
    ticket = await order(env)
    await env.callback(OTHER, f"c:write:{ticket.id}")
    assert not last(env, OTHER).get("reply_markup", {}).get("force_reply")
    assert not env.store.db.execute(
        "SELECT message_id FROM customer_reply_targets WHERE chat_id=?", (OTHER,)
    ).fetchall()
    await env.message(OTHER, "Попытка написать чужому оператору")
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchall()


@pytest.mark.parametrize("status", ["new", "in_progress"])
async def test_new_customer_message_invalidates_pending_completion_even_without_status_change(env, status):
    ticket = await order(env)
    ticket = legacy_ticket(env.store, ticket)
    if status == "in_progress":
        ticket = env.store.set_status(ticket.id, ticket.version, status, ADMIN)
    await env.callback(ADMIN, f"a:set:{ticket.id}:{ticket.version}:resolved")
    confirmation = f"a:confirm:{ticket.id}:{ticket.version}:resolved"
    assert confirmation in callbacks(last(env, ADMIN))
    await env.message(CLIENT, "Подождите, проблема ещё не решена")
    await env.callback(ADMIN, confirmation)
    current = env.store.ticket(ticket.id)
    assert current.status == status and current.version > ticket.version
    assert current.unread == 1


async def test_self_operator_card_changed_from_customer_view_routes_reply_as_operator(env):
    ticket = await order(env, uid=ADMIN)
    env.store.map_customer_reply(ADMIN, 700, ticket.id)
    await env.callback(ADMIN, f"a:view:{ticket.id}", card=700)
    assert env.store.customer_reply_ticket(ADMIN, 700) is None
    assert env.store.reply_ticket(ADMIN, 700).id == ticket.id
    await env.message(ADMIN, "Ответ оператора после смены экрана", reply_to=700)
    row = env.store.db.execute(
        "SELECT role FROM messages WHERE body=?", ("Ответ оператора после смены экрана",)
    ).fetchone()
    assert row["role"] == "operator"


async def test_customer_menu_replacing_reply_card_does_not_keep_hidden_write_target(env):
    ticket = await order(env)
    env.store.map_customer_reply(CLIENT, 700, ticket.id)
    await env.callback(CLIENT, "c:catalog", card=700)
    assert env.store.customer_reply_ticket(CLIENT, 700) is None
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Reply к каталогу не должен быть скрытой заявкой", reply_to=700)
    assert len(sent(env, ADMIN)) == before
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchall()


async def test_reply_to_own_message_in_closed_ticket_cannot_attach_to_new_request(env):
    first = await order(env)
    await env.message(CLIENT, "Мой предыдущий вопрос", message_id=900)
    first = env.store.ticket(first.id)
    legacy_ticket(env.store, first)
    env.store.set_status(first.id, first.version, "resolved", ADMIN)
    second = await order(env, plan="europe")
    before = len(sent(env, ADMIN))
    await reply_to_own_text(env, "Уточнение по старому вопросу", 900)
    assert len(sent(env, ADMIN)) == before
    assert not env.store.db.execute(
        "SELECT id FROM messages WHERE body=?", ("Уточнение по старому вопросу",)
    ).fetchall()
    assert env.store.for_user(CLIENT, active_only=True).id == second.id
    assert callbacks(last(env, CLIENT))


async def test_reply_to_own_current_message_keeps_the_same_ticket(env):
    ticket = await order(env)
    await env.message(CLIENT, "Мой предыдущий вопрос", message_id=900)
    await reply_to_own_text(env, "Уточнение к действующему вопросу", 900)
    row = env.store.db.execute(
        "SELECT ticket_id,role FROM messages WHERE body=?", ("Уточнение к действующему вопросу",)
    ).fetchone()
    assert (row["ticket_id"], row["role"]) == (ticket.id, "user")
    assert "Уточнение к действующему вопросу" in last(env, ADMIN)["text"]


async def test_reply_to_customer_card_and_save_receipt_routes_explicitly(env):
    ticket = await order(env)
    await env.callback(CLIENT, f"c:view:{ticket.id}", card=700)
    assert env.store.customer_reply_ticket(CLIENT, 700).id == ticket.id
    await env.message(CLIENT, "Вопрос из карточки", reply_to=700)
    receipt = env.store.db.execute(
        "SELECT MAX(message_id) FROM customer_reply_targets WHERE chat_id=?", (CLIENT,)
    ).fetchone()[0]
    assert receipt != 700
    assert env.store.customer_reply_ticket(CLIENT, receipt).id == ticket.id
    await env.message(CLIENT, "Дополнение в ответ на квитанцию", reply_to=receipt)
    rows = env.store.db.execute("SELECT ticket_id,role FROM messages WHERE role='user'").fetchall()
    assert len(rows) == 2 and all(row["ticket_id"] == ticket.id for row in rows)
    current = env.store.ticket(ticket.id)
    legacy_ticket(env.store, current)
    env.store.set_status(current.id, current.version, "resolved", ADMIN)
    await order(env, plan="europe")
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Ответ на старую квитанцию", reply_to=receipt)
    assert len(sent(env, ADMIN)) == before
    assert not env.store.db.execute(
        "SELECT id FROM messages WHERE body=?", ("Ответ на старую квитанцию",)
    ).fetchall()


@pytest.mark.parametrize('name', ['\ufe0e\ufe0e', '\u200b\u200c', '   '])
def test_invisible_telegram_name_has_readable_card_fallback(store, name):
    store.remember_user(CLIENT, CLIENT, name, 'client')
    assert store.profile(CLIENT).display_name == 'Клиент'
    store.remember_user(CLIENT, CLIENT, 'Иван ✨', 'client')
    assert store.profile(CLIENT).display_name == 'Иван ✨'
