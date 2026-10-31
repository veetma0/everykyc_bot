"""Direct messages, independently selected conversations, and completed-order reviews."""

import pytest

from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .payment_helpers import legacy_ticket
from .test_upgrade import callbacks, last, order, sent


DOCUMENT = {
    "file_id": "chat_document", "file_unique_id": "chat_document_unique",
    "file_name": "details.pdf", "mime_type": "application/pdf", "file_size": 1000,
}


def user_messages(env, ticket_id):
    return [r["body"] for r in env.store.db.execute(
        "SELECT body FROM messages WHERE ticket_id=? AND role='user' ORDER BY id", (ticket_id,),
    )]


def operator_messages(env, ticket_id):
    return [r["body"] for r in env.store.db.execute(
        "SELECT body FROM messages WHERE ticket_id=? AND role='operator' ORDER BY id", (ticket_id,),
    )]


def media_calls(env, uid):
    return [(method, params) for method, params in env.request.calls
            if method in {"sendPhoto", "sendDocument"} and params["chat_id"] == uid]


async def wholesale(env, uid=CLIENT):
    await env.callback(uid, "c:wholesale")
    ticket = env.store.for_user(uid, active_only=True, kind="wholesale")
    assert ticket is not None
    return ticket


async def request_payment(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    return env.store.ticket(ticket.id)


async def complete_order(env):
    ticket = legacy_ticket(env.store, await order(env))
    await env.callback(ADMIN, f"a:set:{ticket.id}:{ticket.version}:resolved")
    await env.callback(ADMIN, f"a:confirm:{ticket.id}:{ticket.version}:resolved")
    assert env.store.ticket(ticket.id).status == "resolved"
    return env.store.ticket(ticket.id)


@pytest.mark.parametrize("body", ["ок", "1", "250", "Оплатил", "Спасибо!", "Уточните, пожалуйста, условия"])
async def test_plain_customer_messages_arrive_without_a_send_step(env, body):
    ticket = await order(env)
    await env.message(CLIENT, body, message_id=801)
    assert user_messages(env, ticket.id) == [body]
    assert body in last(env, ADMIN)["text"]
    assert env.store.draft(CLIENT) is None
    assert not any(value.startswith(("c:send_draft:", "c:proof_prompt:"))
                   for params in sent(env, CLIENT) for value in callbacks(params))
    before = len(env.request.calls)
    await env.message(CLIENT, body, message_id=801)
    assert user_messages(env, ticket.id) == [body]
    assert len(env.request.calls) == before


@pytest.mark.parametrize("attachment,method", [("photo", "sendPhoto"), ("document", "sendDocument")])
async def test_customer_media_goes_to_operator_directly_in_selected_conversation(env, attachment, method):
    ticket = await order(env)
    kwargs = {"photo": True} if attachment == "photo" else {"document": DOCUMENT}
    await env.message(CLIENT, caption="Пример ошибки без персональных данных", message_id=802, **kwargs)
    row = env.store.find_source(CLIENT, 802)
    assert row is not None and row["ticket_id"] == ticket.id and row["role"] == "user"
    assert env.store.attachment(row["id"])["file_kind"] == attachment
    assert any(name == method for name, _ in media_calls(env, ADMIN))
    assert env.store.draft(CLIENT) is None
    assert not env.store.payment_proofs(ticket.id)
    assert not any(name == "getFile" for name, _ in env.request.calls)


@pytest.mark.parametrize("proof", ["photo", "document", "link"])
async def test_payment_proof_is_submitted_directly_and_waits_for_manual_operator_confirmation(env, proof):
    ticket = await request_payment(env)
    if proof == "photo":
        await env.message(CLIENT, photo=True, caption="Чек", message_id=803)
    elif proof == "document":
        await env.message(CLIENT, document=DOCUMENT, caption="Чек", message_id=803)
    else:
        await env.message(CLIENT, "Чек: https://example.org/receipt/803", message_id=803)
    current = env.store.ticket(ticket.id)
    assert current.payment_stage == "review" and current.status == "new"
    assert len(env.store.payment_proofs(ticket.id)) == 1
    assert env.store.draft(CLIENT) is None
    assert any(value.startswith(f"a:confirm_payment:{ticket.id}:") for value in callbacks(last(env, ADMIN)))
    await env.message(CLIENT, "Оплатил", message_id=804)
    assert len(env.store.payment_proofs(ticket.id)) == 1
    assert env.store.ticket(ticket.id).payment_stage == "review"
    current = env.store.ticket(ticket.id)
    await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{current.version}")
    assert env.store.ticket(ticket.id).payment_stage == "confirmed"
    assert "Оплата подтверждена" in last(env, CLIENT)["text"]


async def test_wholesale_and_transaction_keep_separate_messages_and_payment_state(env):
    transaction = await request_payment(env)
    discussion = await wholesale(env)
    assert discussion.id != transaction.id and discussion.kind == "wholesale"
    assert env.store.customer_focus(CLIENT).id == discussion.id
    await env.message(CLIENT, "Нужно 30 заказов в неделю", message_id=810)
    await env.message(CLIENT, photo=True, caption="Объёмы", message_id=811)
    assert "Нужно 30 заказов в неделю" in user_messages(env, discussion.id)
    assert not user_messages(env, transaction.id)
    assert not env.store.payment_proofs(discussion.id)
    assert env.store.ticket(transaction.id).payment_stage == "awaiting_payment"
    await env.callback(CLIENT, f"c:chat:{transaction.id}")
    await env.message(CLIENT, "Вопрос по текущей сделке", message_id=812)
    assert user_messages(env, transaction.id) == ["Вопрос по текущей сделке"]
    assert "Вопрос по текущей сделке" not in user_messages(env, discussion.id)
    await env.callback(CLIENT, "c:wholesale")
    assert env.store.for_user(CLIENT, kind="wholesale").id == discussion.id
    assert env.store.profile(CLIENT).total_tickets == 1


async def test_context_is_visible_and_can_be_switched_without_a_send_button(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    data = callbacks(last(env, CLIENT))
    assert f"c:chat:{transaction.id}" in data and f"c:chat:{discussion.id}" in data
    assert not any(v.startswith(("c:write:", "c:proof_prompt:", "c:send_draft:")) for v in data)
    await env.callback(CLIENT, f"c:chat:{transaction.id}")
    assert env.store.customer_focus(CLIENT).id == transaction.id
    assert f"{transaction.id:04d}" in last(env, CLIENT)["text"]


async def test_explicit_reply_targets_its_conversation_without_changing_selected_chat(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    env.store.map_customer_reply(CLIENT, 850, transaction.id)
    await env.message(CLIENT, "Ответ именно по сделке", reply_to=850, message_id=813)
    assert user_messages(env, transaction.id) == ["Ответ именно по сделке"]
    assert env.store.customer_focus(CLIENT).id == discussion.id
    await env.message(CLIENT, "Следующий вопрос об опте", message_id=814)
    assert user_messages(env, discussion.id) == ["Следующий вопрос об опте"]


async def test_operator_notifications_do_not_retarget_customer_selected_chat(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    await env.callback(ADMIN, f"a:reply:{transaction.id}")
    await env.message(ADMIN, "Уточнение по вашей сделке", message_id=820)
    assert env.store.customer_focus(CLIENT).id == discussion.id
    await env.message(CLIENT, "Продолжаем обсуждение опта", message_id=821)
    assert user_messages(env, discussion.id) == ["Продолжаем обсуждение опта"]
    assert not user_messages(env, transaction.id)


async def test_missing_focus_with_two_chats_requires_selection_and_does_not_forward(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    env.store.clear_customer_focus(CLIENT)
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Куда относится этот вопрос?", message_id=822)
    assert not user_messages(env, transaction.id) and not user_messages(env, discussion.id)
    assert len(sent(env, ADMIN)) == before
    assert f"c:chat:{transaction.id}" in callbacks(last(env, CLIENT))
    assert f"c:chat:{discussion.id}" in callbacks(last(env, CLIENT))


async def test_selected_chat_persists_in_database(env, tmp_path):
    transaction = await order(env)
    await wholesale(env)
    await env.callback(CLIENT, f"c:chat:{transaction.id}")
    reopened = Store(tmp_path / "desk.sqlite3")
    try:
        assert reopened.customer_focus(CLIENT).id == transaction.id
    finally:
        reopened.close()


@pytest.mark.parametrize("foreign", [False, True])
async def test_closed_or_other_customers_reply_context_never_falls_into_selected_chat(env, foreign):
    transaction = await order(env)
    discussion = await wholesale(env)
    if foreign:
        target = await order(env, uid=OTHER)
    else:
        legacy_ticket(env.store, transaction)
        target = env.store.set_status(transaction.id, transaction.version, "resolved", ADMIN)
    env.store.map_customer_reply(CLIENT, 851, target.id)
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Ответ в недоступную переписку", reply_to=851, message_id=823)
    assert not user_messages(env, discussion.id)
    assert len(sent(env, ADMIN)) == before


async def test_operator_selected_reply_sends_multiple_messages_directly_without_drafts(env):
    transaction = await order(env)
    await env.callback(ADMIN, f"a:reply:{transaction.id}")
    await env.message(ADMIN, "Первое сообщение", message_id=830)
    await order(env, uid=OTHER)
    await env.message(ADMIN, "Продолжение той же переписки", message_id=831)
    assert operator_messages(env, transaction.id) == ["Первое сообщение", "Продолжение той же переписки"]
    assert env.store.draft(ADMIN) is None
    assert not operator_messages(env, env.store.for_user(OTHER).id)
    assert "Продолжение той же переписки" in last(env, CLIENT)["text"]
    before = len(sent(env, CLIENT))
    await env.message(ADMIN, "Продолжение той же переписки", message_id=831)
    assert len(sent(env, CLIENT)) == before


@pytest.mark.parametrize("attachment,method", [("photo", "sendPhoto"), ("document", "sendDocument")])
async def test_operator_sends_media_to_selected_customer_without_extra_confirmation(env, attachment, method):
    transaction = await order(env)
    await env.callback(ADMIN, f"a:reply:{transaction.id}")
    kwargs = {"photo": True} if attachment == "photo" else {"document": DOCUMENT}
    await env.message(ADMIN, caption="Реквизиты и условия", message_id=832, **kwargs)
    assert any(name == method for name, _ in media_calls(env, CLIENT))
    row = env.store.find_source(ADMIN, 832)
    assert row is not None and row["ticket_id"] == transaction.id and row["role"] == "operator"
    assert env.store.attachment(row["id"])["file_kind"] == attachment
    assert env.store.draft(ADMIN) is None


async def test_operator_reply_switches_only_when_explicitly_selecting_another_context(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    await env.callback(ADMIN, f"a:reply:{transaction.id}")
    await env.message(ADMIN, "Ответ по сделке", message_id=833)
    await env.callback(ADMIN, f"a:reply:{discussion.id}")
    await env.message(ADMIN, "Ответ по опту", message_id=834)
    assert operator_messages(env, transaction.id) == ["Ответ по сделке"]
    assert operator_messages(env, discussion.id) == ["Ответ по опту"]


async def test_completion_invites_rating_and_optional_comment_can_be_skipped(env):
    ticket = await complete_order(env)
    data = [value for params in sent(env, CLIENT) for value in callbacks(params)]
    assert {f"c:rate:{ticket.id}:{stars}" for stars in range(1, 6)} <= set(data)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:5")
    assert env.store.review(ticket.id)["stars"] == 5
    assert env.store.pending_review(CLIENT)["ticket_id"] == ticket.id
    assert f"c:review_skip:{ticket.id}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:review_skip:{ticket.id}")
    saved = env.store.review(ticket.id)
    assert saved["stars"] == 5 and not saved["comment"]
    assert env.store.pending_review(CLIENT) is None


async def test_review_comment_is_saved_once_and_not_sent_to_other_conversations(env):
    ticket = await complete_order(env)
    discussion = await wholesale(env)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:4")
    await env.message(CLIENT, "Быстро ответили, всё понятно", message_id=840)
    saved = env.store.review(ticket.id)
    assert saved["stars"] == 4 and saved["comment"] == "Быстро ответили, всё понятно"
    assert env.store.pending_review(CLIENT) is None
    assert not user_messages(env, discussion.id)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:1")
    assert env.store.review(ticket.id)["stars"] == 4
    assert env.store.review(ticket.id)["comment"] == "Быстро ответили, всё понятно"


async def test_reply_to_chat_during_review_keeps_message_and_review_separate(env):
    ticket = await complete_order(env)
    discussion = await wholesale(env)
    env.store.map_customer_reply(CLIENT, 852, discussion.id)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:5")
    await env.message(CLIENT, "По опту нужен другой объём", reply_to=852, message_id=841)
    assert user_messages(env, discussion.id) == ["По опту нужен другой объём"]
    assert env.store.pending_review(CLIENT) is None
    assert env.store.review(ticket.id)["stars"] == 5
    assert not env.store.review(ticket.id)["comment"]


async def test_reviews_reject_foreign_unfinished_cancelled_wholesale_and_invalid_stars(env):
    transaction = await order(env)
    await env.callback(CLIENT, f"c:rate:{transaction.id}:5")
    assert env.store.review(transaction.id) is None
    transaction = legacy_ticket(env.store, env.store.ticket(transaction.id))
    transaction = env.store.set_status(transaction.id, transaction.version, "cancelled", ADMIN)
    await env.callback(CLIENT, f"c:rate:{transaction.id}:5")
    assert env.store.review(transaction.id) is None
    discussion = await wholesale(env)
    discussion = env.store.set_status(discussion.id, discussion.version, "resolved", ADMIN)
    await env.callback(CLIENT, f"c:rate:{discussion.id}:5")
    assert env.store.review(discussion.id) is None
    ticket = await complete_order(env)
    for uid, stars in ((OTHER, 5), (CLIENT, 0), (CLIENT, 6), (CLIENT, -1)):
        await env.callback(uid, f"c:rate:{ticket.id}:{stars}")
        assert env.store.review(ticket.id) is None
    await env.callback(OTHER, f"c:review_skip:{ticket.id}")
    assert env.store.review(ticket.id) is None


async def test_duplicate_review_comment_never_becomes_a_chat_message(env):
    ticket = await complete_order(env)
    discussion = await wholesale(env)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:5")
    await env.message(CLIENT, "Хорошая работа", message_id=860)
    assert env.store.review(ticket.id)["comment"] == "Хорошая работа"
    await env.callback(CLIENT, f"c:chat:{discussion.id}")
    before = len(env.request.calls)
    await env.message(CLIENT, "Хорошая работа", message_id=860)
    assert not user_messages(env, discussion.id)
    assert len(env.request.calls) == before


async def test_switching_back_to_chat_saves_stars_without_capturing_chat_as_comment(env):
    ticket = await complete_order(env)
    discussion = await wholesale(env)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:4")
    await env.callback(CLIENT, f"c:chat:{discussion.id}")
    await env.message(CLIENT, "Продолжаем обсуждать объём", message_id=861)
    assert user_messages(env, discussion.id) == ["Продолжаем обсуждать объём"]
    assert env.store.review(ticket.id)["stars"] == 4
    assert not env.store.review(ticket.id)["comment"]
    assert env.store.pending_review(CLIENT) is None


async def test_opening_current_transaction_explicitly_selects_it_after_wholesale(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    assert env.store.customer_focus(CLIENT).id == discussion.id
    await env.callback(CLIENT, "c:current")
    assert env.store.customer_focus(CLIENT).id == transaction.id
    await env.message(CLIENT, "Это вопрос по открытой сделке", message_id=870)
    assert user_messages(env, transaction.id) == ["Это вопрос по открытой сделке"]
    assert not user_messages(env, discussion.id)


async def test_choosing_another_completed_order_review_finalizes_previous_comment_mode(env):
    first = await complete_order(env)
    second = await complete_order(env)
    discussion = await wholesale(env)
    await env.callback(CLIENT, f"c:rate:{first.id}:4")
    await env.callback(CLIENT, f"c:rate:{second.id}:5")
    assert env.store.review(first.id)["finished_at"] is not None
    assert not env.store.review(first.id)["comment"]
    await env.callback(CLIENT, f"c:review_skip:{second.id}")
    assert env.store.pending_review(CLIENT) is None
    await env.message(CLIENT, "Продолжим обсуждение опта", message_id=871)
    assert user_messages(env, discussion.id) == ["Продолжим обсуждение опта"]
    assert not env.store.review(first.id)["comment"]
    assert not env.store.review(second.id)["comment"]


async def test_reused_review_card_routes_reply_to_the_currently_visible_chat(env):
    ticket = await complete_order(env)
    discussion = await wholesale(env)
    await env.callback(CLIENT, f"c:rate:{ticket.id}:5", card=500)
    assert env.store.review_reply_ticket(CLIENT, 500).id == ticket.id
    await env.callback(CLIENT, f"c:chat:{discussion.id}", card=500)
    assert env.store.review_reply_ticket(CLIENT, 500) is None
    assert env.store.customer_reply_ticket(CLIENT, 500).id == discussion.id
    await env.message(CLIENT, "Ответ на видимую карточку опта", reply_to=500, message_id=872)
    assert user_messages(env, discussion.id) == ["Ответ на видимую карточку опта"]
    assert env.store.review(ticket.id)["stars"] == 5
    assert not env.store.review(ticket.id)["comment"]


async def test_closed_selected_transaction_never_silently_falls_into_remaining_wholesale_chat(env):
    transaction = await order(env)
    discussion = await wholesale(env)
    await env.callback(CLIENT, f"c:chat:{transaction.id}")
    env.store.set_status(transaction.id, transaction.version, "cancelled", ADMIN)
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, "Уточнение по закрытой сделке", message_id=880)
    assert not user_messages(env, transaction.id)
    assert not user_messages(env, discussion.id)
    assert len(sent(env, ADMIN)) == before
    assert f"c:chat:{discussion.id}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:chat:{discussion.id}")
    await env.message(CLIENT, "Теперь обсуждаем опт", message_id=881)
    assert user_messages(env, discussion.id) == ["Теперь обсуждаем опт"]


@pytest.mark.parametrize("failure,expected", [("failed", "failed"), ("uncertain", "uncertain")])
async def test_failed_media_delivery_is_recorded_and_attachment_can_be_reopened_from_history(
    env, monkeypatch, failure, expected,
):
    from telegram.error import Forbidden, TimedOut

    transaction = await order(env)
    original_request = env.request.do_request
    media_error = Forbidden("Media blocked") if failure == "failed" else TimedOut()

    async def fail_photo_only(url, method, request_data=None, **kwargs):
        params = request_data.parameters if request_data else {}
        if url.endswith("/sendPhoto") and params.get("chat_id") == ADMIN:
            raise media_error
        return await original_request(url, method, request_data=request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", fail_photo_only)
    await env.message(CLIENT, photo=True, caption="Фото ошибки", message_id=882)
    stored = env.store.find_source(CLIENT, 882)
    assert stored["delivery"] == expected
    assert "Фото ошибки" in last(env, ADMIN)["text"]
    assert not media_calls(env, ADMIN)
    attachment = env.store.attachment(stored["id"])
    assert attachment["file_id"] == "secret_document"
    for uid, prefix in ((ADMIN, "a"), (CLIENT, "c")):
        await env.callback(uid, f"{prefix}:history:{transaction.id}:0")
        assert f"{prefix}:message:{transaction.id}:{stored['id']}" in callbacks(last(env, uid))
    monkeypatch.setattr(env.request, "do_request", original_request)
    await env.callback(ADMIN, f"a:message:{transaction.id}:{stored['id']}")
    assert any(method == "sendPhoto" and params.get("photo") == "secret_document"
               for method, params in media_calls(env, ADMIN))
    assert not any(method == "getFile" for method, _ in env.request.calls)


async def test_long_operator_attachment_caption_is_preserved_in_customer_history(env):
    transaction = await order(env)
    await env.callback(ADMIN, f"a:reply:{transaction.id}")
    caption = "Условия <b>без разметки</b> & " + "Подробное пояснение. " * 70
    await env.message(ADMIN, document=DOCUMENT, caption=caption, message_id=883)
    stored = env.store.find_source(ADMIN, 883)
    assert stored["body"] == caption
    received = media_calls(env, CLIENT)[-1][1]
    assert len(received["caption"]) < len(caption)
    assert "Полный текст" in received["caption"]
    await env.callback(CLIENT, f"c:history:{transaction.id}:0")
    assert f"c:message:{transaction.id}:{stored['id']}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:message:{transaction.id}:{stored['id']}")
    assert "Подробное пояснение. " * 70 in last(env, CLIENT)["text"]
    assert "&lt;b&gt;без разметки&lt;/b&gt; &amp;" in last(env, CLIENT)["text"]
    assert not any(method == "getFile" for method, _ in env.request.calls)


async def test_plain_followup_during_review_stays_visible_without_resending_old_receipt(env):
    await request_payment(env)
    await env.message(CLIENT, photo=True, caption="Чек", message_id=10001)
    images_before = len(media_calls(env, ADMIN))
    await env.message(CLIENT, "Проверьте, пожалуйста, именно эту сумму", message_id=10002)
    assert "Проверьте, пожалуйста, именно эту сумму" in last(env, ADMIN)["text"]
    assert len(media_calls(env, ADMIN)) == images_before
