"""Run with --mode write/read in isolated containers; never use a production data volume."""

import argparse

from verifydesk.__main__ import SingleInstance
from verifydesk.config import Config
from verifydesk.deployment import check_storage
from verifydesk.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("write", "read"), default="write")
    mode = parser.parse_args().mode
    config = Config.load()
    check_storage(config)
    lock = SingleInstance(config.data_dir)
    store = Store(config.data_dir / "desk.sqlite3")
    try:
        if mode == "write":
            store.remember_user(101, 101, "Container test", None)
            ticket, created = store.create_ticket(101, "claude", "armenia", "35.00")
            assert created
            store.add_message(ticket.id, "user", "Persistence check", 101, 101, 1)
            store.claim_ticket(ticket.id, 9001)
        ticket = store.for_user(101)
        assert ticket.price_usd == "35.00"
        assert ticket.unread == 1
        assert store.claim_owner(ticket.id) == 9001
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        print(f"Container {mode} check passed; no Telegram calls.")
    finally:
        store.close()
        lock.close()


if __name__ == "__main__":
    main()
