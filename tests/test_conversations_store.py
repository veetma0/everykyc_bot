"""Persistent conversation isolation, safe attachments, and completed-order reviews."""

from pathlib import Path

import pytest

from verifydesk.store import StaleTicket, Store, ticket_status


def seed(store, user=101):
    store.remember_user(user, user, f"Клиент {user}", None)
    order, _ = store.create_ticket(user, "claude", "standard", "45.00")
    wholesale, _ = store.create_ticket(user, kind="wholesale")
    return order, wholesale


def complete(store, ticket, operator=9001):
    with store.db:
        store.db.execute("UPDATE tickets SET payment_stage='legacy' WHERE id=?", (ticket.id,))
    return store.set_status(ticket.id, ticket.version, "resolved", operator)


def test_one_open_order_and_one_wholesale_can_coexist_and_repeat_independently(store):
    order, wholesale = seed(store)
    assert order.id != wholesale.id
    assert order.kind == "order" and wholesale.kind == "wholesale"
    assert wholesale.service_code == "wholesale" and wholesale.price_usd is None
    assert wholesale.payment_stage == "legacy"
    assert store.for_user(101).id == order.id
    assert store.for_user(101, kind="wholesale").id == wholesale.id
    assert store.create_ticket(101, "alipay", "standard", "50.00")[0].id == order.id
    assert store.create_ticket(101, kind="wholesale")[0].id == wholesale.id
    assert store.profile(101).total_tickets == 1
    assert store.profile(101).active_tickets == 1
    assert store.queue_count() == 2
    assert "Опт" in ticket_status(wholesale)
    assert store.stage_counts()["new"] == 2


def test_two_conversations_and_selected_recipient_survive_database_reopen(store):
    order, wholesale = seed(store)
    store.set_customer_focus(101, wholesale.id)
    path = Path(store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    try:
        assert reopened.for_user(101).id == order.id
        assert reopened.for_user(101, kind="wholesale").id == wholesale.id
        assert reopened.customer_focus(101).id == wholesale.id
        assert reopened.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()


def test_focus_is_owned_and_does_not_move_when_other_chat_receives_messages(store):
    order, wholesale = seed(store)
    other_order, _ = seed(store, 102)
    store.set_customer_focus(101, order.id)
    store.add_message(wholesale.id, "operator", "Условия опта", 9001, 9001, 1)
    assert store.customer_focus(101).id == order.id
    with pytest.raises(StaleTicket):
        store.set_customer_focus(101, other_order.id)
    assert store.customer_focus(101).id == order.id
    store.set_customer_focus(101, wholesale.id)
    complete(store, order)
    assert store.customer_focus(101).id == wholesale.id
    complete(store, wholesale)
    assert store.customer_focus(101) is None
    with pytest.raises(StaleTicket):
        store.set_customer_focus(101, wholesale.id)
    # Closing wholesale did not change which order is the historical most recent one.
    assert store.for_user(101).id == order.id


def test_messages_and_customer_reply_targets_are_scoped_to_each_conversation(store):
    order, wholesale = seed(store)
    order_message, _ = store.add_message(order.id, "user", "Вопрос по заказу", 101, 101, 1)
    wholesale_message, _ = store.add_message(wholesale.id, "user", "Вопрос по опту", 101, 101, 2)
    assert store.find_source(101, 1)["ticket_id"] == order.id
    assert store.find_source(101, 2)["ticket_id"] == wholesale.id
    store.map_customer_reply(101, 100, order.id)
    store.map_customer_reply(101, 200, wholesale.id)
    assert store.customer_reply_ticket(101, 100).id == order.id
    assert store.customer_reply_ticket(101, 200).id == wholesale.id
    assert store.ticket(order.id).unread == store.ticket(wholesale.id).unread == 1
    store.mark_read(wholesale.id)
    assert store.ticket(order.id).unread == 1
    assert store.ticket(wholesale.id).unread == 0
    assert order_message != wholesale_message


@pytest.mark.parametrize("file_kind", ["photo", "document", "voice", "video", "audio", "animation", "video_note", "sticker"])
def test_general_chat_attachments_are_persistent_and_never_overwritten(store, file_kind):
    _, wholesale = seed(store)
    message_id, _ = store.add_message(wholesale.id, "user", "Файл по опту", 101, 101, 20)
    store.attach_message(message_id, "file_identifier", file_kind)
    assert store.attachment(message_id)["file_kind"] == file_kind
    assert store.attach_message(message_id, "file_identifier", file_kind)["file_id"] == "file_identifier"
    with pytest.raises(StaleTicket):
        store.attach_message(message_id, "another_file", file_kind)
    path = Path(store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    try:
        assert reopened.attachment(message_id)["file_id"] == "file_identifier"
    finally:
        reopened.close()
    assert not store.payment_proofs(wholesale.id)


def test_rating_is_owned_completed_order_only_and_outside_financial_states(store):
    order, wholesale = seed(store)
    with pytest.raises(StaleTicket):
        store.rate_ticket(order.id, 101, 5)
    complete(store, wholesale)
    with pytest.raises(StaleTicket):
        store.rate_ticket(wholesale.id, 101, 5)
    order = complete(store, order)
    with pytest.raises(StaleTicket):
        store.rate_ticket(order.id, 102, 5)
    rating = store.rate_ticket(order.id, 101, 5)
    assert rating["stars"] == 5 and rating["comment"] is None
    assert rating["finished_at"] is None
    assert store.pending_review(101)["ticket_id"] == order.id
    assert store.pending_review(102) is None
    assert store.ticket(order.id).version == order.version


@pytest.mark.parametrize("stars", [0, 6, -1, "5", True, 4.5, None])
def test_invalid_rating_is_rejected_without_creating_review(store, stars):
    order, _ = seed(store)
    complete(store, order)
    with pytest.raises(ValueError):
        store.rate_ticket(order.id, 101, stars)
    assert store.review(order.id) is None


@pytest.mark.parametrize("comment", [None, "", "   ", "Спасибо за помощь!"])
def test_optional_review_comment_finishes_once_without_touching_wholesale(store, comment):
    order, wholesale = seed(store)
    complete(store, order)
    store.set_customer_focus(101, wholesale.id)
    store.rate_ticket(order.id, 101, 4)
    store.rate_ticket(order.id, 101, 5)
    review = store.finish_review(order.id, 101, comment)
    normalized = comment.strip() or None if comment is not None else None
    assert (review["stars"], review["comment"]) == (5, normalized)
    assert review["finished_at"] is not None
    assert store.pending_review(101) is None
    assert store.customer_focus(101).id == wholesale.id
    assert store.rate_ticket(order.id, 101, 5)["finished_at"] == review["finished_at"]
    assert store.finish_review(order.id, 101, comment)["finished_at"] == review["finished_at"]
    with pytest.raises(StaleTicket):
        store.rate_ticket(order.id, 101, 1)
    with pytest.raises(StaleTicket):
        store.finish_review(order.id, 101, "Подменённый комментарий")


def test_review_pending_and_finished_state_survives_restart(store):
    order, _ = seed(store)
    complete(store, order)
    store.rate_ticket(order.id, 101, 5)
    path = Path(store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    try:
        assert reopened.pending_review(101)["stars"] == 5
        reopened.finish_review(order.id, 101, "Удобно и понятно")
    finally:
        reopened.close()
    assert store.pending_review(101) is None
    assert store.review(order.id)["comment"] == "Удобно и понятно"


def test_invalid_review_comment_does_not_finalize_or_take_other_users_review(store):
    order, _ = seed(store)
    complete(store, order)
    store.rate_ticket(order.id, 101, 5)
    with pytest.raises(StaleTicket):
        store.finish_review(order.id, 102, "Чужой комментарий")
    with pytest.raises(ValueError):
        store.finish_review(order.id, 101, "я" * 2401)
    assert store.pending_review(101)["finished_at"] is None


def test_review_reply_binding_is_owned_persistent_and_keeps_late_reply_target(store):
    order, wholesale = seed(store)
    complete(store, order)
    with pytest.raises(StaleTicket):
        store.map_review_reply(101, 500, order.id)
    store.rate_ticket(order.id, 101, 5)
    store.map_review_reply(101, 500, order.id)
    assert store.review_reply_ticket(101, 500).id == order.id
    assert store.review_reply_ticket(102, 500) is None
    with pytest.raises(StaleTicket):
        store.map_review_reply(102, 500, order.id)
    with pytest.raises(StaleTicket):
        store.map_review_reply(101, 501, wholesale.id)
    path = Path(store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    try:
        assert reopened.review_reply_ticket(101, 500).id == order.id
    finally:
        reopened.close()
    store.finish_review(order.id, 101, "Спасибо")
    assert store.review_reply_ticket(101, 500).id == order.id
    with pytest.raises(StaleTicket):
        store.map_review_reply(101, 501, order.id)


def test_wholesale_cannot_enter_payment_flow_even_if_legacy_data_has_payment_stage(store):
    _, wholesale = seed(store)
    with store.db:
        store.db.execute("UPDATE tickets SET payment_stage='not_requested' WHERE id=?", (wholesale.id,))
    with pytest.raises(StaleTicket):
        store.request_payment(wholesale.id, wholesale.version, 9001)
    with store.db:
        store.db.execute("UPDATE tickets SET payment_stage='awaiting_payment' WHERE id=?", (wholesale.id,))
    with pytest.raises(StaleTicket):
        store.submit_payment_proof(wholesale.id, "https://example.org/receipt", 101, 101, 555)
    assert not store.payment_proofs(wholesale.id)


def test_review_comment_source_is_persistent_and_cannot_be_reused_for_other_review(store):
    order, _ = seed(store)
    complete(store, order)
    store.rate_ticket(order.id, 101, 5)
    saved = store.finish_review(order.id, 101, "Спасибо", source_chat=101, source_message=777)
    assert store.review_source(101, 777)["ticket_id"] == order.id
    assert store.review_source(102, 777) is None
    assert store.finish_review(order.id, 101, "Спасибо", source_chat=101, source_message=777)["finished_at"] == saved["finished_at"]
    new, _ = store.create_ticket(101)
    complete(store, new)
    store.rate_ticket(new.id, 101, 5)
    with pytest.raises(StaleTicket):
        store.finish_review(new.id, 101, "Спасибо", source_chat=101, source_message=777)
    assert store.review(new.id)["finished_at"] is None
    path = Path(store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    try:
        assert reopened.review_source(101, 777)["ticket_id"] == order.id
    finally:
        reopened.close()


@pytest.mark.parametrize("source_chat,source_message", [(101, None), (None, 1), (101, 0), (101, True), (102, 1)])
def test_review_comment_source_is_complete_owned_and_valid(store, source_chat, source_message):
    order, _ = seed(store)
    complete(store, order)
    store.rate_ticket(order.id, 101, 5)
    with pytest.raises((ValueError, StaleTicket)):
        store.finish_review(order.id, 101, "Спасибо", source_chat=source_chat, source_message=source_message)
    assert store.review(order.id)["finished_at"] is None
