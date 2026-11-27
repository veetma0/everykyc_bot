import re
from html import escape

import pytest

from verifydesk import rules, ui
from verifydesk.language import FULFILLMENT, render
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .test_journey_audit import press
from .test_upgrade import buttons, callbacks, last, order, sent


def test_legacy_accounts_keep_russian_and_order_consent_after_switching_language(tmp_path):
    path = tmp_path / "languages.sqlite3"
    store = Store(path)
    store.remember_user(101, 101, "Existing customer", None)
    last_page = len(rules.PAGES) - 1
    store.mark_terms_page(101, rules.VERSION, last_page)
    assert store.accept_terms(101, rules.VERSION, last_page)
    ticket, _ = store.create_ticket(101, "bybit", "standard", "50.00")
    accepted_at = store.terms_state(101)["accepted_at"]
    with store.db:
        store.db.execute("ALTER TABLE users DROP COLUMN language")
    store.close()

    migrated = Store(path)
    assert migrated.language(101) == "ru"
    migrated.set_language(101, "en")
    migrated.remember_user(101, 101, "Existing customer", None, language="ru")
    migrated.close()

    reopened = Store(path)
    try:
        assert reopened.language(101) == "en"
        assert reopened.terms_state(101)["accepted_at"] == accepted_at
        assert reopened.terms_state(101)["accepted_version"] == rules.VERSION
        snapshot = reopened.db.execute("SELECT * FROM ticket_terms WHERE ticket_id=?", (ticket.id,)).fetchone()
        assert (snapshot["version"], snapshot["accepted_at"]) == (rules.VERSION, accepted_at)
        assert reopened.ticket(ticket.id) == ticket
    finally:
        reopened.close()


def test_first_language_is_saved_and_real_switch_restarts_an_unfinished_reader(store):
    assert store.language(102) == "ru"
    store.remember_user(102, 102, "Alice", None, language="en")
    store.remember_user(102, 102, "Alice", None)
    assert store.language(102) == "en"
    store.mark_terms_page(102, rules.VERSION, len(rules.PAGES_EN) - 1)
    store.set_language(102, "en")
    assert store.terms_state(102)["viewed_page"] == len(rules.PAGES_EN) - 1
    store.set_language(102, "ru")
    assert store.language(102) == "ru" and store.terms_state(102)["viewed_page"] == -1
    assert not store.accept_terms(102, rules.VERSION, len(rules.PAGES) - 1)
    with pytest.raises(ValueError):
        store.set_language(102, "unavailable")
    assert store.language(102) == "ru"


def test_english_rules_include_every_section_and_the_original_guarantees():
    source = rules.TEXT_EN
    assert re.findall(r"^### (\d+)\.", source, re.M) == re.findall(r"^### (\d+)\.", rules.TEXT, re.M)
    assert [len(block.splitlines()) for block in source.strip().split("\n\n")] == [
        len(block.splitlines()) for block in rules.TEXT.strip().split("\n\n")
    ]
    assert source.count("48 hours") == 2
    assert "14 calendar days" in source and "holding the funds" in source
    assert "silence does not constitute completion" in source.lower()
    assert "compensation is due by law" in source
    assert "14 days" in source and "support contacts provided before payment" in source
    assert not re.search(r"[а-яё]", source, re.I)


@pytest.mark.parametrize(("language", "agree", "home"), [("ru", "Принимаю правила", "Главная"),
                                                        ("en", "I accept the rules", "Home")])
def test_full_and_paginated_rules_share_terms_and_have_readable_actions(language, agree, home):
    pages = rules.pages(language)
    source = rules.TEXT_EN if language == "en" else rules.TEXT
    rendered = "\n\n".join(rules._render(paragraph) for paragraph in source.strip().split("\n\n"))
    complete, keyboard = rules.full_card(language=language)
    notice = render(FULFILLMENT, language)
    assert complete == f"{notice}\n\n{rendered}"
    assert "\n\n".join(pages) == rendered
    [[button]] = keyboard.inline_keyboard
    assert (button.text, button.callback_data) == (agree, f"c:agree_full:{rules.VERSION}")
    _, keyboard = rules.full_card(language=language, accepted=True)
    [[button]] = keyboard.inline_keyboard
    assert (button.text, button.callback_data) == (home, "c:home")
    for index, page in enumerate(pages):
        text, keyboard = rules.card(index, language=language)
        assert page in text and ui.text_units(text) <= 4096
        assert (notice in text) == (index == 0)
        actions = {button.callback_data: button.text for row in keyboard.inline_keyboard for button in row}
        if index == len(pages) - 1:
            assert actions[f"c:agree:{rules.VERSION}"] == agree
        else:
            assert f"c:agree:{rules.VERSION}" not in actions
            assert f"c:rules:{rules.VERSION}:{index + 1}" in actions
        if language == "en":
            assert not re.search(r"[а-яё]", text + " ".join(actions.values()), re.I)


async def change_language_from_screen(env, uid, language):
    destination = f"l:set:{language}"
    options = callbacks(last(env, uid))
    if destination not in options:
        menu = next(action for action in options if action.startswith("l:") and not action.startswith("l:set:"))
        await press(env, uid, menu)
    await press(env, uid, destination)


async def test_language_switch_is_available_on_rules_and_persists_after_consent(env):
    env.require_terms = True
    await env.message(CLIENT, "/start", language_code="ru")
    assert rules.PAGES[0] in last(env, CLIENT)["text"]
    await change_language_from_screen(env, CLIENT, "en")
    assert rules.PAGES_EN[0] in last(env, CLIENT)["text"]
    assert env.store.terms_state(CLIENT)["accepted_at"] is None
    await press(env, CLIENT, f"c:agree_full:{rules.VERSION}")
    accepted_at = env.store.terms_state(CLIENT)["accepted_at"]
    assert accepted_at and "Service catalog" in last(env, CLIENT)["text"]
    await press(env, CLIENT, "c:home")
    await change_language_from_screen(env, CLIENT, "ru")
    assert "Каталог" in last(env, CLIENT)["text"] or any(
        "Каталог" in button["text"] for button in buttons(last(env, CLIENT))
    )
    await env.message(CLIENT, "/language")
    await press(env, CLIENT, "l:set:en")
    await env.message(CLIENT, "/start", language_code="ru")
    assert env.store.language(CLIENT) == "en"
    assert env.store.terms_state(CLIENT)["accepted_at"] == accepted_at
    assert "c:catalog" in callbacks(last(env, CLIENT))
    commands = next(params["commands"] for method, params in reversed(env.request.calls)
                    if method == "setMyCommands" and params.get("scope", {}).get("chat_id") == CLIENT)
    assert any(command["command"] == "language" for command in commands)
    assert not any(re.search(r"[а-яё]", command["description"], re.I) for command in commands)


async def test_english_customer_russian_operator_payment_and_verbatim_history(env):
    env.require_terms = True
    await env.message(CLIENT, "/start", language_code="en-GB")
    assert env.store.language(CLIENT) == "en"
    assert rules.PAGES_EN[0] in last(env, CLIENT)["text"]
    await press(env, CLIENT, f"c:agree_full:{rules.VERSION}")
    for route in ("c:category:exchanges", "c:service:bybit", "c:order:bybit:standard"):
        await press(env, CLIENT, route)
        assert not re.search(r"[а-яё]", last(env, CLIENT)["text"], re.I)
    ticket = env.store.for_user(CLIENT)
    assert ticket.price_usd == "50.00"
    assert "Заказ" in last(env, ADMIN)["text"]

    # An exact translation key and HTML-looking text must remain part of the quoted message.
    customer_text = "Каталог услуг & <b>Помощь</b>"
    operator_text = "Ожидает оплаты & <i>Главная</i>"
    await env.message(CLIENT, customer_text)
    assert escape(customer_text) in last(env, ADMIN)["text"]
    await env.message(ADMIN, "/admin", language_code="ru")
    await press(env, ADMIN, "a:next")
    await press(env, ADMIN, f"a:request_payment:{ticket.id}:{env.store.ticket(ticket.id).version}")
    assert "USDT" in last(env, CLIENT)["text"] and "реквизит" not in last(env, CLIENT)["text"]
    await press(env, CLIENT, f"c:pay:{ticket.id}")
    await press(env, CLIENT, f"c:network:{ticket.id}:usdt_tron")
    assert "TRC20" in last(env, CLIENT)["text"] and "оператор" not in last(env, CLIENT)["text"].lower()
    await press(env, CLIENT, f"c:view:{ticket.id}")
    await env.callback(ADMIN, f"a:view:{ticket.id}")
    assert "TRC20" in last(env, ADMIN)["text"] and "Заказ" in last(env, ADMIN)["text"]
    await press(env, ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, operator_text)
    notice = last(env, CLIENT)["text"]
    assert "Operator" in notice and escape(operator_text) in notice
    await env.callback(CLIENT, f"c:history:{ticket.id}:0")
    history = last(env, CLIENT)["text"]
    assert escape(operator_text) in history and escape(customer_text) in history
    assert not re.search(r"[а-яё]", history.replace(escape(operator_text), "").replace(escape(customer_text), ""), re.I)

    await env.proof(CLIENT, photo=True)
    review = env.store.ticket(ticket.id)
    assert review.payment_stage == "review" and "оплат" in last(env, ADMIN)["text"].lower()
    await press(env, ADMIN, f"a:confirm_payment:{ticket.id}:{review.version}")
    assert env.store.ticket(ticket.id).payment_stage == "confirmed"
    assert "specialist" in last(env, CLIENT)["text"].lower()
    assert env.store.language(ADMIN) == "ru" and env.store.language(CLIENT) == "en"


async def test_classic_language_switch_before_acceptance_restarts_reading(env):
    env.require_terms = True
    await env.message(OTHER, "/classic", language_code="en")
    assert rules.PAGES_EN[0] in last(env, OTHER)["text"]
    await press(env, OTHER, f"c:rules:{rules.VERSION}:1")
    await env.message(OTHER, "/language")
    await press(env, OTHER, "l:set:ru")
    assert rules.PAGES[0] in last(env, OTHER)["text"]
    assert env.store.terms_state(OTHER)["viewed_page"] == 0
    await env.callback(OTHER, f"c:agree:{rules.VERSION}")
    assert env.store.terms_state(OTHER)["accepted_at"] is None
    for page in range(1, len(rules.PAGES)):
        await press(env, OTHER, f"c:rules:{rules.VERSION}:{page}")
    await press(env, OTHER, f"c:agree:{rules.VERSION}")
    assert env.store.terms_state(OTHER)["accepted_version"] == rules.VERSION


async def test_english_operator_receives_russian_customers_message_verbatim(env):
    env.require_terms = True
    await env.message(ADMIN, "/language en")
    assert env.store.language(ADMIN) == "en"
    assert "a:next" in callbacks(last(env, ADMIN))
    assert not any("Кабинет" in b["text"] for b in buttons(last(env, ADMIN)))
    await env.message(CLIENT, "/start", language_code="ru")
    await press(env, CLIENT, f"c:agree_full:{rules.VERSION}")
    for route in ("c:category:exchanges", "c:service:bybit", "c:order:bybit:standard"):
        await press(env, CLIENT, route)
    ticket = env.store.for_user(CLIENT)
    customer_text = "История заказов & <Каталог услуг>"
    await env.message(CLIENT, customer_text)
    operator_notice = last(env, ADMIN)["text"]
    assert escape(customer_text) in operator_notice
    assert "Order" in operator_notice and "Клиент 101" in operator_notice
    assert "Оператор" in last(env, CLIENT)["text"]
    await env.callback(ADMIN, f"a:history:{ticket.id}:0")
    history = last(env, ADMIN)["text"]
    assert escape(customer_text) in history
    assert not re.search(r"[а-яё]", history.replace(escape(customer_text), ""), re.I)
    assert env.store.language(CLIENT) == "ru"


async def test_leaving_operator_reply_for_language_menu_releases_its_recipient(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    assert env.store.focused_ticket(ADMIN).id == ticket.id and env.store.claim_owner(ticket.id) == ADMIN
    env.store.save_draft(ADMIN, ticket.id, "operator", "Previous draft", ADMIN, 2745)
    before = len(sent(env, CLIENT))
    await env.message(ADMIN, "/language")
    assert env.store.focused_ticket(ADMIN) is None
    assert env.store.draft(ADMIN) is None and env.store.claim_owner(ticket.id) is None
    await press(env, ADMIN, "l:set:en")
    assert "a:next" in callbacks(last(env, ADMIN))
    await env.message(ADMIN, "This has no recipient")
    assert len(sent(env, CLIENT)) == before
    assert not env.store.db.execute("SELECT 1 FROM messages WHERE ticket_id=? AND role='operator'",
                                    (ticket.id,)).fetchone()
