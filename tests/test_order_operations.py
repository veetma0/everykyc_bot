"""Cancellation boundaries, manager tools and a bounded thousand-order queue."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from verifydesk import catalog, screens, ui
from verifydesk.store import StaleTicket, Store, can_customer_cancel

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last, order, sent


async def awaiting_payment(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    return env.store.ticket(ticket.id)


@pytest.mark.parametrize("stage", ["new", "awaiting_payment"])
async def test_customer_can_cancel_unpaid_order_from_visible_buttons(env, stage):
    ticket = await (awaiting_payment(env) if stage == "awaiting_payment" else order(env))
    cancel = f"c:cancel:{ticket.id}:{ticket.version}"
    assert cancel in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, cancel)
    assert env.store.ticket(ticket.id).status == "new"
    assert f"c:close:{ticket.id}:{ticket.version}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:close:{ticket.id}:{ticket.version}")
    assert env.store.ticket(ticket.id).status == "cancelled"


@pytest.mark.parametrize("stage", ["review", "rejected", "confirmed"])
async def test_customer_cannot_cancel_after_proof_even_with_fresh_forged_button(env, stage):
    ticket = await awaiting_payment(env)
    await env.proof(CLIENT, "https://example.org/payment/receipt")
    current = env.store.ticket(ticket.id)
    if stage != "review":
        verb = "reject_payment" if stage == "rejected" else "confirm_payment"
        await env.callback(ADMIN, f"a:{verb}:{ticket.id}:{current.version}")
    current = env.store.ticket(ticket.id)
    assert current.has_payment_proof and not can_customer_cancel(current)
    assert not any(":cancel:" in x for x in callbacks(last(env, CLIENT)))
    await env.callback(CLIENT, f"c:cancel:{ticket.id}:{current.version}")
    assert not any(":close:" in x for x in callbacks(last(env, CLIENT)))
    await env.callback(CLIENT, f"c:close:{ticket.id}:{current.version}")
    assert env.store.ticket(ticket.id).status == current.status
    assert env.store.ticket(ticket.id).version == current.version


async def test_cancellation_old_version_cannot_overwrite_submitted_proof(env):
    ticket = await awaiting_payment(env)
    await env.callback(CLIENT, f"c:cancel:{ticket.id}:{ticket.version}")
    await env.proof(CLIENT, photo=True)
    await env.callback(CLIENT, f"c:close:{ticket.id}:{ticket.version}")
    assert env.store.ticket(ticket.id).payment_stage == "review"
    assert len(env.store.payment_proofs(ticket.id)) == 1


def create(store, uid):
    store.remember_user(uid, uid, f"Client {uid}", None)
    return store.create_ticket(uid, "claude", "armenia", "35.00")[0]


def request(store, ticket):
    return store.request_payment(ticket.id, ticket.version, 42)


def review(store, ticket):
    ticket = request(store, ticket)
    store.submit_payment_proof(ticket.id, "https://example.org/receipt", ticket.user_id, ticket.chat_id, 1)
    return store.ticket(ticket.id)


def test_cancel_and_proof_race_has_one_winner(tmp_path):
    path = tmp_path / "race.sqlite3"
    seed = Store(path)
    ticket = request(seed, create(seed, CLIENT))
    seed.close()
    barrier = Barrier(2)

    def act(kind):
        db = Store(path)
        try:
            barrier.wait(timeout=5)
            try:
                if kind == "cancel":
                    db.set_status(ticket.id, ticket.version, "cancelled", CLIENT, customer_cancel=True)
                else:
                    db.submit_payment_proof(ticket.id, "https://example.org/receipt", CLIENT, CLIENT, 1)
                return True
            except StaleTicket:
                return False
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(act, ["cancel", "proof"]))
    assert sorted(winners) == [False, True]
    result = Store(path)
    try:
        latest = result.ticket(ticket.id)
        assert (latest.status, latest.payment_stage) in {("cancelled", "awaiting_payment"), ("new", "review")}
        assert bool(result.payment_proofs(ticket.id)) == (latest.payment_stage == "review")
    finally:
        result.close()


def test_rejected_proof_keeps_customer_cancellation_locked_after_restart(tmp_path):
    path = tmp_path / "orders.sqlite3"
    db = Store(path)
    ticket = review(db, create(db, CLIENT))
    db.reject_payment(ticket.id, ticket.version, 42)
    db.close()
    reopened = Store(path)
    try:
        latest = reopened.ticket(ticket.id)
        assert latest.payment_stage == "awaiting_payment" and latest.has_payment_proof
        with pytest.raises(StaleTicket):
            reopened.set_status(latest.id, latest.version, "cancelled", CLIENT, customer_cancel=True)
        assert reopened.set_status(latest.id, latest.version, "cancelled", 42).status == "cancelled"
    finally:
        reopened.close()


def test_thousand_orders_prioritize_receipts_and_work_with_distinct_managers(tmp_path):
    path = tmp_path / "thousand.sqlite3"
    db = Store(path)
    tickets = [create(db, uid) for uid in range(2000, 3000)]
    for ticket in tickets[700:800]:
        request(db, ticket)
    for ticket in tickets[800:900]:
        current = review(db, ticket)
        db.confirm_payment(current.id, current.version, 42)
    for ticket in tickets[900:]:
        review(db, ticket)
    assert db.stage_counts() == {"new": 700, "payment": 100, "review": 100, "work": 100}
    assert db.queue_count() == 900
    for stage, expected in (("new", 700), ("payment", 100), ("review", 100), ("work", 100)):
        page, total = db.page(stage, 0)
        assert total == expected and len(page) == 8
    page, total = db.queue_page(42)
    assert total == 900 and [t.id for t in page] == [t.id for t in tickets[900:908]]
    page, total = db.queue_page(42, 100)
    assert [t.id for t in page] == [t.id for t in tickets[800:808]]
    db.close()
    barrier = Barrier(10)

    def claim(manager):
        instance = Store(path)
        try:
            barrier.wait(timeout=10)
            claimed = instance.claim_next(manager)
            assert claimed.payment_stage == "review"
            assert instance.claim_next(manager).id == claimed.id
            return claimed.id
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        assigned = list(pool.map(claim, range(100, 110)))
    assert len(set(assigned)) == 10


async def test_manager_filters_and_search_reach_the_right_order_without_sending_messages(env):
    first = await awaiting_payment(env)
    second = await order(env, uid=OTHER)
    await env.proof(CLIENT, "https://example.org/receipt")
    await env.message(ADMIN, "/admin")
    assert "a:find" in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, "a:list:active:0")
    assert all(f"a:list:{x}:0" in callbacks(last(env, ADMIN)) for x in ("new", "review", "work", "payment"))
    await env.callback(ADMIN, "a:list:review:0")
    assert f"a:view:{first.id}" in callbacks(last(env, ADMIN))
    assert f"a:view:{second.id}" not in callbacks(last(env, ADMIN))
    before = len(sent(env, CLIENT))
    await env.callback(ADMIN, "a:find")
    await env.message(ADMIN, "не номер")
    assert "Введите другой номер" in last(env, ADMIN)["text"]
    await env.message(ADMIN, f"№{first.id:04d}")
    assert f"№{first.id:04d}" in last(env, ADMIN)["text"]
    assert len(sent(env, CLIENT)) == before
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


@pytest.mark.parametrize("entry", ["/order 1", "a:find", "a:list:review:0", "a:list:work:0"])
async def test_manager_search_and_filters_are_private(env, entry):
    ticket = await order(env)
    if entry.startswith("/"):
        await env.message(OTHER, entry)
    else:
        await env.callback(OTHER, entry)
    assert f"№{ticket.id:04d}" not in last(env, OTHER)["text"]
    assert "Клиент 101" not in last(env, OTHER)["text"]


async def test_search_exit_cannot_leave_a_hidden_reply_recipient(env):
    ticket = await order(env)
    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.callback(ADMIN, "a:find")
    assert env.store.focused_ticket(ADMIN) is None
    await env.callback(ADMIN, "a:home")
    await env.message(ADMIN, str(ticket.id))
    assert env.store.draft(ADMIN) is None
    assert not env.store.db.execute("SELECT id FROM messages WHERE role='operator'").fetchall()


async def test_order_list_marks_a_live_claim_and_removes_mark_after_expiry(env, monkeypatch):
    ticket = await order(env)
    assert env.store.claim_ticket(ticket.id, 9002)
    await env.callback(ADMIN, "a:list:active:0")
    items = last(env, ADMIN)["reply_markup"]["inline_keyboard"]
    button = next(b for row in items for b in row if b.get("callback_data") == f"a:view:{ticket.id}")
    assert button["text"].startswith("🔒")
    monkeypatch.setattr("verifydesk.store.time.time", lambda: 10**12)
    await env.callback(ADMIN, "a:list:active:0")
    items = last(env, ADMIN)["reply_markup"]["inline_keyboard"]
    button = next(b for row in items for b in row if b.get("callback_data") == f"a:view:{ticket.id}")
    assert not button["text"].startswith("🔒")


@pytest.mark.parametrize("url", [
    "https://inquiry.withpersona.com/verify?inquiry-id=PRIVATE",
    "https://WITHPERSONA.com./anything?secret=PRIVATE",
    "https://claude.ai/verify/PRIVATE",
    "https://claude.com/identity-verification/PRIVATE",
])
@pytest.mark.parametrize("paid", [False, True])
async def test_verification_links_are_not_saved_or_forwarded(env, url, paid):
    ticket = await awaiting_payment(env)
    if paid:
        await env.proof(CLIENT, "https://example.org/receipt")
        current = env.store.ticket(ticket.id)
        await env.callback(ADMIN, f"a:confirm_payment:{ticket.id}:{current.version}")
    before = len(sent(env, ADMIN))
    await env.message(CLIENT, url)
    assert "Ссылку проверки не отправляйте" in last(env, CLIENT)["text"]
    assert env.store.draft(CLIENT) is None
    assert len(sent(env, ADMIN)) == before
    assert not env.store.db.execute("SELECT id FROM messages WHERE body LIKE '%PRIVATE%'").fetchall()


async def test_hidden_verification_link_in_entity_or_image_caption_is_not_forwarded(env):
    await awaiting_payment(env)
    await env.message(CLIENT, "Посмотрите", entities=[{
        "type": "text_link", "offset": 0, "length": 10, "url": "https://inquiry.withpersona.com/PRIVATE",
    }])
    assert env.store.draft(CLIENT) is None
    await env.message(CLIENT, photo=True, caption="https://claude.ai/verify/PRIVATE")
    assert env.store.draft(CLIENT) is None
    assert not any(name == "sendPhoto" for name, _ in env.request.calls)


def test_offer_separates_support_from_subscription_and_instructions_keep_verification_private():
    text, keyboard = screens.offer_card(catalog.offer("claude", "standard"))
    assert "Гео уточняйте у оператора" in text and "$45" in text
    assert "<b>Подписка не входит в стоимость.</b>" in text
    assert "Подписку Claude вы оплачиваете самостоятельно" in text
    assert len([b for row in keyboard.inline_keyboard for b in row]) == 2
    assert "самостоятельно" in ui.INSTRUCTIONS
    assert "отправляйте" in ui.INSTRUCTIONS and "Ссылку KYC" in ui.INSTRUCTIONS
    assert "Фамили" not in ui.INSTRUCTIONS
