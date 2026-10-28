"""Manual payment approval gates work without rewriting old orders."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest

from verifydesk.store import StaleTicket, Store, ticket_status


def create_order(store, uid=101):
    store.remember_user(uid, uid, f"Client {uid}", None)
    return store.create_ticket(uid, "claude", "armenia", "35.00")[0]


def awaiting_payment(store, uid=101):
    order = create_order(store, uid)
    return store.request_payment(order.id, order.version, 42)


def payment_review(store, uid=101):
    order = awaiting_payment(store, uid)
    store.submit_payment_proof(order.id, "https://example.com/test-receipt", uid, uid, 1)
    return store.ticket(order.id)


def test_order_follows_manual_payment_then_work_and_completion(store):
    order = create_order(store)
    assert order.status == "new" and order.payment_stage == "not_requested"
    assert ticket_status(order) == "⏳ Ожидает оператора"
    assert store.claim_next(42) == order
    assert store.claim_ticket(order.id, 42)
    assert store.ticket(order.id) == order  # A claim alone never starts the work.

    payment = store.request_payment(order.id, order.version, 42)
    assert payment.status == "new" and payment.payment_stage == "awaiting_payment"
    assert ticket_status(payment) == "💳 Ожидает оплаты"
    assert store.claim_owner(order.id) is None
    assert store.queue_count() == 0
    assert store.queue_page(42) == ([], 0)
    assert store.claim_next(42) is None

    proof_id, created = store.submit_payment_proof(order.id, "Test receipt", 101, 101, 1, "file-123", "photo")
    assert created
    review = store.ticket(order.id)
    assert review.status == "new" and review.payment_stage == "review"
    assert ticket_status(review) == "🔎 Проверяем оплату"
    assert store.queue_count() == 1
    assert store.queue_page(42)[0] == [review]
    assert store.claim_next(42) == review
    proof = store.payment_proofs(order.id)[0]
    assert (proof["id"], proof["source_chat"], proof["source_message"]) == (proof_id, 101, 1)
    assert (proof["body"], proof["file_id"], proof["file_kind"]) == ("Test receipt", "file-123", "photo")

    working = store.confirm_payment(order.id, review.version, 42)
    assert working.status == "in_progress" and working.payment_stage == "confirmed"
    assert ticket_status(working) == "🛠 В работе"
    done = store.set_status(order.id, working.version, "resolved", 42)
    assert ticket_status(done) == "✅ Заказ выполнен"
    assert store.for_user(101, active_only=True) is None


@pytest.mark.parametrize("stage", ["not_requested", "awaiting_payment", "review"])
@pytest.mark.parametrize("status", ["in_progress", "waiting_user", "resolved"])
def test_old_status_controls_cannot_skip_payment(store, stage, status):
    order = create_order(store)
    if stage != "not_requested":
        order = store.request_payment(order.id, order.version, 42)
    if stage == "review":
        store.submit_payment_proof(order.id, "https://example.com/receipt", 101, 101, 1)
        order = store.ticket(order.id)
    with pytest.raises(StaleTicket, match="Сначала подтвердите оплату"):
        store.set_status(order.id, order.version, status, 42)
    assert store.ticket(order.id) == order


@pytest.mark.parametrize("stage", ["not_requested", "awaiting_payment"])
def test_unpaid_orders_can_be_cancelled_by_customer_even_when_claimed(store, stage):
    order = create_order(store)
    if stage != "not_requested":
        order = store.request_payment(order.id, order.version, 42)
    if stage == "review":
        store.submit_payment_proof(order.id, "receipt", 101, 101, 1)
        order = store.ticket(order.id)
    store.claim_ticket(order.id, 42)
    cancelled = store.set_status(order.id, order.version, "cancelled", 101, customer_cancel=True)
    assert ticket_status(cancelled) == "❌ Заказ отменён"
    assert store.claim_owner(order.id) is None
    assert store.queue_count() == 0


def test_rejected_receipt_requires_new_evidence_and_preserves_old_records(store):
    order = payment_review(store)
    first_proof = store.payment_proofs(order.id)[0]["id"]
    assert store.claim_ticket(order.id, 42)
    rejected = store.reject_payment(order.id, order.version, 42)
    assert rejected.payment_stage == "awaiting_payment"
    assert store.claim_owner(order.id) is None
    assert store.queue_count() == 0
    with pytest.raises(StaleTicket):
        store.confirm_payment(order.id, rejected.version, 42)
    assert store.submit_payment_proof(order.id, "Same receipt", 101, 101, 1) == (first_proof, False)
    assert store.ticket(order.id) == rejected
    store.submit_payment_proof(order.id, "New receipt", 101, 101, 2, "test-file", "document")
    review = store.ticket(order.id)
    assert review.payment_stage == "review"
    assert len(store.payment_proofs(order.id)) == 2
    assert store.payment_proofs(order.id)[0]["source_message"] == 2
    assert store.confirm_payment(order.id, review.version, 42).payment_stage == "confirmed"


def test_evidence_duplicate_is_idempotent_even_after_confirmation(store):
    order = payment_review(store)
    proof_id = store.payment_proofs(order.id)[0]["id"]
    confirmed = store.confirm_payment(order.id, order.version, 42)
    assert store.submit_payment_proof(order.id, "duplicate", 101, 101, 1) == (proof_id, False)
    assert store.ticket(order.id) == confirmed
    assert len(store.payment_proofs(order.id)) == 1


def test_proof_requires_order_owner_and_correct_phase(store):
    order = create_order(store)
    for actor, chat in [(102, 102), (101, 102), (102, 101)]:
        with pytest.raises(StaleTicket):
            store.submit_payment_proof(order.id, "receipt", actor, chat, 1)
    with pytest.raises(StaleTicket):
        store.submit_payment_proof(order.id, "receipt", 101, 101, 1)
    assert store.payment_proofs(order.id) == []


@pytest.mark.parametrize("file_id,file_kind", [(None, "photo"), ("", "photo"), ("file", None), ("file", "video")])
def test_invalid_evidence_metadata_is_not_saved(store, file_id, file_kind):
    order = awaiting_payment(store)
    with pytest.raises(ValueError):
        store.submit_payment_proof(order.id, "receipt", 101, 101, 1, file_id, file_kind)
    assert store.ticket(order.id) == order
    assert store.payment_proofs(order.id) == []


def test_same_source_cannot_be_attached_to_a_different_order(store):
    order = payment_review(store)
    store.set_status(order.id, order.version, "cancelled", 101)
    another = awaiting_payment(store)
    with pytest.raises(StaleTicket):
        store.submit_payment_proof(another.id, "receipt", 101, 101, 1)
    assert store.payment_proofs(another.id) == []


def test_payment_mutations_reject_stale_versions_and_other_operator_claim(store):
    original = create_order(store)
    store.claim_ticket(original.id, 42)
    with pytest.raises(StaleTicket):
        store.request_payment(original.id, original.version, 43)
    requested = store.request_payment(original.id, original.version, 42)
    with pytest.raises(StaleTicket):
        store.request_payment(original.id, original.version, 42)
    store.submit_payment_proof(original.id, "receipt", 101, 101, 1)
    review = store.ticket(original.id)
    store.claim_ticket(original.id, 42)
    for method in [store.confirm_payment, store.reject_payment]:
        with pytest.raises(StaleTicket):
            method(original.id, requested.version, 42)
        with pytest.raises(StaleTicket):
            method(original.id, review.version, 43)
    store.submit_payment_proof(original.id, "additional receipt", 101, 101, 2)
    with pytest.raises(StaleTicket):
        store.confirm_payment(original.id, review.version, 42)
    assert store.ticket(original.id).payment_stage == "review"


@pytest.mark.parametrize("stage", ["not_requested", "awaiting_payment", "review"])
def test_operator_reply_never_starts_or_skips_unpaid_order(store, stage):
    order = create_order(store)
    if stage != "not_requested":
        order = store.request_payment(order.id, order.version, 42)
    if stage == "review":
        store.submit_payment_proof(order.id, "receipt", 101, 101, 1)
    outgoing, _ = store.add_message(order.id, "operator", "Message", 42, 42, 20)
    current = store.finalize_operator_delivery(outgoing, "delivered", 42)
    assert current.status == "new" and current.payment_stage == stage
    store.add_message(order.id, "user", "Question", 101, 101, 2)
    assert store.ticket(order.id).payment_stage == stage


def test_confirmed_order_keeps_reply_queue_behavior(store):
    review = payment_review(store)
    order = store.confirm_payment(review.id, review.version, 42)
    outgoing, _ = store.add_message(order.id, "operator", "Question", 42, 42, 20)
    waiting = store.finalize_operator_delivery(outgoing, "delivered", 42)
    assert waiting.status == "waiting_user" and waiting.payment_stage == "confirmed"
    assert ticket_status(waiting) == "🛠 В работе" and store.queue_count() == 0
    store.add_message(order.id, "user", "Answer", 101, 101, 2)
    assert store.ticket(order.id).status == "in_progress" and store.queue_count() == 1


def test_proof_transaction_rolls_back_when_metadata_cannot_be_written(store):
    order = awaiting_payment(store)
    store.db.execute(
        """CREATE TRIGGER reject_proof BEFORE INSERT ON payment_proofs
        BEGIN SELECT RAISE(ABORT, 'proof failed'); END"""
    )
    with pytest.raises(sqlite3.IntegrityError, match="proof failed"):
        store.submit_payment_proof(order.id, "receipt", 101, 101, 1)
    assert store.ticket(order.id) == order
    assert store.find_source(101, 1) is None


def test_review_queue_age_starts_on_first_proof_not_each_followup(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("verifydesk.store.time.time", lambda: clock[0])
    order = awaiting_payment(store)
    clock[0] = 1010.0
    store.submit_payment_proof(order.id, "receipt", 101, 101, 1)
    clock[0] = 1020.0
    store.submit_payment_proof(order.id, "additional receipt", 101, 101, 2)
    assert store.ticket(order.id).waiting_since == 1010
    review = store.ticket(order.id)
    store.reject_payment(order.id, review.version, 42)
    clock[0] = 1030.0
    store.submit_payment_proof(order.id, "new receipt", 101, 101, 3)
    assert store.ticket(order.id).waiting_since == 1030


def test_concurrent_confirm_and_reject_only_one_version_wins(tmp_path):
    path = tmp_path / "race.sqlite3"
    initial = Store(path)
    review = payment_review(initial)
    initial.close()
    barrier = Barrier(2)

    def decide(method):
        instance = Store(path)
        try:
            barrier.wait(timeout=5)
            try:
                return getattr(instance, method)(review.id, review.version, 42).payment_stage
            except StaleTicket:
                return "stale"
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ("confirm_payment", "reject_payment")))
    assert results.count("stale") == 1
    reopened = Store(path)
    try:
        assert reopened.ticket(review.id).version == review.version + 1
        assert reopened.ticket(review.id).payment_stage in {"confirmed", "awaiting_payment"}
    finally:
        reopened.close()


def test_concurrent_duplicate_evidence_is_saved_once(tmp_path):
    path = tmp_path / "duplicate.sqlite3"
    initial = Store(path)
    order = awaiting_payment(initial)
    initial.close()
    barrier = Barrier(2)

    def submit(_):
        instance = Store(path)
        try:
            barrier.wait(timeout=5)
            return instance.submit_payment_proof(order.id, "receipt", 101, 101, 1)
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (1, 2)))
    assert len({result[0] for result in results}) == 1
    assert sorted(result[1] for result in results) == [False, True]
    reopened = Store(path)
    try:
        assert len(reopened.payment_proofs(order.id)) == 1
        assert reopened.ticket(order.id).version == order.version + 1
    finally:
        reopened.close()


def test_pre_payment_schema_migrates_existing_orders_as_legacy(tmp_path):
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,chat_id INTEGER NOT NULL,display_name TEXT NOT NULL,username);
        CREATE TABLE tickets(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            consent_at REAL NOT NULL,last_read_id INTEGER NOT NULL DEFAULT 0);
        INSERT INTO users VALUES(101,101,'Existing',NULL);
        INSERT INTO tickets VALUES(1,101,'new',7,123,456,123,0);
    """)
    old.close()
    migrated = Store(path)
    try:
        order = migrated.ticket(1)
        assert (order.status, order.payment_stage, order.version, order.created_at) == ("new", "legacy", 7, 123)
        assert migrated.claim_next(42) == order
        done = migrated.set_status(order.id, order.version, "resolved", 42)
        assert done.status == "resolved" and done.payment_stage == "legacy"
        assert migrated.payment_proofs(order.id) == []
    finally:
        migrated.close()
