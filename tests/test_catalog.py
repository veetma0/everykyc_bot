"""Expanded prices, navigation, historical orders, and mandatory rules."""

import pytest

from verifydesk import catalog, rules, screens, ui
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT
from .test_upgrade import callbacks, last, order, sent


EXPECTED_PRICES = {
    "bybit": 50, "kraken": 45, "whitebit": 45, "mexc": 45, "bitget": 45, "okx": 45,
    "kucoin": 45, "bingx": 45, "s1lkpay": 60, "paxful": 45, "coinlist": 50,
    "htx": 45, "bitpapa": 45, "okcoin": 45, "gate": 45, "crypto_com": 45,
    "localbitcoins": 45, "garantex": 40, "in1": 65, "eldorado": 80,
    "g2g_skrill": 70, "igvault": 45, "z2u": 45, "u7buy": 45, "g2g": 45,
    "alipay": 50, "webmoney": 50, "advcash": 70, "lava": 70,
    "fragment": 45, "telegram_wallet": 45, "cryptobot": 45,
    "stake": 40, "bcgame": 45, "megadice": 45, "mellstroy": 45,
    "cloudbet": 45, "dragon_money": 45, "pm_by": 45, "1win": 45, "luckybird": 45,
    "claude": 45, "hetzner": 100, "fansly": 60, "webshare": 45, "soax": 50,
    "fanvue": 60, "iproyal": 45, "astroproxy": 45, "openloot": 40, "lis_skins": 45,
    "csfloat": 45, "cs_money": 45, "csgo_roll": 45, "clash_gg": 45,
    "rain_gg": 45, "roblox": 45, "faceit": 35,
}


def test_complete_owner_price_list_and_telegram_limits():
    assert {o.service: o.price_usd for o in catalog.OFFERS.values()} == {
        code: f"{amount:.2f}" for code, amount in EXPECTED_PRICES.items()
    }
    assert all(o.plan == "standard" for o in catalog.OFFERS.values())
    assert "binance" not in EXPECTED_PRICES
    assert catalog.offer("eldorado", "standard").price_from
    assert not catalog.offer("localbitcoins", "standard").available
    cards = [screens.catalog_card(), ui.home("Эврикус", None)]
    cards += [screens.category_card(code, page) for code in catalog.CATEGORIES
              for page in range((len(screens.category_offers(code)) + 7) // 8)]
    cards += [screens.offer_card(o) for o in catalog.OFFERS.values()]
    cards += [rules.card(i) for i in range(len(rules.PAGES))]
    for text, keyboard in cards:
        assert ui.text_units(text) <= 4096
        assert "Армения" not in text and "Европа" not in text
        assert all(len(b.callback_data.encode()) <= 64 for row in keyboard.inline_keyboard for b in row)


@pytest.mark.parametrize("category", catalog.CATEGORIES)
async def test_each_category_exposes_services_and_current_prices(env, category):
    offers = screens.category_offers(category)
    seen = []
    for page in range((len(offers) + 7) // 8):
        await env.callback(CLIENT, f"c:category:{category}:{page}")
        card = last(env, CLIENT)
        assert catalog.CATEGORIES[category] in card["text"]
        assert "Доступность для вашей страны уточнит оператор" in card["text"]
        service_rows = [row for row in card["reply_markup"]["inline_keyboard"]
                        if row[0].get("callback_data", "").startswith("c:service:")]
        assert all(1 <= len(row) <= 2 for row in service_rows)
        assert sum(map(len, service_rows)) <= 8
        for selected in offers[page * 8:(page + 1) * 8]:
            assert f"c:service:{selected.service}" in callbacks(card)
            assert selected.title not in card["text"]
            button = next(b for row in service_rows for b in row
                          if b["callback_data"] == f"c:service:{selected.service}")
            assert (catalog.offer_price(selected) if selected.available else "⛔") in button["text"]
            assert ui.text_units(button["text"]) <= 24
            seen.append(selected.service)
        if page:
            assert f"c:category:{category}:{page - 1}" in callbacks(card)
        if (page + 1) * 8 < len(offers):
            assert f"c:category:{category}:{page + 1}" in callbacks(card)
    assert seen == [offer.service for offer in offers]


def test_catalog_has_two_column_sections_and_no_wholesale_entrypoints():
    text, keyboard = screens.catalog_card()
    section_rows = [row for row in keyboard.inline_keyboard
                    if str(row[0].callback_data).startswith("c:category:")]
    assert len(section_rows) == 3
    assert all(len(row) == 2 for row in section_rows)
    assert {button.callback_data for row in section_rows for button in row} == {
        f"c:category:{category}" for category in catalog.CATEGORIES
    }
    assert "опт" not in text.lower()
    assert all(button.callback_data != "c:wholesale" for row in keyboard.inline_keyboard for button in row)


@pytest.mark.parametrize("category", catalog.CATEGORIES)
def test_category_out_of_range_pages_return_valid_first_or_last_page(category):
    offers = screens.category_offers(category)
    assert screens.category_card(category, -10) == screens.category_card(category, 0)
    assert screens.category_card(category, 10000) == screens.category_card(category, (len(offers) - 1) // 8)


@pytest.mark.parametrize("selected", catalog.OFFERS.values(), ids=lambda selected: selected.service)
async def test_offer_back_button_returns_to_page_containing_the_offer(env, selected):
    await env.callback(CLIENT, f"c:service:{selected.service}")
    card = last(env, CLIENT)
    back = next(data for data in callbacks(card) if data.startswith("c:category:"))
    await env.callback(CLIENT, back)
    assert f"c:service:{selected.service}" in callbacks(last(env, CLIENT))


async def test_legacy_category_button_opens_first_page_and_preview_keeps_paging(env):
    await env.callback(CLIENT, "c:category:exchanges")
    first = last(env, CLIENT)
    assert "c:service:bybit" in callbacks(first)
    assert "c:service:paxful" not in callbacks(first)
    assert "c:category:exchanges:1" in callbacks(first)
    _, keyboard = screens.category_card("exchanges", 1)
    preview = screens.preview_markup(keyboard)
    assert all(str(button.callback_data).startswith("p:")
               for row in preview.inline_keyboard for button in row)
    assert "p:category:exchanges:0" in [button.callback_data
                                      for row in preview.inline_keyboard for button in row]


def test_legacy_only_customer_history_is_still_reachable_without_exposing_private_notes(store):
    store.remember_user(CLIENT, CLIENT, "Клиент", "customer")
    store.set_note(CLIENT, "Приватная заметка оператора", ADMIN)
    discussion, _ = store.create_ticket(CLIENT, kind="wholesale")
    store.set_status(discussion.id, discussion.version, "resolved", ADMIN)
    profile = store.profile(CLIENT)
    assert profile.total_tickets == 0
    text, keyboard = screens.profile_card(profile, None, "UTC", has_history=True)
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "c:orders:0" in data
    assert "c:wholesale" not in data
    assert "Приватная заметка" not in text


def test_help_keeps_rules_privacy_and_order_instructions_available():
    text, keyboard = screens.help_card()
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert {"c:guide:general", "c:rules", "c:privacy", "c:catalog", "c:home"} == set(data)
    assert data[0] == "c:catalog"
    assert ui.text_units(text) < 700


def test_help_prioritizes_existing_order_without_creating_a_second_one(store):
    store.remember_user(CLIENT, CLIENT, "Клиент", None)
    ticket, _ = store.create_ticket(CLIENT)
    _, keyboard = screens.help_card(ticket)
    assert keyboard.inline_keyboard[0][0].callback_data == "c:current"


def test_rules_intro_and_consent_controls_leave_full_rules_intact():
    for page in range(len(rules.PAGES)):
        text, keyboard = rules.card(page)
        data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        assert rules.PAGES[page] in text
        assert (f"c:agree:{rules.VERSION}" in data) == (page == len(rules.PAGES) - 1)
        assert ui.text_units(text) <= 4096
    text, keyboard = rules.card(0)
    assert f"прочитайте все {len(rules.PAGES)} страницы" in text
    assert keyboard.inline_keyboard[0][0].callback_data == f"c:rules:{rules.VERSION}:1"


async def test_paid_order_instruction_explains_verification_without_restarting_checkout(env):
    from .payment_helpers import legacy_ticket

    ticket = legacy_ticket(env.store, await order(env, service="bybit"))
    ticket = env.store.set_status(ticket.id, ticket.version, "in_progress", ADMIN)
    await env.callback(CLIENT, f"c:guide:{ticket.service_code}")
    card = last(env, CLIENT)
    assert "Проверку проходите самостоятельно" in card["text"]
    assert "в своём аккаунте" in card["text"]
    assert "оформите заказ" not in card["text"]
    assert "пришлите сюда чек" not in card["text"]
    assert callbacks(card) == ["c:current"]
    assert "оформите заказ" in screens.guide("general")


@pytest.mark.parametrize("service", [o.service for o in catalog.OFFERS.values() if o.available])
async def test_every_active_service_creates_correctly_priced_order_and_notifies_operator(env, service):
    await env.callback(CLIENT, f"c:service:{service}")
    assert f"c:order:{service}:standard" in callbacks(last(env, CLIENT))
    ticket = await order(env, service=service)
    selected = catalog.offer(service, "standard")
    assert (ticket.service_code, ticket.price_usd) == (service, selected.price_usd)
    assert "Оператор уточнит вашу страну и условия" in last(env, CLIENT)["text"]
    assert selected.title in last(env, ADMIN)["text"]
    await env.callback(CLIENT, f"c:order:{service}:standard")
    assert env.store.profile(CLIENT).total_tickets == 1
    await env.callback(CLIENT, f"c:guide:{service}")
    assert selected.title in last(env, CLIENT)["text"]


async def test_closed_and_retired_services_cannot_create_orders(env):
    for service in ("localbitcoins", "chatgpt", "gemini"):
        await env.callback(CLIENT, f"c:order:{service}:standard")
        assert env.store.for_user(CLIENT) is None
        assert not any(data.startswith(f"c:order:{service}:") for data in callbacks(last(env, CLIENT)))
    assert not sent(env, ADMIN)


@pytest.mark.parametrize("plan,price", [("armenia", "35.00"), ("europe", "50.00")])
async def test_old_geo_order_buttons_require_fresh_price_acceptance_and_preserve_history(env, plan, price):
    await env.callback(CLIENT, f"c:order:claude:{plan}")
    assert env.store.for_user(CLIENT) is None
    assert any("$45" in b["text"] for row in last(env, CLIENT)["reply_markup"]["inline_keyboard"] for b in row)
    assert "c:order:claude:standard" in callbacks(last(env, CLIENT))
    old, _ = env.store.create_ticket(CLIENT, "claude", plan, price)
    await env.callback(CLIENT, f"c:view:{old.id}")
    assert catalog.dollars(price) in last(env, CLIENT)["text"]
    assert "Армения" not in last(env, CLIENT)["text"] and "Европа" not in last(env, CLIENT)["text"]
    assert env.store.ticket(old.id).price_usd == price


async def read_and_accept(env, uid=CLIENT):
    await env.message(uid, "/start")
    for page in range(1, len(rules.PAGES)):
        await env.callback(uid, f"c:rules:{rules.VERSION}:{page}")
    await env.callback(uid, f"c:agree:{rules.VERSION}")


@pytest.mark.parametrize("entry", ["/start", "/services", "/status", "/profile", "/help", "/unknown",
                                       "text", "photo", "edited", "c:order:bybit:standard",
                                       "c:send_draft:1:fake", "c:home", "a:home"])
async def test_rules_block_all_customer_entrypoints_without_forwarding_content(env, entry):
    env.require_terms = True
    if entry.startswith(("c:", "a:")):
        await env.callback(CLIENT, entry)
    elif entry == "photo":
        await env.message(CLIENT, photo=True)
    elif entry == "edited":
        await env.message(CLIENT, "Личные данные", edited=True)
    else:
        await env.message(CLIENT, entry)
    card = last(env, CLIENT)
    assert "Правила оказания услуг" in card["text"]
    assert not any(data.startswith("c:agree:") for data in callbacks(card))
    assert env.store.for_user(CLIENT) is None
    assert not sent(env, ADMIN)
    assert env.store.terms_state(CLIENT)["accepted_at"] is None


async def test_rules_require_all_pages_then_explicit_agreement_and_snapshot_order(env):
    env.require_terms = True
    await env.callback(CLIENT, f"c:agree:{rules.VERSION}")
    assert not env.store.terms_state(CLIENT)["accepted_at"]
    await env.callback(CLIENT, f"c:rules:{rules.VERSION}:{len(rules.PAGES) - 1}")
    assert "1/" in last(env, CLIENT)["text"]
    for page in range(1, len(rules.PAGES)):
        await env.callback(CLIENT, f"c:rules:{rules.VERSION}:{page}")
        assert rules.PAGES[page] in last(env, CLIENT)["text"]
    agree = f"c:agree:{rules.VERSION}"
    assert callbacks(last(env, CLIENT))[-1] == agree
    assert not env.store.terms_state(CLIENT)["accepted_at"]
    await env.callback(CLIENT, agree)
    state = env.store.terms_state(CLIENT)
    assert state["accepted_version"] == rules.VERSION and state["accepted_at"]
    assert "c:catalog" in callbacks(last(env, CLIENT))
    accepted_at = state["accepted_at"]
    await env.callback(CLIENT, agree)
    assert env.store.terms_state(CLIENT)["accepted_at"] == accepted_at
    ticket = await order(env, service="bybit")
    snapshot = env.store.db.execute("SELECT * FROM ticket_terms WHERE ticket_id=?", (ticket.id,)).fetchone()
    assert snapshot["version"] == rules.VERSION and snapshot["accepted_at"] == accepted_at
    await env.callback(CLIENT, "c:rules")
    assert "Правила оказания услуг" in last(env, CLIENT)["text"]
    assert "c:home" in callbacks(last(env, CLIENT))


async def test_consent_survives_restart_and_new_rules_need_new_agreement(env, monkeypatch, tmp_path):
    env.require_terms = True
    await read_and_accept(env)
    path = tmp_path / "desk.sqlite3"
    reopened = Store(path)
    assert reopened.terms_state(CLIENT)["accepted_version"] == rules.VERSION
    reopened.close()
    old = env.store.terms_state(CLIENT)["accepted_at"]
    monkeypatch.setattr(rules, "VERSION", "newrulesversion")
    await env.callback(CLIENT, "c:order:alipay:standard")
    assert "Правила оказания услуг" in last(env, CLIENT)["text"]
    await env.callback(CLIENT, "c:agree:staleversion")
    assert env.store.terms_state(CLIENT)["accepted_at"] == old
    assert env.store.for_user(CLIENT) is None
    await read_and_accept(env)
    assert env.store.terms_state(CLIENT)["accepted_version"] == "newrulesversion"


async def test_operator_admin_access_and_client_onboarding_modes(env):
    env.require_terms = True
    await env.message(ADMIN, "/admin")
    assert "Кабинет оператора" in last(env, ADMIN)["text"]
    await env.message(ADMIN, "/client")
    assert "Правила оказания услуг" in last(env, ADMIN)["text"]
    assert env.store.operator_mode(ADMIN) == "client"
    await env.message(ADMIN, "/admin")
    assert env.store.operator_mode(ADMIN) == "admin"
    await env.callback(ADMIN, "a:mode:client")
    await read_and_accept(env, ADMIN)
    assert "c:catalog" in callbacks(last(env, ADMIN))


def test_full_rules_are_preserved_without_omitted_paragraphs():
    assert len(rules.PAGES) > 1
    assert "\n\n".join(rules.PAGES) == "\n\n".join(rules._render(p) for p in rules.TEXT.strip().split("\n\n"))
    assert "11. Обращения и разрешение разногласий" in "".join(rules.PAGES)


@pytest.mark.parametrize("status", ["new", "resolved"])
async def test_historical_alipay_orders_keep_original_prices_and_messages(env, status):
    from .payment_helpers import legacy_ticket

    env.store.remember_user(CLIENT, CLIENT, "Клиент", None)
    old, _ = env.store.create_ticket(CLIENT, "alipay", "standard", "27.00")
    env.store.add_message(old.id, "user", "История прежней заявки", CLIENT, CLIENT, 901)
    old = env.store.ticket(old.id)
    if status == "resolved":
        legacy_ticket(env.store, old)
        old = env.store.set_status(old.id, old.version, status, ADMIN)
    for uid, prefix in ((CLIENT, "c"), (ADMIN, "a")):
        await env.callback(uid, f"{prefix}:view:{old.id}")
        assert "Alipay" in last(env, uid)["text"] and "$27" in last(env, uid)["text"]
    await env.callback(CLIENT, f"c:history:{old.id}:0")
    assert "История прежней заявки" in last(env, CLIENT)["text"]
    await env.callback(CLIENT, "c:order:alipay:standard")
    assert env.store.ticket(old.id).price_usd == "27.00"
    current = env.store.for_user(CLIENT)
    assert current.price_usd == ("50.00" if status == "resolved" else "27.00")


async def test_failed_rules_delivery_does_not_allow_skipping_to_acceptance(env):
    from telegram.error import Forbidden

    env.require_terms = True
    env.request.fail_chat, env.request.fail_error = CLIENT, Forbidden("Blocked")
    await env.message(CLIENT, "/start")
    assert env.store.terms_state(CLIENT) is None
    env.request.fail_chat = None
    await env.callback(CLIENT, f"c:rules:{rules.VERSION}:1")
    assert rules.PAGES[0] in last(env, CLIENT)["text"]
    assert env.store.terms_state(CLIENT)["viewed_page"] == 0


async def test_source_is_retained_while_customer_reads_rules(env):
    env.require_terms = True
    await env.message(CLIENT, "/start src_partner")
    await read_and_accept(env)
    ticket = await order(env, service="alipay")
    assert env.store.db.execute(
        "SELECT source_code FROM ticket_acquisition WHERE ticket_id=?", (ticket.id,),
    ).fetchone()[0] == "src_partner"
