"""Queue fairness, independent operator leases, and atomic delivery outcomes."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest

from verifydesk.store import CLAIM_SECONDS, Store


def new_ticket(store, uid):
    store.remember_user(uid, uid, f"Client {uid}", None)
    ticket = store.create_ticket(uid, "claude", "armenia", "35.00")[0]
    # This suite covers the existing reply queue; payment stages have their own suite.
    with store.db:
        store.db.execute("UPDATE tickets SET payment_stage='legacy' WHERE id=?", (ticket.id,))
    return store.ticket(ticket.id)


def test_queue_age_tracks_unanswered_turn_not_latest_message(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("verifydesk.store.time.time", lambda: clock[0])
    first = new_ticket(store, 101)
    clock[0] = 1005
    second = new_ticket(store, 102)
    clock[0] = 1010
    store.add_message(first.id, "user", "More details", 101, 101, 1)
    assert store.ticket(first.id).waiting_since == 1000
    assert store.claim_next(42).id == first.id
    assert store.claim_next(42).id == first.id  # Resume, don't silently switch recipient.
    assert store.claim_next(43).id == second.id
    current = store.ticket(first.id)
    store.set_status(first.id, current.version, "waiting_user", 42)
    store.release_claim(42)
    clock[0] = 1020
    store.add_message(first.id, "user", "Client answered", 101, 101, 2)
    assert store.ticket(first.id).waiting_since == 1020
    clock[0] = 1025
    store.add_message(first.id, "user", "Another detail", 101, 101, 3)
    assert store.ticket(first.id).waiting_since == 1020
    store.release_claim(43)
    assert store.claim_next(42).id == second.id


def test_claim_conflicts_expiry_switch_and_explicit_skip(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("verifydesk.store.time.time", lambda: clock[0])
    first, second = new_ticket(store, 101), new_ticket(store, 102)
    assert store.queue_count() == 2
    assert store.claim_ticket(first.id, 42)
    assert store.claim_ticket(second.id, 43)
    assert store.queue_count() == 0
    assert store.queue_count(42) == 1
    assert not store.claim_ticket(second.id, 42)
    assert store.claim_owner(first.id) == 42  # A failed switch must keep the previous claim.
    assert not store.release_claim(43, first.id)
    clock[0] += CLAIM_SECONDS
    assert store.claim_owner(first.id) is None
    assert store.queue_count() == 2
    assert store.claim_ticket(first.id, 43)
    assert store.claim_owner(first.id) == 43
    assert store.claim_next(43, skip_ticket_id=first.id).id == second.id
    assert store.claim_owner(first.id) is None
    assert store.claim_owner(second.id) == 43
    assert store.claim_next(42).id == first.id
    assert store.claim_next(42, skip_ticket_id=first.id) is None
    assert store.claim_owner(first.id) is None


def test_explicit_followup_allowed_but_waiting_and_closed_not_queued(store):
    first, second = new_ticket(store, 101), new_ticket(store, 102)
    first = store.set_status(first.id, first.version, "waiting_user", 42)
    assert store.queue_count() == 1
    assert store.claim_ticket(first.id, 42)  # A deliberate follow-up may continue this chat.
    claimed = store.claim_next(42)
    assert claimed.id == second.id
    assert store.claim_owner(first.id) is None
    closed = store.set_status(claimed.id, claimed.version, "resolved", 42)
    assert store.claim_owner(closed.id) is None
    assert not store.claim_ticket(closed.id, 43)
    assert not store.claim_ticket(999999, 43)
    assert store.claim_next(43) is None


def test_queue_page_matches_available_fifo_and_includes_own_claim(store, monkeypatch):
    monkeypatch.setattr("verifydesk.store.time.time", lambda: 1000)
    tickets = [new_ticket(store, 100 + i) for i in range(12)]
    store.claim_ticket(tickets[0].id, 42)
    store.claim_ticket(tickets[1].id, 43)
    first_page, total = store.queue_page(42)
    second_page, second_total = store.queue_page(42, 8)
    expected = [t.id for t in tickets if t.id != tickets[1].id]
    assert [t.id for t in first_page + second_page] == expected
    assert total == second_total == store.queue_count(42) == 11
    assert store.queue_page(42, 100) == ([], 11)
    for offset, limit in [(-1, 8), (0, 0), (0, 101)]:
        with pytest.raises(ValueError):
            store.queue_page(42, offset, limit)


@pytest.mark.parametrize("same_ticket", [False, True])
def test_simultaneous_claims_from_separate_connections(tmp_path, same_ticket):
    path = tmp_path / "shared.sqlite3"
    seed = Store(path)
    first = new_ticket(seed, 101)
    new_ticket(seed, 102)
    seed.close()
    barrier = Barrier(2)

    def acquire(operator):
        instance = Store(path)
        try:
            barrier.wait(timeout=5)
            if same_ticket:
                return instance.claim_ticket(first.id, operator)
            return instance.claim_next(operator).id
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, (42, 43)))
    if same_ticket:
        assert sorted(results) == [False, True]
    else:
        assert len(set(results)) == 2


def test_thousand_tickets_fifo_no_loss_and_excludes_waiting_customers(store):
    expected = []
    with store.db:
        for number in range(1000):
            uid = 10000 + number
            store.db.execute("INSERT INTO users(id,chat_id,display_name) VALUES(?,?,?)", (uid, uid, str(uid)))
            status = "waiting_user" if number % 10 == 0 else "resolved" if number % 20 == 1 else "new"
            cursor = store.db.execute(
                """INSERT INTO tickets(user_id,status,created_at,updated_at,consent_at,waiting_since)
                VALUES(?,?,100,100,100,?)""",
                (uid, status, 100 + number // 3),
            )
            if status == "new":
                expected.append(cursor.lastrowid)
    assert len(expected) == store.queue_count() == 850
    received = []
    for number in range(len(expected)):
        operator = 42 + number % 3
        ticket = store.claim_next(operator)
        assert ticket is not None
        received.append(ticket.id)
        store.set_status(ticket.id, ticket.version, "waiting_user", operator)
        store.release_claim(operator, ticket.id)
    assert received == expected
    assert store.queue_count() == 0
    assert store.claim_next(42) is None
    assert store.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1000


def test_existing_database_migrates_without_changing_records(tmp_path):
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,chat_id INTEGER NOT NULL,display_name TEXT NOT NULL,username TEXT);
        CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            consent_at REAL NOT NULL,last_read_id INTEGER NOT NULL DEFAULT 0);
        INSERT INTO users VALUES(101,101,'Existing client','existing');
        INSERT INTO tickets(user_id,status,created_at,updated_at,consent_at) VALUES(101,'new',123,456,123);
    """)
    old.close()
    current = Store(path)
    before = current.ticket(1)
    assert (before.status, before.version, before.created_at, before.updated_at, before.waiting_since) == (
        "new", 1, 123, 456, 123
    )
    claimed = current.claim_next(42)
    assert claimed == before
    assert claimed.payment_stage == "legacy"
    current.close()
    reopened = Store(path)
    try:
        assert reopened.ticket(1) == claimed
        assert reopened.claim_owner(1) == 42
    finally:
        reopened.close()


@pytest.mark.parametrize("state", ["failed", "uncertain"])
def test_failed_delivery_preserves_queue_and_claim(store, state):
    ticket = new_ticket(store, 101)
    assert store.claim_ticket(ticket.id, 42)
    store.add_message(ticket.id, "user", "Question", 101, 101, 1)
    message, _ = store.add_message(ticket.id, "operator", "Answer", 42, 42, 2)
    current = store.finalize_operator_delivery(message, state, 42)
    assert current.status == "new"
    assert current.unread == 1
    assert store.claim_owner(ticket.id) == 42
    assert store.queue_count(42) == 1
    assert store.db.execute("SELECT delivery FROM messages WHERE id=?", (message,)).fetchone()[0] == state


def test_confirmed_delivery_atomically_waits_for_user_releases_and_is_idempotent(store):
    ticket = new_ticket(store, 101)
    store.claim_ticket(ticket.id, 42)
    store.add_message(ticket.id, "user", "Question", 101, 101, 1)
    message, _ = store.add_message(ticket.id, "operator", "Answer", 42, 42, 2)
    current = store.finalize_operator_delivery(message, "delivered", 42)
    assert current.status == "waiting_user" and current.unread == 0
    assert store.queue_count() == 0 and store.claim_owner(ticket.id) is None
    assert store.claim_ticket(ticket.id, 42)
    before = store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    repeated = store.finalize_operator_delivery(message, "delivered", 42)
    assert repeated == current
    assert store.claim_owner(ticket.id) == 42  # A duplicate must not release a newer follow-up claim.
    assert store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before


def test_client_message_during_send_stays_unread_and_in_queue(store):
    ticket = new_ticket(store, 101)
    store.claim_ticket(ticket.id, 42)
    store.add_message(ticket.id, "user", "First question", 101, 101, 1)
    message, _ = store.add_message(ticket.id, "operator", "Answer", 42, 42, 2)
    store.add_message(ticket.id, "user", "A new question during delivery", 101, 101, 3)
    current = store.finalize_operator_delivery(message, "delivered", 42)
    assert current.status == "new" and current.unread == 1
    assert store.queue_count() == 1
    assert store.claim_owner(ticket.id) is None
    assert store.claim_next(43).id == ticket.id


def test_finalization_does_not_reopen_closed_ticket_or_allow_wrong_actor(store):
    ticket = new_ticket(store, 101)
    message, _ = store.add_message(ticket.id, "operator", "Answer", 42, 42, 2)
    with pytest.raises(ValueError):
        store.finalize_operator_delivery(message, "delivered", 43)
    store.set_status(ticket.id, ticket.version, "cancelled", 42)
    current = store.finalize_operator_delivery(message, "delivered", 42)
    assert current.status == "cancelled" and store.queue_count() == 0


def test_old_reply_target_blocks_colleague_duplicate_but_fresh_target_allows_followup(store):
    ticket = new_ticket(store, 101)
    store.map_reply(42, 500, ticket.id)
    store.map_reply(43, 501, ticket.id)
    assert not store.stale_operator_reply(43, 501, 43)
    outgoing, _ = store.add_message(ticket.id, "operator", "First answer", 42, 42, 900)
    store.finalize_operator_delivery(outgoing, "delivered", 42)
    assert store.stale_operator_reply(43, 501, 43)
    assert not store.stale_operator_reply(42, 500, 42)  # Same operator may continue their own answer.
    store.map_reply(43, 502, ticket.id)
    assert not store.stale_operator_reply(43, 502, 43)
    snapshot = store.db.execute(
        "SELECT delivered_operator_id FROM reply_targets WHERE chat_id=43 AND message_id=502"
    ).fetchone()[0]
    assert snapshot == outgoing
    followup, _ = store.add_message(ticket.id, "operator", "Deliberate follow-up", 43, 43, 901)
    store.finalize_operator_delivery(followup, "delivered", 43)
    assert not store.stale_operator_reply(43, 502, 43)
    assert store.stale_operator_reply(42, 500, 42)
    assert not store.stale_operator_reply(42, 999, 42)


@pytest.mark.parametrize("state", ["pending", "failed", "uncertain"])
def test_unconfirmed_colleague_reply_does_not_claim_a_delivered_answer(store, state):
    ticket = new_ticket(store, 101)
    store.map_reply(43, 500, ticket.id)
    outgoing, _ = store.add_message(ticket.id, "operator", "Not confirmed", 42, 42, 900)
    if state != "pending":
        store.finalize_operator_delivery(outgoing, state, 42)
    assert not store.stale_operator_reply(43, 500, 43)
    store.map_reply(43, 501, ticket.id)
    assert store.db.execute(
        "SELECT delivered_operator_id FROM reply_targets WHERE chat_id=43 AND message_id=501"
    ).fetchone()[0] == 0


def test_legacy_reply_target_migration_is_conservative_and_preserves_mapping(tmp_path):
    path = tmp_path / "old-target.sqlite3"
    initial = Store(path)
    ticket = new_ticket(initial, 101)
    outgoing, _ = initial.add_message(ticket.id, "operator", "Already answered", 42, 42, 900)
    initial.finalize_operator_delivery(outgoing, "delivered", 42)
    with initial.db:
        initial.db.execute("DROP TABLE reply_targets")
        initial.db.execute(
            """CREATE TABLE reply_targets(
                chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                PRIMARY KEY(chat_id,message_id)
            )"""
        )
        initial.db.execute("INSERT INTO reply_targets VALUES(43,500,?)", (ticket.id,))
    initial.close()
    migrated = Store(path)
    try:
        assert migrated.reply_ticket(43, 500).id == ticket.id
        assert migrated.db.execute("SELECT delivered_operator_id FROM reply_targets").fetchone()[0] == 0
        assert migrated.stale_operator_reply(43, 500, 43)
        migrated.map_reply(43, 500, ticket.id)
        assert not migrated.stale_operator_reply(43, 500, 43)
    finally:
        migrated.close()
