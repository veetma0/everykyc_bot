"""Customer-selected USDT networks and the separate operator payment review."""

import pytest

from verifydesk import catalog, rich, ui
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .test_journey_audit import press
from .test_order_payment_flow import request_payment
from .test_upgrade import buttons, callbacks, last, order


def assert_compact_rows(env, uid=CLIENT):
    for row in last(env, uid)["reply_markup"]["inline_keyboard"]:
        widths = [rich._button_width(ui.Button.de_json(button, env.app.bot)) for button in row]
        assert sum(widths) + 8 * (len(row) - 1) <= 199, [button["text"] for button in row]


async def test_customer_can_choose_reopen_and_change_payment_network(env, tmp_path):
    ticket = await request_payment(env)
    pay = f"c:pay:{ticket.id}"
    back = f"c:view:{ticket.id}"
    assert any(b["text"] == "Выбрать сеть" and b["callback_data"] == pay for b in buttons(last(env, CLIENT)))
    await press(env, CLIENT, pay)
    await press(env, CLIENT, f"c:networks:{ticket.id}:usdt0:0")
    await press(env, CLIENT, f"c:networks:{ticket.id}:usdt0:8")
    await press(env, CLIENT, f"c:network:{ticket.id}:usdt0_optimism")
    assert "Optimism" in last(env, CLIENT)["text"]
    assert_compact_rows(env)
    await press(env, CLIENT, back)
    assert "Optimism" in last(env, CLIENT)["text"]
    assert any(b["text"] == "Сменить сеть" and b["callback_data"] == pay for b in buttons(last(env, CLIENT)))
    assert_compact_rows(env)
    reopened = Store(tmp_path / "desk.sqlite3")
    try:
        previous = reopened.ticket(ticket.id)
        assert previous.payment_network == "usdt0_optimism"
        assert previous.payment_stage == "awaiting_payment"
        assert previous.price_usd == ticket.price_usd
    finally:
        reopened.close()

    await press(env, CLIENT, pay)
    assert "Optimism" in last(env, CLIENT)["text"]
    await press(env, CLIENT, f"c:network:{ticket.id}:usdt_tron")
    assert env.store.ticket(ticket.id).payment_network == "usdt_tron"
    await env.callback(ADMIN, f"a:view:{ticket.id}")
    assert "TRC20" in last(env, ADMIN)["text"]
    await press(env, ADMIN, f"a:details:{ticket.id}")
    assert "TRC20" in last(env, ADMIN)["text"]
    assert "Optimism" not in last(env, ADMIN)["text"]

    await press(env, CLIENT, back)
    await env.proof(CLIENT, photo=True)
    review = env.store.ticket(ticket.id)
    assert review.payment_stage == "review" and review.status == "new"
    await env.callback(CLIENT, f"c:network:{ticket.id}:usdt_ton")
    assert env.store.ticket(ticket.id).payment_network == "usdt_tron"
    await press(env, ADMIN, f"a:confirm_payment:{ticket.id}:{review.version}")
    confirmed = env.store.ticket(ticket.id)
    assert confirmed.payment_stage == "confirmed" and confirmed.status == "in_progress"
    assert confirmed.payment_network == "usdt_tron"
    assert not any(method in {"sendInvoice", "createInvoiceLink"} for method, _ in env.request.calls)


async def test_all_networks_are_reachable_from_compact_selector_pages(env):
    ticket = await request_payment(env)
    pay = f"c:pay:{ticket.id}"
    assert_compact_rows(env)
    await press(env, CLIENT, pay)
    assert_compact_rows(env)
    found = set()
    for group in catalog.NETWORK_GROUPS:
        base = f"c:networks:{ticket.id}:{group}:"
        await press(env, CLIENT, base + "0")
        offset = 0
        earlier_page = None
        while True:
            assert_compact_rows(env)
            options = callbacks(last(env, CLIENT))
            if earlier_page:
                assert earlier_page in options
            prefix = f"c:network:{ticket.id}:"
            found.update(value.removeprefix(prefix) for value in options if value.startswith(prefix))
            later = [value for value in options if value.startswith(base)
                     and int(value.removeprefix(base)) > offset]
            if not later:
                break
            assert len(later) == 1
            earlier_page = base + str(offset)
            offset = int(later[0].removeprefix(base))
            await press(env, CLIENT, later[0])
        await press(env, CLIENT, pay)
    assert found == set(catalog.NETWORK_BY_CODE)
    assert env.store.ticket(ticket.id).payment_network is None


async def test_customer_can_clear_the_selection_and_ignore_a_repeated_clear(env):
    ticket = await request_payment(env)
    pay = f"c:pay:{ticket.id}"
    clear = f"c:network_clear:{ticket.id}"
    await press(env, CLIENT, pay)
    assert clear not in callbacks(last(env, CLIENT))
    await press(env, CLIENT, f"c:network:{ticket.id}:usdt_ton")
    await press(env, CLIENT, pay)
    await press(env, CLIENT, clear)
    assert env.store.ticket(ticket.id) == ticket
    await env.callback(CLIENT, clear)
    assert env.store.ticket(ticket.id) == ticket
    await env.callback(CLIENT, f"c:view:{ticket.id}")
    await press(env, CLIENT, pay)
    assert clear not in callbacks(last(env, CLIENT))


@pytest.mark.parametrize("phase", ["new", "foreign", "closed", "rejected", "preview", "unknown"])
async def test_unavailable_network_actions_leave_the_order_unchanged(env, phase):
    owner = ADMIN if phase == "preview" else CLIENT
    if owner == ADMIN:
        await env.message(owner, "/client")
    ticket = await order(env, uid=owner)
    if phase != "new":
        ticket = env.store.request_payment(ticket.id, ticket.version, ADMIN)
        ticket = env.store.set_payment_network(ticket.id, owner, "usdt_ton")
    if phase == "closed":
        env.store.set_status(ticket.id, ticket.version, "cancelled", owner)
    elif phase == "rejected":
        await env.proof(owner, photo=True)
        review = env.store.ticket(ticket.id)
        env.store.reject_payment(ticket.id, review.version, ADMIN)

    def stored_order():
        return env.store.db.execute("SELECT * FROM tickets WHERE id=?", (ticket.id,)).fetchone()

    snapshot = stored_order()
    uid = OTHER if phase == "foreign" else owner
    scope = "p" if phase == "preview" else "c"
    network = "missing" if phase == "unknown" else "usdt_tron"
    await env.callback(uid, f"{scope}:network:{ticket.id}:{network}")
    assert stored_order() == snapshot
    if phase != "unknown":
        await env.callback(uid, f"{scope}:network_clear:{ticket.id}")
        assert stored_order() == snapshot
