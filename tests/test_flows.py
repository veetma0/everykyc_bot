from telegram.error import Forbidden, TimedOut

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last


def texts(env, chat=None):
    return [
        params["text"]
        for method, params in env.request.calls
        if method in {"sendMessage", "editMessageText"} and (chat is None or params["chat_id"] == chat)
    ]


async def create(env, uid=CLIENT):
    await env.callback(uid, "c:order:claude:armenia")
    return env.store.for_user(uid)


async def test_full_customer_operator_flow(env):
    await env.message(CLIENT, "/start")
    assert "Эврикус" in texts(env, CLIENT)[-1]
    assert "c:service:claude" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, "c:prepare")
    assert "c:service:claude" in callbacks(last(env, CLIENT))
    assert "c:create" not in callbacks(last(env, CLIENT))
    ticket = await create(env)
    assert ticket.status == "new"
    await env.message(CLIENT, "Не могу открыть проверку")
    assert env.store.ticket(ticket.id).unread == 1
    assert any("Не могу открыть" in text for text in texts(env, ADMIN))
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    prompt_id = env.store.db.execute(
        "SELECT MAX(message_id) FROM reply_targets WHERE chat_id=?", (ADMIN,)
    ).fetchone()[0]
    await env.message(ADMIN, "Откройте уведомление в своём аккаунте Claude.", reply_to=prompt_id)
    assert "Откройте уведомление" in texts(env, CLIENT)[-1]
    assert env.store.for_user(CLIENT).status == "waiting_user"
    await env.message(CLIENT, "Спасибо, всё открылось")
    current = env.store.for_user(CLIENT)
    assert current.status == "in_progress"
    await env.callback(ADMIN, f"a:set:{ticket.id}:{current.version}:resolved")
    assert env.store.for_user(CLIENT).status == "in_progress"  # confirmation required
    await env.callback(ADMIN, f"a:confirm:{ticket.id}:{current.version}:resolved")
    assert env.store.for_user(CLIENT).status == "resolved"
    assert "Помощь завершена" in texts(env, CLIENT)[-1]


async def test_plain_text_requires_consent_and_ticket(env):
    await env.message(CLIENT, "Нужна помощь")
    assert env.store.for_user(CLIENT) is None
    assert "не отправлено" in texts(env, CLIENT)[-1]
    assert "c:catalog" in callbacks(last(env, CLIENT))
    assert not any("Нужна помощь" in text for text in texts(env, ADMIN))


async def test_repeated_create_does_not_duplicate(env):
    first = await create(env)
    calls = len(texts(env, ADMIN))
    second = await create(env)
    assert first.id == second.id
    assert len(texts(env, ADMIN)) == calls


async def test_operator_cannot_send_to_implicit_previous_customer(env):
    ticket = await create(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, "Случайный текст без Reply")
    assert not any("Случайный" in text for text in texts(env, CLIENT))
    assert "не отправлено" in texts(env, ADMIN)[-1]
    assert "a:home" in callbacks(last(env, ADMIN))


async def test_reply_to_notification_routes_to_correct_client(env):
    one = await create(env)
    await create(env, OTHER)
    notification = env.store.db.execute(
        "SELECT message_id FROM reply_targets WHERE chat_id=? AND ticket_id=?", (ADMIN, one.id)
    ).fetchone()[0]
    before = len(texts(env, OTHER))
    await env.message(ADMIN, "Ответ первому клиенту", reply_to=notification)
    assert "Ответ первому клиенту" in texts(env, CLIENT)[-1]
    assert len(texts(env, OTHER)) == before


async def test_edited_card_no_longer_routes_reply_to_old_ticket(env):
    ticket = await create(env)
    env.store.map_reply(ADMIN, 555, ticket.id)
    await env.callback(ADMIN, "a:list:active:0", card=555)
    assert env.store.reply_ticket(ADMIN, 555) is None
    await env.message(ADMIN, "Не должно отправиться клиенту", reply_to=555)
    assert not any("Не должно отправиться" in text for text in texts(env, CLIENT))


async def test_non_admin_cannot_access_admin_or_change_status(env):
    ticket = await create(env)
    await env.callback(OTHER, f"a:set:{ticket.id}:{ticket.version}:resolved")
    await env.message(OTHER, "/admin")
    assert env.store.ticket(ticket.id).status == "new"
    assert all("Клиент 101" not in text for text in texts(env, OTHER))


async def test_customer_cannot_read_another_ticket_or_message(env):
    ticket = await create(env)
    await env.message(CLIENT, "Приватный вопрос")
    message_id = env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchone()[0]
    for callback in (
        f"c:view:{ticket.id}",
        f"c:history:{ticket.id}:0",
        f"c:message:{ticket.id}:{message_id}",
    ):
        await env.callback(OTHER, callback)
    assert not any("Приватный вопрос" in text for text in texts(env, OTHER))


async def test_full_message_must_belong_to_the_ticket(env):
    own = await create(env)
    await create(env, OTHER)
    await env.message(OTHER, "Секрет другой заявки")
    other_message = env.store.db.execute(
        "SELECT id FROM messages WHERE body='Секрет другой заявки'"
    ).fetchone()[0]
    await env.callback(CLIENT, f"c:message:{own.id}:{other_message}")
    assert not any("Секрет другой заявки" in text for text in texts(env, CLIENT))


async def test_stale_close_does_not_overwrite_status(env):
    ticket = await create(env)
    env.store.set_status(ticket.id, ticket.version, "resolved", ADMIN)
    await env.callback(CLIENT, f"c:close:{ticket.id}:{ticket.version}")
    assert env.store.ticket(ticket.id).status == "resolved"


async def test_close_confirmation_and_new_ticket(env):
    ticket = await create(env)
    await env.callback(CLIENT, f"c:cancel:{ticket.id}:{ticket.version}")
    assert env.store.ticket(ticket.id).status == "new"
    await env.callback(CLIENT, f"c:close:{ticket.id}:{ticket.version}")
    assert env.store.ticket(ticket.id).status == "cancelled"
    await env.message(CLIENT, "Без новой заявки это не отправляется")
    assert not any("Без новой заявки" in text for text in texts(env, ADMIN))
    second = await create(env)
    assert second.id != ticket.id


async def test_duplicate_customer_update_is_saved_once(env):
    ticket = await create(env)
    await env.message(CLIENT, "Один вопрос", message_id=900)
    count = len(texts(env, ADMIN))
    await env.message(CLIENT, "Один вопрос", message_id=900)
    rows, _ = env.store.messages(ticket.id)
    assert sum(row["body"] == "Один вопрос" for row in rows) == 1
    assert len(texts(env, ADMIN)) == count


async def test_duplicate_operator_update_never_resends(env):
    ticket = await create(env)
    env.store.map_reply(ADMIN, 777, ticket.id)
    await env.message(ADMIN, "Один ответ", reply_to=777, message_id=900)
    count = len(texts(env, CLIENT))
    await env.message(ADMIN, "Один ответ", reply_to=777, message_id=900)
    assert len(texts(env, CLIENT)) == count


async def test_uncertain_delivery_persists_without_retry_or_false_receipt(env):
    ticket = await create(env)
    env.store.map_reply(ADMIN, 777, ticket.id)
    env.request.fail_chat, env.request.fail_error = CLIENT, TimedOut()
    await env.message(ADMIN, "Ответ при обрыве сети", reply_to=777)
    row = env.store.db.execute("SELECT delivery FROM messages WHERE role='operator'").fetchone()
    assert row["delivery"] == "uncertain"
    assert "могло дойти" in texts(env, ADMIN)[-1]
    assert "Автоматического повтора" in texts(env, ADMIN)[-1]
    assert env.store.ticket(ticket.id).status == "new"


async def test_blocked_customer_is_not_marked_delivered(env):
    ticket = await create(env)
    env.store.map_reply(ADMIN, 777, ticket.id)
    env.request.fail_chat, env.request.fail_error = CLIENT, Forbidden("Blocked")
    await env.message(ADMIN, "Недоставленный ответ", reply_to=777)
    assert (
        env.store.db.execute("SELECT delivery FROM messages WHERE role='operator'").fetchone()[0] == "failed"
    )
    assert "не удалось" in texts(env, ADMIN)[-1]


async def test_customer_text_is_saved_if_admin_unavailable(env):
    ticket = await create(env)
    env.request.fail_chat, env.request.fail_error = ADMIN, Forbidden("Not started")
    await env.message(CLIENT, "Вопрос останется в списке")
    row = env.store.db.execute("SELECT body,delivery FROM messages WHERE role='user'").fetchone()
    assert row["body"] == "Вопрос останется в списке"
    assert row["delivery"] == "stored"
    assert env.store.ticket(ticket.id).unread == 1
    assert f"№{ticket.id:04d}" in texts(env, CLIENT)[-1]
    assert f"c:view:{ticket.id}" in callbacks(last(env, CLIENT))


async def test_documents_are_not_downloaded_relayed_or_saved(env):
    await create(env)
    count = len(texts(env, ADMIN))
    await env.message(CLIENT, photo=True)
    assert len(texts(env, ADMIN)) == count
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchall()
    assert not any(method == "getFile" for method, _ in env.request.calls)


async def test_edited_messages_do_not_replace_or_duplicate_ticket_text(env):
    await create(env)
    await env.message(CLIENT, "Исходный вопрос", message_id=900)
    await env.message(CLIENT, "Изменённый вопрос", message_id=900, edited=True)
    assert (
        env.store.db.execute("SELECT body FROM messages WHERE role='user'").fetchone()[0] == "Исходный вопрос"
    )


async def test_html_is_escaped_and_long_messages_have_full_view(env):
    ticket = await create(env)
    body = "<b>не разметка</b> & " + "я" * 1500
    await env.message(CLIENT, body)
    assert "&lt;b&gt;" in texts(env, ADMIN)[-1]
    await env.callback(CLIENT, f"c:history:{ticket.id}:0")
    markup = env.request.calls[-1][1]["reply_markup"]
    assert any(
        ":message:" in button.get("callback_data", "") for row in markup["inline_keyboard"] for button in row
    )
    mid = env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchone()[0]
    await env.callback(CLIENT, f"c:message:{ticket.id}:{mid}")
    assert "я" * 1500 in texts(env, CLIENT)[-1]


async def test_oversized_text_is_not_silently_truncated(env):
    await create(env)
    await env.message(CLIENT, "a" * 2401)
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='user'").fetchall()
    assert "Разделите" in texts(env, CLIENT)[-1]


async def test_group_messages_never_create_private_tickets(env):
    await env.callback(CLIENT, "c:create", chat_type="group")
    await env.message(CLIENT, "Приватный вопрос", chat_type="group")
    assert env.store.for_user(CLIENT) is None


async def test_pagination_keeps_all_tickets_accessible(env):
    for uid in range(200, 211):
        env.store.remember_user(uid, uid, f"Клиент {uid}", None)
        env.store.create_ticket(uid)
    await env.callback(ADMIN, "a:list:active:0")
    markup = env.request.calls[-1][1]["reply_markup"]
    assert any(
        button.get("callback_data") == "a:list:active:8"
        for row in markup["inline_keyboard"]
        for button in row
    )
    await env.callback(ADMIN, "a:list:active:8")
    markup = env.request.calls[-1][1]["reply_markup"]
    assert (
        sum(
            button.get("callback_data", "").startswith("a:view:")
            for row in markup["inline_keyboard"]
            for button in row
        )
        == 3
    )


async def test_live_setup_refuses_to_replace_existing_webhook(env):
    env.request.webhook = True
    try:
        await env.app.post_init(env.app)
        assert False, "Existing integration must not be replaced"
    except RuntimeError:
        pass
    assert not any(method == "deleteWebhook" for method, _ in env.request.calls)


async def test_emoji_history_fits_telegram_limit_and_opens_full_message(env):
    ticket = await create(env)
    for number in range(4):
        await env.message(CLIENT, "🙂" * 500, message_id=800 + number)
    await env.callback(CLIENT, f"c:history:{ticket.id}:0")
    from verifydesk.ui import text_units

    assert text_units(texts(env, CLIENT)[-1]) < 4096
    markup = env.request.calls[-1][1]["reply_markup"]
    assert (
        sum(
            ":message:" in button.get("callback_data", "")
            for row in markup["inline_keyboard"]
            for button in row
        )
        == 4
    )


async def test_admin_start_opens_operator_cabinet_and_sets_private_commands(env):
    await env.message(ADMIN, "/start")
    assert "Кабинет оператора" in texts(env, ADMIN)[-1]
    command_calls = [params for method, params in env.request.calls if method == "setMyCommands"]
    assert command_calls[-1]["scope"]["chat_id"] == ADMIN
    assert command_calls[-1]["commands"][0]["command"] == "admin"
