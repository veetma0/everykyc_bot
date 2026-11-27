"""The classic option works even if Telegram accepted an unreadable rich message."""

import pytest

from verifydesk import rules
from verifydesk.bot import customer_commands, operator_commands
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import callbacks, last, order


def last_wire(env, uid=CLIENT):
    return next((name, params) for name, params in reversed(env.request.calls)
                if params.get("chat_id") == uid and (name.startswith("send") or name.startswith("edit")))


@pytest.mark.parametrize("rich_start", [False, True])
async def test_classic_before_consent_requires_all_readable_pages(env, rich_start):
    env.require_terms = True
    if rich_start:
        await env.message(CLIENT, "/start")
        assert "rich_message" in last_wire(env)[1]
    await env.message(CLIENT, "/classic")
    assert env.store.uses_classic(CLIENT)
    assert last_wire(env)[0] == "sendMessage"
    assert rules.PAGES[0] in last(env, CLIENT)["text"]
    await env.callback(CLIENT, f"c:agree_full:{rules.VERSION}")
    assert env.store.terms_state(CLIENT)["accepted_at"] is None
    assert callbacks(last(env, CLIENT)) == [f"c:rules:{rules.VERSION}:1", "l:set:en"]
    await env.callback(CLIENT, f"c:rules:{rules.VERSION}:{len(rules.PAGES) - 1}")
    assert rules.PAGES[0] in last(env, CLIENT)["text"]
    for i in range(1, len(rules.PAGES)):
        await env.callback(CLIENT, f"c:rules:{rules.VERSION}:{i}")
        assert rules.PAGES[i] in last(env, CLIENT)["text"]
        assert "rich_message" not in last_wire(env)[1]
    await env.callback(CLIENT, f"c:agree:{rules.VERSION}")
    assert env.store.terms_state(CLIENT)["accepted_version"] == rules.VERSION
    assert "c:category:wallets" in callbacks(last(env, CLIENT))
    assert "rich_message" not in last_wire(env)[1]
    await env.callback(CLIENT, "c:rules")
    assert "c:home" in callbacks(last(env, CLIENT))
    assert rules.PAGES[0] in last(env, CLIENT)["text"]


async def test_modern_restores_complete_rules_before_consent(env):
    env.require_terms = True
    await env.message(CLIENT, "/classic")
    await env.message(CLIENT, "/modern")
    assert not env.store.uses_classic(CLIENT)
    assert "rich_message" in last_wire(env)[1]
    assert last(env, CLIENT)["text"] == rules.full_card()[0]
    assert env.store.terms_state(CLIENT)["accepted_at"] is None
    await env.callback(CLIENT, f"c:agree_full:{rules.VERSION}")
    assert "rich_message" in last_wire(env)[1]
    assert env.store.terms_state(CLIENT)["accepted_version"] == rules.VERSION


async def test_classic_persists_across_reopen_and_applies_to_notices_until_modern(env, tmp_path):
    await env.message(CLIENT, "/classic")
    assert last_wire(env)[0] == "sendPhoto"
    assert "c:catalog" in callbacks(last(env, CLIENT))
    reopened = Store(tmp_path / "desk.sqlite3")
    try:
        assert reopened.uses_classic(CLIENT) and not reopened.uses_classic(OTHER)
    finally:
        reopened.close()
    await env.message(OTHER, "/start")
    assert "rich_message" in last_wire(env, OTHER)[1]
    await env.callback(CLIENT, "c:catalog")
    assert "rich_message" not in last_wire(env)[1]
    ticket = await order(env)
    desk = env.app.post_init.__self__
    assert await desk.notify_customer_status(env.app.bot, ticket) == "delivered"
    assert last_wire(env)[0] == "sendMessage"
    assert last_wire(env)[1]["reply_markup"]["inline_keyboard"]
    await env.message(CLIENT, "/modern")
    assert "rich_message" in last_wire(env)[1] and not env.store.uses_classic(CLIENT)
    assert await desk.notify_customer_status(env.app.bot, ticket) == "delivered"
    assert last_wire(env)[0] == "sendRichMessage"


async def test_interface_commands_only_change_customer_mode_in_private_chats(env):
    commands = {item.command for item in customer_commands()}
    assert {"classic", "modern"} <= commands
    assert {"classic", "modern"}.isdisjoint(item.command for item in operator_commands())
    await env.message(ADMIN, "/classic")
    assert env.store.operator_mode(ADMIN) == "admin" and not env.store.uses_classic(ADMIN)
    await env.message(OTHER, "/classic", chat_type="group")
    assert not env.store.uses_classic(OTHER)
    await env.message(OTHER, "/classic@some_other_bot")
    assert not env.store.uses_classic(OTHER)
    await env.message(ADMIN, "/client")
    await env.message(ADMIN, "/classic")
    assert env.store.uses_classic(ADMIN) and "a:mode:admin" in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, "a:mode:admin")
    assert env.store.operator_mode(ADMIN) == "admin"
    assert "Кабинет оператора" in last(env, ADMIN)["text"]
    await env.message(ADMIN, "/preview")
    assert "rich_message" in last_wire(env, ADMIN)[1]
