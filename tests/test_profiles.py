from decimal import Decimal
import sqlite3

import pytest

from verifydesk.store import StaleTicket, Store
from .payment_helpers import legacy_ticket


def legacy_database(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL,
            display_name TEXT NOT NULL, username TEXT
        );
        CREATE TABLE tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            consent_at REAL NOT NULL, last_read_id INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO users VALUES(101,101,'Существующий клиент','existing');
        INSERT INTO users VALUES(102,102,'Без заявки',NULL);
        INSERT INTO tickets(user_id,status,created_at,updated_at,consent_at)
            VALUES(101,'new',100,200,100);
    """)
    connection.commit()
    connection.close()


def remember(store, uid=101, name="Клиент"):
    store.remember_user(uid, uid, name, f"client{uid}")


def test_legacy_database_migrates_without_changing_existing_ticket(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy_database(path)
    store = Store(path)
    ticket = store.ticket(1)
    assert ticket.id == 1
    assert ticket.display_name == "Существующий клиент"
    assert (ticket.service_code, ticket.plan_code, ticket.price_usd, ticket.demo_network) == (
        "claude",
        "standard",
        None,
        None,
    )
    profile = store.profile(101)
    assert profile.first_seen_at == 100
    assert profile.last_seen_at == 200
    assert profile.total_tickets == profile.active_tickets == 1
    assert profile.latest_ticket_id == 1
    assert store.profile(102).first_seen_at > 0
    assert store.profile(102).total_tickets == 0
    store.close()


def test_migration_is_idempotent_and_preserves_notes_and_catalog_snapshot(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy_database(path)
    first = Store(path)
    first.set_note(101, "Заметка оператора", 42)
    first.remember_user(101, 101, "Новое имя", None)
    first.close()
    for _ in range(2):
        store = Store(path)
        assert store.profile(101).operator_note == "Заметка оператора"
        assert store.profile(101).first_seen_at == 100
        assert store.profile(101).display_name == "Новое имя"
        assert store.ticket(1).service_code == "claude"
        assert (
            len(
                [
                    row
                    for row in store.db.execute("PRAGMA table_info(users)")
                    if row["name"] == "first_seen_at"
                ]
            )
            == 1
        )
        store.close()


def test_remember_user_preserves_first_seen_and_note(store, monkeypatch):
    monkeypatch.setattr("verifydesk.store.time.time", lambda: 100)
    remember(store)
    store.set_note(101, "  Важный контекст  ", 42)
    monkeypatch.setattr("verifydesk.store.time.time", lambda: 200)
    store.remember_user(101, 555, "Обновлённое имя", None)
    profile = store.profile(101)
    assert profile.first_seen_at == 100
    assert profile.last_seen_at == 200
    assert profile.operator_note == "Важный контекст"
    assert (profile.chat_id, profile.display_name, profile.username) == (555, "Обновлённое имя", None)
    assert store.db.execute("SELECT note_updated_by,note_updated_at FROM users WHERE id=101").fetchone()[
        :
    ] == (42, 100)


def test_profile_totals_are_for_this_user_and_actual_statuses(store):
    remember(store)
    remember(store, 102)
    first, _ = store.create_ticket(101, "claude", "armenia", "35")
    legacy_ticket(store, first)
    store.set_status(first.id, first.version, "resolved", 42)
    second, _ = store.create_ticket(101, "alipay", "standard")
    store.set_status(second.id, second.version, "cancelled", 101)
    third, _ = store.create_ticket(101, "claude", "europe", Decimal("50.00"))
    store.create_ticket(102)
    profile = store.profile(101)
    assert (
        profile.total_tickets,
        profile.active_tickets,
        profile.resolved_tickets,
        profile.cancelled_tickets,
    ) == (3, 1, 1, 1)
    assert profile.latest_ticket_id == third.id
    assert store.profile(102).total_tickets == 1
    assert store.profile(999) is None


def test_active_ticket_is_not_retargeted_or_repriced_by_another_service(store):
    remember(store)
    first, created = store.create_ticket(101, "claude", "armenia", "35")
    second, second_created = store.create_ticket(101, "alipay", "standard", "90")
    assert created and not second_created
    assert second.id == first.id
    assert (second.service_code, second.plan_code, second.price_usd) == ("claude", "armenia", "35.00")


@pytest.mark.parametrize("amount,expected", [("35", "35.00"), ("50.00", "50.00"), (Decimal("0.01"), "0.01")])
def test_price_is_canonical_decimal_text(store, amount, expected):
    remember(store)
    ticket, _ = store.create_ticket(101, price_usd=amount)
    assert ticket.price_usd == expected
    row = store.db.execute(
        "SELECT price_usd,typeof(price_usd) FROM tickets WHERE id=?", (ticket.id,)
    ).fetchone()
    assert row[:] == (expected, "text")


@pytest.mark.parametrize("amount", [35.0, True, "0", "-1", "NaN", "Infinity", "35.001", "wrong"])
def test_invalid_price_never_creates_ticket(store, amount):
    remember(store)
    with pytest.raises(ValueError):
        store.create_ticket(101, price_usd=amount)
    assert store.for_user(101) is None


@pytest.mark.parametrize(
    "service,plan",
    [("Claude", "standard"), ("claude", "EUROPE"), ("bad:code", "ok"), ("a" * 33, "ok"), ("ok", "")],
)
def test_invalid_catalog_codes_cannot_reach_storage(store, service, plan):
    remember(store)
    with pytest.raises(ValueError):
        store.create_ticket(101, service, plan)


def test_clients_page_is_paginated_and_excludes_operators(store, monkeypatch):
    for uid in range(100, 110):
        monkeypatch.setattr("verifydesk.store.time.time", lambda value=uid: value)
        remember(store, uid)
    first, total = store.clients_page(0, limit=3, exclude_ids=(109, 108))
    second, same_total = store.clients_page(3, limit=3, exclude_ids=(109, 108))
    assert total == same_total == 8
    assert [profile.id for profile in first] == [107, 106, 105]
    assert [profile.id for profile in second] == [104, 103, 102]
    assert store.clients_page(100, exclude_ids=(109,))[0] == []


def test_note_reply_targets_are_isolated_from_client_message_targets(store):
    remember(store)
    remember(store, 102)
    ticket, _ = store.create_ticket(101)
    store.map_reply(42, 500, ticket.id)
    assert store.reply_ticket(42, 500).id == ticket.id
    store.map_note_reply(42, 500, 102)
    assert store.reply_ticket(42, 500) is None
    assert store.note_reply_user(42, 500) == 102
    assert store.note_reply_user(43, 500) is None
    store.map_reply(42, 500, ticket.id)
    assert store.note_reply_user(42, 500) is None
    assert store.reply_ticket(42, 500).id == ticket.id
    store.unmap_reply(42, 500)
    assert store.reply_ticket(42, 500) is None
    assert store.note_reply_user(42, 500) is None


def test_private_note_does_not_become_message_and_can_be_cleared(store):
    remember(store)
    ticket, _ = store.create_ticket(101)
    before = store.messages(ticket.id)
    store.set_note(101, "Только для оператора", 42)
    assert store.messages(ticket.id) == before
    assert not hasattr(store.ticket(ticket.id), "operator_note")
    assert store.set_note(101, "", 42).operator_note == ""
    with pytest.raises(ValueError):
        store.set_note(101, "a" * 1201, 42)
    with pytest.raises(ValueError):
        store.set_note(999, "Не создаёт пользователя", 42)


def test_mock_network_changes_no_price_service_or_payment_status(store):
    remember(store)
    ticket, _ = store.create_ticket(101, "claude", "armenia", "35")
    selected = store.set_demo_network(ticket.id, "tron")
    assert selected.demo_network == "tron"
    assert (
        selected.service_code,
        selected.plan_code,
        selected.price_usd,
        selected.status,
        selected.version,
    ) == (
        "claude",
        "armenia",
        "35.00",
        "new",
        ticket.version,
    )
    assert not hasattr(selected, "paid")
    with pytest.raises(ValueError):
        store.set_demo_network(ticket.id, "TRC20")
    legacy_ticket(store, ticket)
    closed = store.set_status(ticket.id, ticket.version, "resolved", 42)
    with pytest.raises(StaleTicket):
        store.set_demo_network(closed.id, "ethereum")


def test_note_and_mock_network_survive_restart(tmp_path):
    path = tmp_path / "desk.sqlite3"
    store = Store(path)
    remember(store)
    ticket, _ = store.create_ticket(101, "claude", "europe", "50")
    store.set_note(101, "Контекст", 42)
    store.map_note_reply(42, 888, 101)
    store.set_demo_network(ticket.id, "ton")
    store.close()
    reopened = Store(path)
    assert reopened.ticket(ticket.id).demo_network == "ton"
    assert reopened.ticket(ticket.id).price_usd == "50.00"
    assert reopened.profile(101).operator_note == "Контекст"
    assert reopened.note_reply_user(42, 888) == 101
    reopened.close()
