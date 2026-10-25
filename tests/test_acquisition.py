"""Recognized start tags measure first-touch starts, never search ranking or money."""

from pathlib import Path
import sqlite3

import pytest

from verifydesk import acquisition
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last, order


def attribution(env, uid):
    return env.store.db.execute("SELECT * FROM user_acquisition WHERE user_id=?", (uid,)).fetchone()


def ticket_source(store, ticket_id):
    row = store.db.execute(
        "SELECT source_code FROM ticket_acquisition WHERE ticket_id=?", (ticket_id,)
    ).fetchone()
    return row[0] if row else None


async def test_first_recognized_source_is_immutable_and_repeat_starts_are_unique(env):
    await env.message(CLIENT, "/start src_tg_post")
    first = dict(attribution(env, CLIENT))
    for text in ("/start src_tg_post", "/start src_partner", "/start"):
        await env.message(CLIENT, text)
    assert dict(attribution(env, CLIENT)) == first
    assert env.store.source_summary() == [
        {"source_code": "src_tg_post", "started_users": 1, "requested_users": 0, "tickets": 0}
    ]
    assert env.store.for_user(CLIENT) is None
    assert "c:service:claude" in callbacks(last(env, CLIENT))


@pytest.mark.parametrize("payload", ["", "unknown", "SRC_TG_POST", "src_tg_post extra", "src_tg_post?token=secret", "x" * 65])
async def test_invalid_payload_keeps_home_and_stores_no_free_text(env, payload):
    await env.message(CLIENT, f"/start {payload}".strip())
    assert attribution(env, CLIENT) is None
    assert env.store.for_user(CLIENT) is None
    assert "c:service:claude" in callbacks(last(env, CLIENT))
    assert env.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


async def test_named_bot_start_and_later_recognized_source_after_direct_start(env):
    await env.message(CLIENT, "/start")
    await env.message(CLIENT, "/start@test_verify_bot src_site_claude")
    assert attribution(env, CLIENT)["source_code"] == "src_site_claude"


async def test_ticket_snapshots_source_and_repeated_order_does_not_inflate_stats(env):
    await env.message(CLIENT, "/start src_site_alipay")
    first = await order(env, plan="europe")
    await order(env, plan="europe")
    await env.message(CLIENT, "/start src_partner")
    assert ticket_source(env.store, first.id) == "src_site_alipay"
    assert env.store.source_summary()[0]["tickets"] == 1
    env.store.set_status(first.id, first.version, "resolved", ADMIN)
    second = await order(env)
    assert ticket_source(env.store, second.id) == "src_site_alipay"
    assert env.store.source_summary() == [
        {"source_code": "src_site_alipay", "started_users": 1, "requested_users": 1, "tickets": 2}
    ]


async def test_late_source_never_attributes_old_ticket_even_when_still_active(env):
    old = await order(env)
    await env.message(CLIENT, "/start src_profile")
    await order(env)
    assert ticket_source(env.store, old.id) is None
    assert env.store.source_summary()[0] == {
        "source_code": "src_profile", "started_users": 1, "requested_users": 0, "tickets": 0
    }
    env.store.set_status(old.id, old.version, "resolved", ADMIN)
    new = await order(env)
    assert ticket_source(env.store, old.id) is None
    assert ticket_source(env.store, new.id) == "src_profile"
    assert env.store.source_summary()[0]["tickets"] == 1


async def test_operator_starts_and_own_test_orders_are_excluded_in_both_modes(env):
    await env.message(ADMIN, "/start src_tg_post")
    await env.message(ADMIN, "/client")
    await env.message(ADMIN, "/start src_partner")
    own = await order(env, uid=ADMIN)
    assert attribution(env, ADMIN) is None
    assert ticket_source(env.store, own.id) is None
    assert env.store.source_summary() == []


async def test_sources_report_has_no_customer_access_or_client_mode_bypass(env):
    await env.message(CLIENT, "/start src_partner")
    await order(env)
    for uid in (CLIENT, OTHER):
        await env.message(uid, "/sources")
        assert "только оператору" in last(env, uid)["text"]
        assert "Партнёрская ссылка" not in last(env, uid)["text"]
    await env.message(ADMIN, "/client")
    await env.message(ADMIN, "/sources")
    assert "Сейчас вы в режиме клиента" in last(env, ADMIN)["text"]
    assert "Партнёрская ссылка" not in last(env, ADMIN)["text"]
    await env.message(ADMIN, "/admin")
    await env.message(ADMIN, "/sources")
    report = last(env, ADMIN)["text"]
    assert "Партнёрская ссылка" in report and "Запустили: 1 · С заявкой: 1 · Заявок: 1" in report
    assert "не просмотры, позиции в поиске или оплаты" in report


async def test_stats_exclude_users_now_configured_as_operators(env):
    await env.message(CLIENT, "/start src_partner")
    await order(env)
    assert env.store.source_summary(exclude_ids=(CLIENT,)) == []


async def test_sources_and_ticket_snapshots_survive_restart(env):
    await env.message(CLIENT, "/start src_site_claude")
    ticket = await order(env)
    path = Path(env.store.db.execute("PRAGMA database_list").fetchone()["file"])
    reopened = Store(path)
    assert ticket_source(reopened, ticket.id) == "src_site_claude"
    assert reopened.source_summary() == env.store.source_summary()
    reopened.close()


def test_existing_database_gets_empty_tables_without_backfill(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    original = Store(path)
    original.remember_user(CLIENT, CLIENT, "Клиент", None)
    ticket, _ = original.create_ticket(CLIENT)
    original.db.execute("DROP TABLE ticket_acquisition")
    original.db.execute("DROP TABLE user_acquisition")
    original.db.commit()
    original.close()
    migrated = Store(path)
    assert migrated.ticket(ticket.id).status == "new"
    assert ticket_source(migrated, ticket.id) is None
    assert migrated.source_summary() == []
    migrated.close()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1


def test_storage_rejects_unknown_source_and_start_parser_accepts_only_allowlist(store):
    store.remember_user(CLIENT, CLIENT, "Клиент", None)
    assert not store.remember_source(CLIENT, "untrusted arbitrary text")
    assert store.source_summary() == []
    assert all(acquisition.start_source("/start " + code) == code for code in acquisition.SOURCES)
    assert acquisition.start_source("/profile src_partner") is None
