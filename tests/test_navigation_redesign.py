"""Customer navigation, historical conversations and retired entry points."""

import pytest

from verifydesk import catalog, rules

from .conftest import ADMIN, CLIENT
from .test_upgrade import callbacks, last, order, sent


def ticket_count(env):
    return env.store.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]


def existing_discussion(env):
    env.store.remember_user(CLIENT, CLIENT, "Клиент", None)
    ticket, _ = env.store.create_ticket(CLIENT, kind="wholesale")
    return ticket


async def test_home_groups_primary_action_navigation_and_rules(env):
    await env.message(CLIENT, "/start")
    card = last(env, CLIENT)
    assert "Выберите сервис в каталоге или напишите его название в чат. Бот покажет цену и условия." in card["text"]
    rows = card["reply_markup"]["inline_keyboard"]
    assert [[button["callback_data"] for button in row] for row in rows] == [
        ["c:catalog"], ["c:profile"], ["c:help"], ["c:guide:general", "c:rules"],
    ]
    assert rows[0][0]["style"] == "primary"
    assert "Обсудить опт" not in card["text"]
    assert ticket_count(env) == 0
    assert not sent(env, ADMIN)


async def test_order_history_identifies_service_and_status_with_a_short_numbered_button(env):
    await env.callback(CLIENT, "c:order:fragment:standard")
    ticket = env.store.for_user(CLIENT, active_only=True)
    await env.callback(CLIENT, "c:orders:0")
    card = last(env, CLIENT)
    assert f"№{ticket.id:04d} · Telegram Fragment" in card["text"]
    assert "Ожидает оператора" in card["text"]
    assert card["reply_markup"]["inline_keyboard"][0][0]["text"] == f"Заказ №{ticket.id:04d}"
    await env.callback(CLIENT, f"c:view:{ticket.id}")
    assert "Telegram Fragment" in last(env, CLIENT)["text"]


async def test_active_order_is_reachable_from_home_without_new_order(env):
    ticket = await order(env)
    await env.callback(CLIENT, "c:home")
    rows = last(env, CLIENT)["reply_markup"]["inline_keyboard"]
    row_actions = [[button["callback_data"] for button in row] for row in rows]
    assert ["c:catalog"] in row_actions
    assert ["c:profile"] in row_actions
    assert callbacks(last(env, CLIENT))[0] == f"c:chat:{ticket.id}"
    await env.callback(CLIENT, callbacks(last(env, CLIENT))[0])
    assert env.store.customer_focus(CLIENT).id == ticket.id
    assert ticket_count(env) == 1


async def test_all_home_entry_points_keep_individual_service_buttons_in_catalog(env):
    def check_home(uid):
        rows = last(env, uid)["reply_markup"]["inline_keyboard"]
        buttons = [button for row in rows for button in row]
        assert any(b["callback_data"].endswith(":catalog") for b in buttons)
        assert not any(b["callback_data"].split(":")[1] in {"service", "offer", "order"} for b in buttons)
        assert not any(name in b["text"].casefold() for b in buttons for name in ("claude", "bybit", "alipay"))

    for command in ("/start", "/menu"):
        await env.message(CLIENT, command)
        check_home(CLIENT)
    ticket = await order(env)
    await env.callback(CLIENT, "c:home")
    check_home(CLIENT)
    env.store.set_status(ticket.id, ticket.version, "cancelled", ADMIN)
    await env.callback(CLIENT, "c:home")
    check_home(CLIENT)
    await env.message(ADMIN, "/preview")
    check_home(ADMIN)
    await env.callback(ADMIN, "p:home")
    check_home(ADMIN)
    await env.message(ADMIN, "/client")
    check_home(ADMIN)


def test_named_offer_recognizes_displayed_names_but_not_unrelated_messages():
    for selected in catalog.OFFERS.values():
        assert catalog.named_offer(selected.title.swapcase()) == selected
        assert catalog.named_offer(catalog.SHORT_TITLES.get(selected.service, selected.title)) == selected
    assert catalog.named_offer(" telegram   wallet ") == catalog.offer("telegram_wallet", "standard")
    assert catalog.named_offer("Huobi") == catalog.offer("htx", "standard")
    assert catalog.named_offer("Я хотел спросить про Bybit") is None
    assert catalog.named_offer("Cryp") is None


async def test_exact_service_name_opens_offer_then_creates_order_in_one_click(env):
    await env.message(CLIENT, "  CoinList  ")
    card = last(env, CLIENT)
    assert "CoinList" in card["text"] and "$50" in card["text"]
    assert ticket_count(env) == 0
    assert not sent(env, ADMIN)
    cta = callbacks(card)[0]
    assert cta == "c:order:coinlist:standard"
    await env.callback(CLIENT, cta)
    ticket = env.store.for_user(CLIENT)
    assert (ticket.service_code, ticket.price_usd) == ("coinlist", "50.00")
    await env.message(CLIENT, "Bybit", message_id=9584)
    assert env.store.find_source(CLIENT, 9584)["ticket_id"] == ticket.id
    assert ticket_count(env) == 1


async def test_exact_service_name_in_existing_discussion_is_delivered(env):
    discussion = existing_discussion(env)
    await env.message(CLIENT, "Claude", message_id=9585)
    assert env.store.find_source(CLIENT, 9585)["ticket_id"] == discussion.id
    assert env.store.for_user(CLIENT) is None


async def test_legacy_conversation_switches_do_not_duplicate_visible_order_action(env):
    discussion = existing_discussion(env)
    ticket = await order(env)
    for entry, order_action in (("c:profile", f"c:view:{ticket.id}"), ("c:help", "c:current")):
        await env.callback(CLIENT, entry)
        actions = callbacks(last(env, CLIENT))
        assert order_action in actions
        assert f"c:chat:{ticket.id}" not in actions
        assert f"c:chat:{discussion.id}" in actions
    await env.callback(CLIENT, f"c:chat:{discussion.id}")
    assert env.store.customer_focus(CLIENT).id == discussion.id


@pytest.mark.parametrize("service", ["claude", "bybit", "alipay"])
async def test_catalog_shortcut_opens_priced_offer_without_creating_order(env, service):
    from verifydesk import catalog

    await env.message(CLIENT, "/start")
    await env.callback(CLIENT, "c:catalog")
    selected = catalog.offer(service, "standard")
    shortcut = next(button for row in last(env, CLIENT)["reply_markup"]["inline_keyboard"] for button in row
                    if button["callback_data"] == f"c:service:{service}")
    assert catalog.offer_price(selected) in shortcut["text"]
    await env.callback(CLIENT, shortcut["callback_data"])
    card = last(env, CLIENT)
    assert selected.title in card["text"]
    assert catalog.offer_price(selected) in card["text"]
    assert f"c:order:{service}:standard" in callbacks(card)
    assert ticket_count(env) == 0
    assert not sent(env, ADMIN)
    assert "c:catalog" in callbacks(card)
    await env.callback(CLIENT, "c:catalog")
    assert shortcut["callback_data"] in callbacks(last(env, CLIENT))


@pytest.mark.parametrize("entry", ["c:home", "c:catalog", "c:profile", "c:help"])
async def test_customer_sections_have_no_new_wholesale_entry(env, entry):
    await env.callback(CLIENT, entry)
    assert "c:wholesale" not in callbacks(last(env, CLIENT))
    assert "Обсудить опт" not in last(env, CLIENT)["text"]
    assert ticket_count(env) == 0


async def test_stale_wholesale_button_cannot_create_or_notify(env):
    for _ in range(2):
        await env.callback(CLIENT, "c:wholesale")
        assert ticket_count(env) == 0
        assert any(data.startswith("c:category:") for data in callbacks(last(env, CLIENT)))
        assert "c:wholesale" not in callbacks(last(env, CLIENT))
    assert not sent(env, ADMIN)


async def test_stale_wholesale_button_preserves_current_order_focus(env):
    ticket = await order(env)
    before = len(sent(env, ADMIN))
    await env.callback(CLIENT, "c:wholesale")
    assert ticket_count(env) == 1
    assert env.store.customer_focus(CLIENT).id == ticket.id
    assert env.store.ticket(ticket.id).price_usd == ticket.price_usd
    assert len(sent(env, ADMIN)) == before


async def test_existing_legacy_discussion_opens_without_new_ticket_or_notification(env):
    discussion = existing_discussion(env)
    env.store.add_message(discussion.id, "user", "Сохранённая переписка", CLIENT, CLIENT, 920)
    await env.callback(CLIENT, "c:wholesale")
    assert env.store.customer_focus(CLIENT).id == discussion.id
    assert ticket_count(env) == 1
    assert f"c:history:{discussion.id}:0" in callbacks(last(env, CLIENT))
    assert "c:wholesale" not in callbacks(last(env, CLIENT))
    assert not sent(env, ADMIN)
    await env.callback(CLIENT, f"c:history:{discussion.id}:0")
    assert "Сохранённая переписка" in last(env, CLIENT)["text"]


async def test_only_existing_discussion_remains_reachable_from_home(env):
    discussion = existing_discussion(env)
    await env.message(CLIENT, "/start")
    card = last(env, CLIENT)
    resume = f"c:chat:{discussion.id}"
    assert "Сообщения в этой переписке получает оператор" in card["text"]
    assert "Цены и условия услуг смотрите в каталоге" in card["text"]
    assert card["reply_markup"]["inline_keyboard"][0][0]["text"] == "Открыть чат"
    actions = callbacks(card)
    assert actions[0] == resume and actions.count(resume) == 1
    assert "c:catalog" in actions and "c:wholesale" not in actions
    await env.callback(CLIENT, resume)
    assert env.store.customer_focus(CLIENT).id == discussion.id


async def test_closed_legacy_discussion_cannot_be_recreated_by_old_button(env):
    discussion = existing_discussion(env)
    env.store.set_status(discussion.id, discussion.version, "resolved", ADMIN)
    await env.callback(CLIENT, "c:wholesale")
    assert ticket_count(env) == 1
    assert env.store.for_user(CLIENT, active_only=True, kind="wholesale") is None
    assert "c:wholesale" not in callbacks(last(env, CLIENT))
    assert not sent(env, ADMIN)


async def test_closed_legacy_discussion_is_reachable_even_without_orders(env):
    discussion = existing_discussion(env)
    env.store.add_message(discussion.id, "user", "Архивный вопрос", CLIENT, CLIENT, 925)
    discussion = env.store.ticket(discussion.id)
    env.store.set_status(discussion.id, discussion.version, "resolved", ADMIN)
    assert env.store.profile(CLIENT).total_tickets == 0
    await env.callback(CLIENT, "c:profile")
    assert "c:orders:0" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, "c:orders:0")
    assert f"c:view:{discussion.id}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:view:{discussion.id}")
    assert f"c:history:{discussion.id}:0" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:history:{discussion.id}:0")
    assert "Архивный вопрос" in last(env, CLIENT)["text"]
    assert "c:wholesale" not in callbacks(last(env, CLIENT))
    assert not sent(env, ADMIN)


async def test_help_has_explicit_destinations_without_order(env):
    await env.callback(CLIENT, "c:help")
    data = callbacks(last(env, CLIENT))
    assert {"c:guide:general", "c:rules", "c:privacy", "c:home"} <= set(data)
    assert "c:current" not in data
    await env.callback(CLIENT, "c:guide:general")
    assert "c:help" in callbacks(last(env, CLIENT))
    assert ticket_count(env) == 0
    await env.callback(CLIENT, "c:help")
    await env.callback(CLIENT, "c:home")
    assert "c:catalog" in callbacks(last(env, CLIENT))


async def test_help_returns_to_current_order_when_one_exists(env):
    ticket = await order(env)
    await env.callback(CLIENT, "c:help")
    assert "c:current" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, "c:current")
    assert f"c:history:{ticket.id}:0" in callbacks(last(env, CLIENT))
    assert env.store.customer_focus(CLIENT).id == ticket.id


async def test_current_order_card_remains_a_native_reply_target(env):
    ticket = await order(env)
    await env.callback(CLIENT, "c:help", card=940)
    assert env.store.customer_reply_ticket(CLIENT, 940) is None
    await env.callback(CLIENT, "c:current", card=940)
    target = env.store.customer_reply_ticket(CLIENT, 940)
    assert target is not None and target.id == ticket.id
    await env.message(CLIENT, "Ответ на текущую карточку", reply_to=940, message_id=941)
    assert env.store.find_source(CLIENT, 941)["ticket_id"] == ticket.id


async def test_order_history_is_visible_and_returns_to_the_same_order(env):
    ticket = await order(env)
    await env.message(CLIENT, "Сохраните этот вопрос", message_id=930)
    await env.callback(CLIENT, f"c:view:{ticket.id}")
    assert {f"c:history:{ticket.id}:0", "c:profile", "c:home"} <= set(callbacks(last(env, CLIENT)))
    await env.callback(CLIENT, f"c:history:{ticket.id}:0")
    assert "Сохраните этот вопрос" in last(env, CLIENT)["text"]
    assert f"c:view:{ticket.id}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:view:{ticket.id}")
    assert env.store.customer_focus(CLIENT).id == ticket.id
    assert ticket_count(env) == 1


async def test_category_service_round_trip_keeps_second_page(env):
    await env.callback(CLIENT, "c:category:exchanges:1")
    page_services = [data for data in callbacks(last(env, CLIENT)) if data.startswith("c:service:")]
    assert 1 <= len(page_services) <= 8
    await env.callback(CLIENT, page_services[-1])
    assert "c:category:exchanges:1" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, "c:category:exchanges:1")
    assert [data for data in callbacks(last(env, CLIENT)) if data.startswith("c:service:")] == page_services
    assert ticket_count(env) == 0


async def test_operator_secondary_actions_are_discoverable_from_home(env):
    await env.message(ADMIN, "/admin")
    assert "a:more" in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, "a:more")
    assert {"a:clients:0", "a:list:closed:0", "a:mode:client", "a:home"} <= set(callbacks(last(env, ADMIN)))


@pytest.mark.parametrize("view", ["view", "details", "history"])
async def test_preview_order_navigation_never_redirects_real_conversation(env, view):
    ticket = await order(env, uid=ADMIN)
    discussion, _ = env.store.create_ticket(ADMIN, kind="wholesale")
    env.store.set_customer_focus(ADMIN, discussion.id)
    suffix = ":0" if view == "history" else ""
    await env.callback(ADMIN, f"p:{view}:{ticket.id}{suffix}")
    assert env.store.customer_focus(ADMIN).id == discussion.id
    assert "ПРЕДПРОСМОТР" in last(env, ADMIN)["text"]
    assert ticket_count(env) == 2


async def test_preview_attachment_has_no_real_reply_target_or_customer_actions(env):
    ticket = await order(env, uid=ADMIN)
    message_id, _ = env.store.add_message(ticket.id, "user", "Тестовый файл", ADMIN, ADMIN, 950)
    env.store.attach_message(message_id, "preview_file", "document")
    discussion, _ = env.store.create_ticket(ADMIN, kind="wholesale")
    env.store.set_customer_focus(ADMIN, discussion.id)
    before = len(env.request.calls)
    await env.callback(ADMIN, f"p:message:{ticket.id}:{message_id}", card=951)
    new_calls = env.request.calls[before:]
    assert not any(method in {"sendPhoto", "sendDocument"} for method, _ in new_calls)
    assert env.store.customer_reply_ticket(ADMIN, 951) is None
    assert env.store.reply_ticket(ADMIN, 951) is None
    assert env.store.customer_focus(ADMIN).id == discussion.id
    assert "Тестовый файл" in last(env, ADMIN)["text"]
    assert all(data.startswith("p:") or data == "a:home" for data in callbacks(last(env, ADMIN)))


async def test_unaccepted_rules_do_not_show_legacy_chat_shortcuts(env):
    discussion = existing_discussion(env)
    env.require_terms = True
    await env.message(CLIENT, "/start")
    assert rules.PAGES[0] in last(env, CLIENT)["text"]
    assert not any(data.startswith("c:chat:") for data in callbacks(last(env, CLIENT)))
    await env.callback(CLIENT, f"c:chat:{discussion.id}")
    assert env.store.customer_focus(CLIENT) is None
    assert rules.PAGES[0] in last(env, CLIENT)["text"]
    assert not sent(env, ADMIN)
