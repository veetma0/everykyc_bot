"""Current catalog and stale callbacks, with historical records kept readable."""

import pytest

from verifydesk import catalog

from .conftest import ADMIN, CLIENT
from .test_upgrade import callbacks, last, sent
from .payment_helpers import legacy_ticket


DISABLED_SERVICES = ("alipay", "chatgpt", "gemini")


def ticket_rows(env):
    return [tuple(row) for row in env.store.db.execute("SELECT * FROM tickets ORDER BY id")]


def message_rows(env):
    return [tuple(row) for row in env.store.db.execute("SELECT * FROM messages ORDER BY id")]


@pytest.mark.parametrize("prefix,uid", [("c", CLIENT), ("p", ADMIN)])
@pytest.mark.parametrize("service", DISABLED_SERVICES)
@pytest.mark.parametrize("verb", ["offer", "order", "guide", "service"])
async def test_disabled_service_buttons_have_recovery_and_cannot_create_requests(env, prefix, uid, service, verb):
    tail = f"{service}:standard" if verb in {"offer", "order"} else service
    before_tickets, before_messages = ticket_rows(env), message_rows(env)
    before_notifications = len(sent(env, ADMIN))
    await env.callback(uid, f"{prefix}:{verb}:{tail}")
    screen = last(env, uid)
    assert "Claude" in screen["text"]
    assert "только" in screen["text"].lower() or "недоступ" in screen["text"].lower()
    assert any(value in callbacks(screen) for value in (f"{prefix}:service:claude", f"{prefix}:catalog"))
    assert not any(value.startswith(f"{prefix}:order:{service}:") for value in callbacks(screen))
    assert ticket_rows(env) == before_tickets
    assert message_rows(env) == before_messages
    if prefix == "p":
        assert "ПРЕДПРОСМОТР" in screen["text"]
        assert all(value.startswith("p:") or value == "a:home" for value in callbacks(screen))
    else:
        assert len(sent(env, ADMIN)) == before_notifications


@pytest.mark.parametrize("entry", ["/start", "/services", "/help", "c:catalog", "c:service:claude"])
async def test_current_customer_entrypoints_only_expose_claude(env, entry):
    if entry.startswith("/"):
        await env.message(CLIENT, entry)
    else:
        await env.callback(CLIENT, entry)
    screen = last(env, CLIENT)
    rendered = (screen["text"] + " " + " ".join(callbacks(screen))).lower()
    assert "claude" in rendered
    assert all(service not in rendered for service in DISABLED_SERVICES)
    assert {service for service, _ in catalog.OFFERS} == {"claude"}
    assert {offer.price_usd for offer in catalog.OFFERS.values()} == {"35.00", "50.00"}


@pytest.mark.parametrize("status", ["new", "resolved"])
async def test_historical_alipay_ticket_and_messages_survive_new_catalog(env, status):
    # Existing database records may refer to services retired from the current catalog.
    env.store.remember_user(CLIENT, CLIENT, "Клиент", None)
    ticket, _ = env.store.create_ticket(CLIENT, "alipay", "standard", "27.00")
    env.store.add_message(ticket.id, "user", "История прежней заявки", CLIENT, CLIENT, 901)
    ticket = env.store.ticket(ticket.id)
    if status != ticket.status:
        legacy_ticket(env.store, ticket)
        ticket = env.store.set_status(ticket.id, ticket.version, status, ADMIN)
    before_tickets, before_messages = ticket_rows(env), message_rows(env)

    await env.callback(CLIENT, "c:orders:0")
    assert f"c:view:{ticket.id}" in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, f"c:view:{ticket.id}")
    customer = last(env, CLIENT)
    assert "Alipay" in customer["text"] and "$27" in customer["text"]
    assert "смотрите в Claude" not in customer["text"]
    await env.callback(CLIENT, f"c:history:{ticket.id}:0")
    assert "История прежней заявки" in last(env, CLIENT)["text"]
    await env.callback(ADMIN, f"a:view:{ticket.id}")
    assert "Alipay" in last(env, ADMIN)["text"] and "$27" in last(env, ADMIN)["text"]
    await env.callback(CLIENT, "c:order:alipay:standard")
    assert env.store.profile(CLIENT).total_tickets == 1
    # Reading as operator may mark messages read, but must preserve the service, price and history.
    latest = env.store.ticket(ticket.id)
    assert (latest.id, latest.service_code, latest.plan_code, latest.price_usd, latest.status) == (
        ticket.id, "alipay", "standard", "27.00", status
    )
    assert len(ticket_rows(env)) == len(before_tickets)
    assert message_rows(env) == before_messages
