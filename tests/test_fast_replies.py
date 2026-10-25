"""Fast operator queue and compact client paths, without live Telegram calls."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from telegram.error import Forbidden, TimedOut

from verifydesk import ui
from verifydesk.store import STATUS_NAMES

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import buttons, callbacks, last, order, sent


SECOND_ADMIN = 9002


def reply_target(env, uid=ADMIN):
    row = env.store.db.execute(
        "SELECT message_id,ticket_id FROM reply_targets WHERE chat_id=? ORDER BY message_id DESC LIMIT 1",
        (uid,),
    ).fetchone()
    assert row is not None
    return row["message_id"], row["ticket_id"]


def allow_second_operator(env):
    desk = env.app.handlers[0][0].callback.__self__
    desk.config = replace(desk.config, admin_ids=(ADMIN, SECOND_ADMIN))


async def test_next_opens_reply_immediately_and_success_updates_both_sides(env):
    ticket = await order(env)
    await env.message(CLIENT, "Ошибка на последнем шаге")
    await env.message(ADMIN, "/next")
    prompt = last(env, ADMIN)
    assert prompt["reply_markup"]["force_reply"] is True
    assert f"{ticket.id:04d}" in prompt["text"]
    assert "Клиент 101" in prompt["text"] and "Ошибка на последнем шаге" in prompt["text"]
    prompt_id, target_id = reply_target(env)
    assert target_id == ticket.id
    assert env.store.claim_owner(ticket.id) == ADMIN

    await env.message(ADMIN, "Уточните текст ошибки", reply_to=prompt_id)
    current = env.store.ticket(ticket.id)
    assert current.status == "waiting_user"
    assert env.store.claim_owner(ticket.id) is None
    assert "Уточните текст ошибки" in last(env, CLIENT)["text"]
    assert STATUS_NAMES["waiting_user"] in last(env, CLIENT)["text"]
    assert ui.admin_status("waiting_user") in last(env, ADMIN)["text"]
    assert f"a:next:{ticket.id}" in callbacks(last(env, ADMIN))

    await env.message(CLIENT, "Теперь вижу другой текст")
    assert env.store.ticket(ticket.id).status == "in_progress"
    assert env.store.queue_count() == 1


async def test_reply_to_receipt_can_continue_without_opening_ticket_again(env):
    ticket = await order(env)
    await env.callback(ADMIN, "a:next")
    prompt_id, _ = reply_target(env)
    await env.message(ADMIN, "Первый ответ", reply_to=prompt_id)
    receipt_id, target_id = reply_target(env)
    assert receipt_id != prompt_id and target_id == ticket.id

    await env.message(ADMIN, "И ещё одно уточнение", reply_to=receipt_id)
    assert "И ещё одно уточнение" in last(env, CLIENT)["text"]
    assert env.store.ticket(ticket.id).status == "waiting_user"
    rows = env.store.db.execute(
        "SELECT body,delivery FROM messages WHERE ticket_id=? AND role='operator' ORDER BY id", (ticket.id,)
    ).fetchall()
    assert [tuple(row) for row in rows] == [("Первый ответ", "delivered"), ("И ещё одно уточнение", "delivered")]


async def test_new_customer_notification_cannot_retarget_open_queue_reply(env):
    first = await order(env)
    await env.callback(ADMIN, "a:next")
    first_prompt, _ = reply_target(env)
    other = await order(env, uid=OTHER)
    await env.message(OTHER, "Второй клиент пишет во время ответа")
    before_other = len(sent(env, OTHER))

    await env.message(ADMIN, "Ответ именно первому", reply_to=first_prompt)
    assert "Ответ именно первому" in last(env, CLIENT)["text"]
    assert len(sent(env, OTHER)) == before_other
    assert env.store.ticket(first.id).status == "waiting_user"
    assert env.store.ticket(other.id).status == "new"


async def test_skip_releases_current_and_opens_next_eligible_ticket(env):
    first = await order(env)
    second = await order(env, uid=OTHER)
    await env.callback(ADMIN, "a:next")
    assert reply_target(env)[1] == first.id
    await env.callback(ADMIN, f"a:next:{first.id}")
    assert reply_target(env)[1] == second.id
    assert last(env, ADMIN)["reply_markup"]["force_reply"] is True
    assert env.store.claim_owner(first.id) is None
    assert env.store.claim_owner(second.id) == ADMIN
    # Repeated /next resumes this operator's current work instead of silently changing recipient.
    await env.message(ADMIN, "/next")
    assert reply_target(env)[1] == second.id


async def test_empty_queue_excludes_clients_whose_turn_it_is(env):
    ticket = await order(env)
    env.store.set_status(ticket.id, ticket.version, "waiting_user", ADMIN)
    before_messages = env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    await env.callback(ADMIN, "a:next")
    screen = last(env, ADMIN)
    assert not screen.get("reply_markup", {}).get("force_reply")
    assert env.store.queue_count() == 0
    assert env.store.claim_owner(ticket.id) is None
    assert env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before_messages
    assert callbacks(screen)


@pytest.mark.parametrize("entry", ["/next", "a:next", "a:list:queue:0"])
async def test_queue_does_not_expose_client_data_to_nonoperators(env, entry):
    ticket = await order(env)
    await env.message(CLIENT, "Закрытая переписка первого клиента")
    before_messages = env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if entry.startswith("/"):
        await env.message(OTHER, entry)
    else:
        await env.callback(OTHER, entry)
    assert "Закрытая переписка" not in last(env, OTHER)["text"]
    assert not last(env, OTHER).get("reply_markup", {}).get("force_reply")
    assert env.store.claim_owner(ticket.id) is None
    assert env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before_messages


@pytest.mark.parametrize("entry", ["/next", "a:next"])
async def test_queue_does_not_send_operator_reply_prompt_in_customer_mode(env, entry):
    ticket = await order(env)
    await env.message(ADMIN, "/client")
    if entry.startswith("/"):
        await env.message(ADMIN, entry)
    else:
        await env.callback(ADMIN, entry)
    assert env.store.operator_mode(ADMIN) == "client"
    assert env.store.claim_owner(ticket.id) is None
    assert not last(env, ADMIN).get("reply_markup", {}).get("force_reply")
    assert "a:mode:admin" in callbacks(last(env, ADMIN))


async def test_two_operators_cannot_reply_to_the_same_claimed_request(env):
    allow_second_operator(env)
    ticket = await order(env)
    second_notification = reply_target(env, SECOND_ADMIN)[0]
    await env.callback(ADMIN, "a:next")
    assert env.store.claim_owner(ticket.id) == ADMIN
    before_client = len(sent(env, CLIENT))
    await env.callback(SECOND_ADMIN, f"a:reply:{ticket.id}")
    assert not last(env, SECOND_ADMIN).get("reply_markup", {}).get("force_reply")
    await env.message(SECOND_ADMIN, "Конкурирующий ответ", reply_to=second_notification)
    assert len(sent(env, CLIENT)) == before_client
    assert env.store.claim_owner(ticket.id) == ADMIN
    assert env.store.db.execute("SELECT COUNT(*) FROM messages WHERE body='Конкурирующий ответ'").fetchone()[0] == 0


async def test_old_notification_cannot_send_a_second_operators_stale_reply(env):
    allow_second_operator(env)
    ticket = await order(env)
    first_notification = reply_target(env, ADMIN)[0]
    second_notification = reply_target(env, SECOND_ADMIN)[0]

    await env.message(ADMIN, "Первый оператор уже ответил", reply_to=first_notification)
    assert env.store.ticket(ticket.id).status == "waiting_user"
    before_client = len(sent(env, CLIENT))
    await env.message(SECOND_ADMIN, "Устаревший параллельный ответ", reply_to=second_notification)
    assert len(sent(env, CLIENT)) == before_client
    assert env.store.db.execute(
        "SELECT COUNT(*) FROM messages WHERE body='Устаревший параллельный ответ'"
    ).fetchone()[0] == 0
    assert f"a:reply:{ticket.id}" in callbacks(last(env, SECOND_ADMIN))
    assert env.store.claim_owner(ticket.id) is None

    # Deliberately reopen the current request to see fresh context before following up.
    await env.callback(SECOND_ADMIN, f"a:reply:{ticket.id}")
    assert last(env, SECOND_ADMIN)["reply_markup"]["force_reply"] is True
    fresh_prompt, target = reply_target(env, SECOND_ADMIN)
    assert fresh_prompt != second_notification and target == ticket.id
    await env.message(SECOND_ADMIN, "Осознанное дополнение после просмотра", reply_to=fresh_prompt)
    assert "Осознанное дополнение после просмотра" in last(env, CLIENT)["text"]
    row = env.store.db.execute(
        "SELECT actor_id,delivery FROM messages WHERE body='Осознанное дополнение после просмотра'"
    ).fetchone()
    assert tuple(row) == (SECOND_ADMIN, "delivered")
    assert env.store.ticket(ticket.id).status == "waiting_user"


@pytest.mark.parametrize("error,state", [(TimedOut(), "uncertain"), (Forbidden("Blocked"), "failed")])
async def test_failed_delivery_keeps_operator_turn_and_claim(env, error, state):
    ticket = await order(env)
    await env.callback(ADMIN, "a:next")
    prompt_id, _ = reply_target(env)
    env.request.fail_chat, env.request.fail_error = CLIENT, error
    await env.message(ADMIN, "Ответ с проблемой доставки", reply_to=prompt_id)
    assert env.store.ticket(ticket.id).status == "new"
    assert env.store.claim_owner(ticket.id) == ADMIN
    rows = env.store.db.execute("SELECT delivery FROM messages WHERE role='operator'").fetchall()
    assert [row["delivery"] for row in rows] == [state]
    attempts = [params for method, params in env.request.calls if method == "sendMessage" and params["chat_id"] == CLIENT and "Ответ с проблемой доставки" in params["text"]]
    assert len(attempts) == 1
    assert ui.admin_status("waiting_user") not in last(env, ADMIN)["text"]


async def test_client_ticket_is_compact_and_extra_actions_live_in_details(env):
    ticket = await order(env)
    screen = last(env, CLIENT)
    data = callbacks(screen)
    assert len(buttons(screen)) <= 3
    assert len(screen["text"]) <= 450
    assert f"c:details:{ticket.id}" in data
    assert not any(value.startswith(("c:pay:", "c:cancel:", "c:write:")) for value in data)
    await env.callback(CLIENT, f"c:details:{ticket.id}")
    assert f"c:pay:{ticket.id}" in callbacks(last(env, CLIENT))
    assert any(value.startswith(f"c:cancel:{ticket.id}:") for value in callbacks(last(env, CLIENT)))
    assert f"c:view:{ticket.id}" in callbacks(last(env, CLIENT))
    # A customer cannot use another person's details screen to read their request.
    await env.callback(OTHER, f"c:details:{ticket.id}")
    assert "Клиент 101" not in last(env, OTHER)["text"]
    assert f"c:pay:{ticket.id}" not in callbacks(last(env, OTHER))


async def test_thousand_request_backlog_batches_notifications_without_losing_messages(env, monkeypatch):
    # Populate only the isolated local database; this is not a live Telegram load test.
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr("verifydesk.bot.time", SimpleNamespace(monotonic=lambda: clock.now))
    for uid in range(10000, 11000):
        env.store.remember_user(uid, uid, f"Клиент {uid}", None)
        env.store.create_ticket(uid, "claude", "armenia", "35.00")
    assert env.store.queue_count() == 1000
    for index in range(5):
        await env.message(10000 + index, f"Уточнение в очереди {index}")

    admin_messages = sent(env, ADMIN)
    assert len(admin_messages) == 1
    assert "очеред" in admin_messages[0]["text"].lower()
    assert "a:next" in callbacks(admin_messages[0])
    assert "a:list:queue:0" in callbacks(admin_messages[0])
    # A digest has no implicit recipient; replying to it must not address one of the 1000 clients.
    assert env.store.db.execute("SELECT COUNT(*) FROM reply_targets WHERE chat_id=?", (ADMIN,)).fetchone()[0] == 0
    rows = env.store.db.execute("SELECT body,delivery FROM messages WHERE role='user' ORDER BY id").fetchall()
    assert [tuple(row) for row in rows] == [(f"Уточнение в очереди {index}", "stored") for index in range(5)]
    assert env.store.queue_count() == 1000
    assert all(env.store.for_user(10000 + index).unread == 1 for index in range(5))
    clock.now += 16
    await env.message(10005, "Новое сообщение после интервала")
    assert len(sent(env, ADMIN)) == 2
    assert env.store.db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0] == 6


async def test_blocked_operator_digest_is_throttled_and_user_messages_remain_stored(env, monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr("verifydesk.bot.time", SimpleNamespace(monotonic=lambda: clock.now))
    for uid in range(20000, 21000):
        env.store.remember_user(uid, uid, f"Клиент {uid}", None)
        env.store.create_ticket(uid, "claude", "armenia", "35.00")
    env.request.fail_chat, env.request.fail_error = ADMIN, Forbidden("Blocked")

    for index in range(3):
        await env.message(20000 + index, f"Сообщение при недоступном операторе {index}")
    attempts = [params for method, params in env.request.calls if method == "sendMessage" and params["chat_id"] == ADMIN]
    assert len(attempts) == 1
    assert all(row["delivery"] == "stored" for row in env.store.db.execute("SELECT delivery FROM messages WHERE role='user'"))
    assert env.store.queue_count() == 1000

    clock.now += 16
    await env.message(20003, "Ещё сообщение после интервала")
    attempts = [params for method, params in env.request.calls if method == "sendMessage" and params["chat_id"] == ADMIN]
    assert len(attempts) == 2
    assert env.store.db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0] == 4
    assert env.store.db.execute("SELECT COUNT(*) FROM reply_targets WHERE chat_id=?", (ADMIN,)).fetchone()[0] == 0
