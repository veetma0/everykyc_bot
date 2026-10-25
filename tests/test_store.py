import logging
import sqlite3

import pytest

from verifydesk.__main__ import PrivateFormatter, SingleInstance
from verifydesk.store import StaleTicket, Store
from verifydesk import ui
from .payment_helpers import legacy_ticket


def user(store, uid=101):
    store.remember_user(uid, uid, "<Имя>", "username")
    return store.create_ticket(uid)[0]


def test_state_and_reply_targets_survive_restart(tmp_path):
    path = tmp_path / "desk.sqlite3"
    first = Store(path)
    ticket = user(first)
    first.map_reply(42, 100, ticket.id)
    first.add_message(ticket.id, "operator", "Ответ", 42, 42, 101)
    first.close()
    second = Store(path)
    assert second.for_user(101).id == ticket.id
    assert second.reply_ticket(42, 100).id == ticket.id
    assert second.recover_pending() == 1
    assert (
        second.db.execute("SELECT delivery FROM messages WHERE role='operator'").fetchone()[0] == "uncertain"
    )
    second.close()


def test_closed_ticket_cannot_accept_messages_or_be_reopened(store):
    ticket = user(store)
    legacy_ticket(store, ticket)
    closed = store.set_status(ticket.id, ticket.version, "resolved", 42)
    with pytest.raises(StaleTicket):
        store.add_message(ticket.id, "user", "Поздний текст", 101, 101, 5)
    with pytest.raises(StaleTicket):
        store.set_status(ticket.id, closed.version, "in_progress", 42)


def test_database_enforces_single_active_ticket(store):
    user(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute(
            "INSERT INTO tickets(user_id,status,created_at,updated_at,consent_at) VALUES(101,'new',0,0,0)"
        )
    store.db.rollback()


def test_read_marks_do_not_hide_future_messages(store):
    ticket = user(store)
    store.add_message(ticket.id, "user", "Первое", 101, 101, 1)
    store.mark_read(ticket.id)
    assert store.ticket(ticket.id).unread == 0
    store.add_message(ticket.id, "user", "Второе", 101, 101, 2)
    assert store.ticket(ticket.id).unread == 1


def test_database_permissions(store, tmp_path):
    assert (tmp_path / "desk.sqlite3").stat().st_mode & 0o777 == 0o600


def test_single_instance_lock_can_be_released(tmp_path):
    first = SingleInstance(tmp_path)
    with pytest.raises(RuntimeError):
        SingleInstance(tmp_path)
    first.close()
    second = SingleInstance(tmp_path)
    second.close()


def test_log_formatter_redacts_token_even_in_exception():
    secret = "never-print-this-token"
    record = logging.LogRecord("test", logging.ERROR, "", 0, f"URL with {secret}", (), None)
    assert secret not in PrivateFormatter(secret).format(record)


def test_native_buttons_have_safe_lengths_and_no_private_contact_link(store):
    ticket = user(store)
    cards = [
        ui.home("Помощь", ticket),
        ui.prepare(),
        ui.customer_ticket(ticket, "Asia/Amman"),
        ui.admin_home(store.counts()),
        ui.admin_ticket(ticket),
        ui.status_menu(ticket),
    ]
    for text, keyboard in cards:
        assert len(text) <= 4096
        for row in keyboard.inline_keyboard:
            for button in row:
                assert button.url is None
                assert len(button.callback_data.encode()) <= 64
    assert all(button.style is None for _, keyboard in cards for row in keyboard.inline_keyboard for button in row)
