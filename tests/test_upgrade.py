"""Integration checks for service offers, personal cards and non-payable USDT previews."""

from pathlib import Path

import pytest

from verifydesk import catalog
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .payment_helpers import legacy_ticket


def sent(env, uid=None):
    return [
        params
        for method, params in env.request.calls
        if method in {"sendMessage", "editMessageText"} and (uid is None or params["chat_id"] == uid)
    ]


def last(env, uid):
    return sent(env, uid)[-1]


def buttons(params):
    return [button for row in params.get("reply_markup", {}).get("inline_keyboard", []) for button in row]


def callbacks(params):
    return [button["callback_data"] for button in buttons(params) if "callback_data" in button]


def assert_preview_navigation(params):
    data = callbacks(params)
    assert data and "a:home" in data
    assert all(value.startswith("p:") or value == "a:home" for value in data)


async def order(env, uid=CLIENT, service="claude", plan="standard"):
    await env.callback(uid, f"c:order:{service}:{plan}")
    return env.store.for_user(uid)


@pytest.mark.parametrize("plan,price", [("standard", "45.00")])
async def test_claude_offer_shows_price_and_own_data_consent_before_one_click_order(env, plan, price):
    await env.callback(CLIENT, f"c:offer:claude:{plan}")
    offer_screen = last(env, CLIENT)
    assert any(catalog.dollars(price) in b["text"] for b in buttons(offer_screen))
    assert "сами на свои данные" in offer_screen["text"]
    assert "Документы — только в официальном сервисе" in offer_screen["text"]
    assert "Оформляя заказ" in offer_screen["text"] and "подтверждаете" in offer_screen["text"]
    assert "аккаунт ваш" in offer_screen["text"] and "без списаний" in offer_screen["text"].lower()
    assert f"c:order:claude:{plan}" in callbacks(offer_screen)
    assert env.store.for_user(CLIENT) is None
    ticket = await order(env, plan=plan)
    assert (ticket.service_code, ticket.plan_code, ticket.price_usd) == ("claude", plan, price)
    assert ticket.status == "new"
    assert env.store.db.execute("SELECT consent_at FROM tickets WHERE id=?", (ticket.id,)).fetchone()[0] > 0
    assert "Сделка" in last(env, CLIENT)["text"]
    assert not last(env, CLIENT).get("reply_markup", {}).get("force_reply")


async def test_existing_active_order_is_not_silently_changed_to_another_service_or_price(env):
    first = await order(env)
    admin_notifications = len(sent(env, ADMIN))
    await order(env, service="alipay", plan="standard")
    current = env.store.for_user(CLIENT)
    assert current.id == first.id
    assert (current.service_code, current.plan_code, current.price_usd) == ("claude", "standard", "45.00")
    assert len(sent(env, ADMIN)) == admin_notifications
    assert "Claude" in last(env, CLIENT)["text"] and "$45" in last(env, CLIENT)["text"]


async def test_customer_card_never_discloses_operator_note(env):
    await order(env)
    env.store.set_note(CLIENT, "Секретная заметка оператора", ADMIN)
    await env.callback(CLIENT, "c:profile")
    text = last(env, CLIENT)["text"]
    assert "Мои заказы" in text and f"{CLIENT}" in text
    assert "Claude" in text and "заказов" in text.lower()
    assert "Секретная заметка" not in text
    assert not any(value.startswith("a:") for value in callbacks(last(env, CLIENT)))
    await env.callback(ADMIN, f"a:client:{CLIENT}")
    assert "Карточка клиента" in last(env, ADMIN)["text"]
    assert "Секретная заметка оператора" in last(env, ADMIN)["text"]


async def test_customer_cannot_open_another_client_card_or_operator_order_list(env):
    ticket = await order(env)
    env.store.set_note(CLIENT, "Приватный контекст клиента", ADMIN)
    for data in (f"a:client:{CLIENT}", f"a:orders:{CLIENT}:0", f"a:note:{CLIENT}"):
        await env.callback(OTHER, data)
        assert "Доступ" in last(env, OTHER)["text"]
        assert "Приватный контекст" not in last(env, OTHER)["text"]
        assert f"№{ticket.id:04d}" not in last(env, OTHER)["text"]
    assert env.store.note_reply_user(OTHER, 500) is None


async def test_customer_order_history_contains_only_owned_tickets(env):
    first = await order(env)
    legacy_ticket(env.store, first)
    env.store.set_status(first.id, first.version, "resolved", ADMIN)
    second = await order(env, service="alipay", plan="standard")
    other = await order(env, uid=OTHER, service="alipay", plan="standard")
    await env.callback(CLIENT, "c:orders:0")
    own_callbacks = callbacks(last(env, CLIENT))
    assert f"c:view:{first.id}" in own_callbacks
    assert f"c:view:{second.id}" in own_callbacks
    assert f"c:view:{other.id}" not in own_callbacks
    assert all(not value.startswith("a:") for value in own_callbacks)


async def test_operator_client_list_excludes_operator_profile(env):
    await order(env)
    await env.message(OTHER, "/start")
    await env.callback(ADMIN, "a:clients:0")
    data = callbacks(last(env, ADMIN))
    assert f"a:client:{CLIENT}" in data
    assert f"a:client:{OTHER}" in data
    assert f"a:client:{ADMIN}" not in data
    assert "Клиенты · 2" in last(env, ADMIN)["text"]


async def test_note_prompt_and_private_reply_survive_mapping_without_any_client_forward(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:note:{CLIENT}")
    prompt = env.store.db.execute(
        "SELECT message_id FROM note_targets WHERE chat_id=? AND user_id=? ORDER BY message_id DESC",
        (ADMIN, CLIENT),
    ).fetchone()[0]
    path = Path(env.store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    assert reopened.note_reply_user(ADMIN, prompt) == CLIENT
    reopened.close()
    before_client_calls = len(sent(env, CLIENT))
    before_messages = env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    await env.message(ADMIN, "Приватный контекст для следующего ответа", reply_to=prompt)
    assert env.store.profile(CLIENT).operator_note == "Приватный контекст для следующего ответа"
    assert len(sent(env, CLIENT)) == before_client_calls
    assert env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before_messages
    assert env.store.ticket(ticket.id).status == "new"
    assert env.store.reply_ticket(ADMIN, prompt) is None


async def test_note_can_be_cleared_without_sending_minus_to_customer(env):
    await order(env)
    env.store.set_note(CLIENT, "Старая заметка", ADMIN)
    await env.callback(ADMIN, f"a:note:{CLIENT}")
    prompt = env.store.db.execute("SELECT message_id FROM note_targets WHERE chat_id=?", (ADMIN,)).fetchone()[
        0
    ]
    before = len(sent(env, CLIENT))
    await env.message(ADMIN, "−", reply_to=prompt)
    assert env.store.profile(CLIENT).operator_note == ""
    assert len(sent(env, CLIENT)) == before


async def test_retired_payment_menu_returns_to_current_order_without_extra_choices(env):
    ticket = await order(env)
    await env.callback(CLIENT, f"c:pay:{ticket.id}")
    screen = last(env, CLIENT)
    assert "Сделка" in screen["text"]
    assert len(buttons(screen)) == 2
    assert not any(":network" in value for value in callbacks(screen))
    assert not any(method in {"sendInvoice", "createInvoiceLink"} for method, _ in env.request.calls)


async def test_retired_network_pages_cannot_restore_old_button_menus(env):
    ticket = await order(env)
    for group in catalog.NETWORK_GROUPS:
        for offset in (0, 8, 16):
            await env.callback(CLIENT, f"c:networks:{ticket.id}:{group}:{offset}")
            assert len(buttons(last(env, CLIENT))) == 2
            assert not any(":network" in value for value in callbacks(last(env, CLIENT)))
    assert env.store.ticket(ticket.id).demo_network is None


@pytest.mark.parametrize("network", ["usdt_tron", "usdt_ton", "usdt0_arbitrum", "bridged_bnb"])
async def test_retired_network_selection_is_read_only(env, network):
    initial = await order(env)
    await env.callback(CLIENT, f"c:network:{initial.id}:{network}")
    ticket = env.store.ticket(initial.id)
    assert ticket == initial
    assert ticket.demo_network is None
    assert len(callbacks(last(env, CLIENT))) == 2


async def test_other_customer_cannot_view_or_choose_mock_network_for_ticket(env):
    ticket = await order(env)
    for value in (
        f"c:pay:{ticket.id}",
        f"c:networks:{ticket.id}:usdt:0",
        f"c:network:{ticket.id}:usdt_tron",
    ):
        await env.callback(OTHER, value)
        assert "недоступен" in last(env, OTHER)["text"]
        assert "$45" not in last(env, OTHER)["text"]
    assert env.store.ticket(ticket.id).demo_network is None


async def test_mock_selection_cannot_change_closed_ticket_or_unknown_network(env):
    ticket = await order(env)
    await env.callback(CLIENT, f"c:network:{ticket.id}:not_a_network")
    assert env.store.ticket(ticket.id).demo_network is None
    legacy_ticket(env.store, ticket)
    closed = env.store.set_status(ticket.id, ticket.version, "resolved", ADMIN)
    await env.callback(CLIENT, f"c:network:{ticket.id}:usdt_ton")
    latest = env.store.ticket(ticket.id)
    assert latest.status == "resolved" and latest.version == closed.version
    assert latest.demo_network is None
    assert "выполнен" in last(env, CLIENT)["text"].lower()
    await env.callback(CLIENT, f"c:pay:{ticket.id}")
    assert "выполнен" in last(env, CLIENT)["text"].lower()
    assert not any(value.startswith(f"c:network:{ticket.id}:") for value in callbacks(last(env, CLIENT)))


async def test_admin_preview_entry_and_navigation_keep_callback_namespace_read_only(env):
    await env.message(ADMIN, "/preview")
    assert "ПРЕДПРОСМОТР" in last(env, ADMIN)["text"]
    assert_preview_navigation(last(env, ADMIN))
    for value in (
        "p:catalog",
        "p:offer:claude:standard",
        "p:guide:claude",
        "p:profile",
        "p:orders:0",
        "p:current",
        "p:home",
    ):
        await env.callback(ADMIN, value)
        assert "ПРЕДПРОСМОТР" in last(env, ADMIN)["text"]
        assert_preview_navigation(last(env, ADMIN))
    assert env.store.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0


async def test_preview_cannot_create_close_or_change_mock_network_even_for_admin_owned_ticket(env):
    env.store.remember_user(ADMIN, ADMIN, "Оператор", None)
    ticket, _ = env.store.create_ticket(ADMIN, "claude", "armenia", "35")
    initial = tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone())
    for value in (
        "p:create",
        "p:order:claude:standard",
        f"p:close:{ticket.id}:{ticket.version}",
        f"p:network:{ticket.id}:usdt_ton",
        f"p:write:{ticket.id}",
    ):
        await env.callback(ADMIN, value)
        assert "не отправляются" in last(env, ADMIN)["text"]
        assert "не сохраняется" in last(env, ADMIN)["text"]
        assert_preview_navigation(last(env, ADMIN))
        assert not last(env, ADMIN).get("reply_markup", {}).get("force_reply")
    assert tuple(env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone()) == initial
    assert env.store.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1
    assert not env.store.db.execute("SELECT message_id FROM customer_reply_targets").fetchall()


async def test_client_cannot_use_preview_command_or_forged_preview_callback(env):
    await env.message(CLIENT, "/preview")
    assert "только оператору" in last(env, CLIENT)["text"]
    for value in ("p:catalog", "p:order:claude:standard", "a:preview"):
        await env.callback(CLIENT, value)
        assert "Доступ" in last(env, CLIENT)["text"]
    assert env.store.for_user(CLIENT) is None


async def test_preview_ticket_history_and_payment_buttons_remain_preview_scoped(env):
    env.store.remember_user(ADMIN, ADMIN, "Оператор", None)
    ticket, _ = env.store.create_ticket(ADMIN, "claude", "armenia", "35")
    mid, _ = env.store.add_message(ticket.id, "user", "Текст" * 300, ADMIN, ADMIN, 99)
    for value in (
        f"p:view:{ticket.id}",
        f"p:history:{ticket.id}:0",
        f"p:message:{ticket.id}:{mid}",
        f"p:pay:{ticket.id}",
        f"p:networks:{ticket.id}:usdt:0",
    ):
        await env.callback(ADMIN, value)
        assert "ПРЕДПРОСМОТР" in last(env, ADMIN)["text"]
        assert_preview_navigation(last(env, ADMIN))
    assert env.store.ticket(ticket.id).demo_network is None


async def test_help_only_offers_claude_and_keeps_official_owner_verification_guidance(env):
    await env.message(CLIENT, "/help")
    screen = last(env, CLIENT)
    assert callbacks(screen) == ["c:current"]
    assert all(service not in screen["text"].lower() for service in ("alipay", "chatgpt", "gemini"))
    assert not any(service in value for value in callbacks(screen) for service in ("alipay", "chatgpt", "gemini"))
    await env.callback(CLIENT, "c:guide:claude")
    guide = last(env, CLIENT)
    assert "Claude" in guide["text"]
    assert "сво" in guide["text"].lower()
    assert "Проверку проходите самостоятельно" in guide["text"]
    assert len(buttons(guide)) == 1


@pytest.mark.parametrize("command,expected", [("/services", "Каталог услуг"), ("/profile", "Мои заказы")])
async def test_new_customer_commands_are_registered_and_reach_the_right_screen(env, command, expected):
    await env.message(CLIENT, command)
    assert expected in last(env, CLIENT)["text"]


async def test_clients_command_is_registered_and_guarded(env):
    await env.message(CLIENT, "/clients")
    assert "только оператору" in last(env, CLIENT)["text"]
    await env.message(ADMIN, "/clients")
    assert "Клиенты" in last(env, ADMIN)["text"]


@pytest.mark.parametrize("entry", ["/status", "Текст до создания заявки", "c:prepare"])
async def test_new_customer_entries_reach_catalog_without_legacy_unpriced_order(env, entry):
    if entry.startswith("c:"):
        await env.callback(CLIENT, entry)
    else:
        await env.message(CLIENT, entry)
    data = callbacks(last(env, CLIENT))
    assert "c:create" not in data
    if "c:catalog" in data:
        await env.callback(CLIENT, "c:catalog")
        data = callbacks(last(env, CLIENT))
    assert "c:category:other" in data
    await env.callback(CLIENT, "c:category:other")
    assert "c:service:claude" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, "c:service:claude")
    data = callbacks(last(env, CLIENT))
    assert "c:order:claude:standard" in data
    assert "c:create" not in data
    assert env.store.for_user(CLIENT) is None
