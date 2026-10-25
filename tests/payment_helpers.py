"""Explicit setup for pre-payment legacy records in compatibility tests."""


def legacy_ticket(store, ticket):
    """Model an existing order migrated before the payment workflow was introduced."""
    with store.db:
        store.db.execute("UPDATE tickets SET payment_stage='legacy' WHERE id=?", (ticket.id,))
    return store.ticket(ticket.id)


async def legacy_order(env, *args, **kwargs):
    from .test_upgrade import order

    return legacy_ticket(env.store, await order(env, *args, **kwargs))
