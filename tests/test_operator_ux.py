"""Operator controls stay reachable and actions remain legible on narrow screens."""

from dataclasses import replace
from html import escape

import pytest

from verifydesk import ui

from .conftest import ADMIN, CLIENT
from .test_upgrade import callbacks, last, order


@pytest.fixture
def ticket(store):
    store.remember_user(CLIENT, CLIENT, "Клиент", "customer")
    result, _ = store.create_ticket(CLIENT, "bybit", "standard", "50.00")
    return result


def actions(keyboard):
    return {button.callback_data: button.text for row in keyboard.inline_keyboard for button in row}


@pytest.mark.parametrize("status,stage", [
    ("new", "not_requested"), ("new", "awaiting_payment"), ("new", "review"),
    ("in_progress", "confirmed"), ("waiting_user", "confirmed"),
    ("resolved", "confirmed"), ("cancelled", "not_requested"),
])
def test_every_operator_card_has_history_details_and_exit(ticket, status, stage):
    current = replace(ticket, status=status, payment_stage=stage)
    _, keyboard = ui.admin_ticket(current)
    data = actions(keyboard)
    assert {f"a:history:{ticket.id}:0", f"a:details:{ticket.id}", "a:home"} <= data.keys()
    assert [button.callback_data for button in keyboard.inline_keyboard[-1]] == [
        f"a:next:{ticket.id}", "a:home",
    ]
    assert sum(button.style == "primary" for row in keyboard.inline_keyboard for button in row) <= 1
    assert all(button.style is None for row in keyboard.inline_keyboard[-2:] for button in row)


def test_payment_decisions_have_separate_full_width_rows(ticket):
    current = replace(ticket, payment_stage="review")
    _, keyboard = ui.admin_ticket(current, proof_ready=True)
    decision_rows = [row for row in keyboard.inline_keyboard
                     if any(str(button.callback_data).startswith(("a:confirm_payment:", "a:reject_payment:"))
                            for button in row)]
    assert len(decision_rows) == 2
    assert all(len(row) == 1 for row in decision_rows)


@pytest.mark.parametrize("stage", ["not_requested", "awaiting_payment", "review", "confirmed", "legacy"])
@pytest.mark.parametrize("state", ["delivered", "uncertain", "failed"])
def test_every_reply_receipt_can_return_to_order_or_exit(ticket, stage, state):
    current = replace(ticket, payment_stage=stage)
    _, keyboard = ui.reply_receipt(current, state)
    assert [button.callback_data for button in keyboard.inline_keyboard[-1]] == [
        f"a:view:{ticket.id}", "a:home",
    ]
    data = actions(keyboard)
    if state == "uncertain":
        assert f"a:history:{ticket.id}:0" in data
        assert f"a:reply:{ticket.id}" not in data
    if stage not in {"confirmed", "legacy"}:
        assert not any(callback.endswith(":resolved") for callback in data)


def test_status_choices_describe_actions_and_keep_actual_status_in_text(ticket):
    current = replace(ticket, status="in_progress", payment_stage="confirmed")
    text, keyboard = ui.status_menu(current)
    data = actions(keyboard)
    assert "Сейчас: 🛠 В работе" in text
    assert data[f"a:set:{ticket.id}:{ticket.version}:resolved"] == "Завершить заказ"
    assert data[f"a:set:{ticket.id}:{ticket.version}:cancelled"] == "Отменить заказ"
    assert f"a:view:{ticket.id}" in data and "a:home" in data


def test_operator_two_column_labels_stay_short_in_all_card_states(ticket):
    cards = [ui.admin_more(), ui.admin_details(ticket), ui.status_menu(ticket)]
    for kind in ("order", "wholesale"):
        for stage in ("not_requested", "awaiting_payment", "review", "confirmed", "legacy"):
            current = replace(ticket, kind=kind, payment_stage=stage)
            cards += [ui.admin_ticket(current, proof_ready=True), ui.reply_receipt(current, "delivered")]
    for _, keyboard in cards:
        for row in keyboard.inline_keyboard:
            assert len(row) <= 2
            if len(row) == 2:
                assert all(ui.text_units(button.text) <= 18 for button in row)


def test_short_operator_excerpt_is_kept_and_markup_is_escaped(ticket):
    snippet = "Условие <проверки> & вопрос 🌕"
    text, _ = ui.admin_ticket(ticket, snippet)
    assert escape(snippet) in text
    assert "Полностью — в переписке" not in text


async def test_long_message_keeps_operator_actions_nearby_and_full_text_reachable(env):
    current = await order(env)
    body = "<Вопрос> & уточнение 🌕 " * 80
    await env.message(CLIENT, body)
    card = last(env, ADMIN)
    assert "Полностью — в переписке." in card["text"]
    assert escape(body) not in card["text"]
    assert escape(ui.clip_text(body, 420)) + "…" in card["text"]
    assert f"a:history:{current.id}:0" in callbacks(card)
    await env.callback(ADMIN, f"a:history:{current.id}:0")
    full = next(callback for callback in callbacks(last(env, ADMIN)) if callback.startswith("a:message:"))
    await env.callback(ADMIN, full)
    assert escape(body) in last(env, ADMIN)["text"]
