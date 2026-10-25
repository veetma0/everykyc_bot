from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata

from .acquisition import SOURCES


OPEN_STATUSES = ("new", "in_progress", "waiting_user")
QUEUE_STATUSES = ("new", "in_progress")
CLAIM_SECONDS = 15 * 60
STATUS_NAMES = {
    "new": "⏳ Ожидает оператора",
    "in_progress": "🛠 В работе",
    # Waiting for a reply changes queue eligibility, not the order's work stage.
    "waiting_user": "🛠 В работе",
    "resolved": "✅ Заказ выполнен",
    "cancelled": "❌ Заказ отменён",
}
TRANSITIONS = {
    "new": {"in_progress", "waiting_user", "resolved", "cancelled"},
    "in_progress": {"waiting_user", "resolved", "cancelled"},
    "waiting_user": {"in_progress", "resolved", "cancelled"},
    "resolved": set(),
    "cancelled": set(),
}


class StaleTicket(ValueError):
    pass


@dataclass(frozen=True)
class Ticket:
    id: int
    user_id: int
    chat_id: int
    display_name: str
    username: str | None
    status: str
    version: int
    created_at: float
    updated_at: float
    unread: int
    service_code: str = "claude"
    plan_code: str = "standard"
    price_usd: str | None = None
    demo_network: str | None = None
    waiting_since: float = 0
    payment_stage: str = "legacy"


def ticket_status(ticket: Ticket) -> str:
    """One customer-facing status, including the payment steps before work begins."""
    if ticket.status == "new":
        if ticket.payment_stage == "awaiting_payment":
            return "💳 Ожидает оплаты"
        if ticket.payment_stage == "review":
            return "🔎 Проверяем оплату"
    return STATUS_NAMES[ticket.status]


@dataclass(frozen=True)
class ClientProfile:
    id: int
    chat_id: int
    display_name: str
    username: str | None
    first_seen_at: float
    last_seen_at: float
    operator_note: str
    total_tickets: int
    active_tickets: int
    resolved_tickets: int
    cancelled_tickets: int
    latest_ticket_id: int | None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL,
                display_name TEXT NOT NULL, username TEXT
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                status TEXT NOT NULL CHECK(status IN ('new','in_progress','waiting_user','resolved','cancelled')),
                version INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                consent_at REAL NOT NULL, last_read_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_ticket ON tickets(user_id)
                WHERE status IN ('new','in_progress','waiting_user');
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user','operator','system')),
                body TEXT NOT NULL, actor_id INTEGER NOT NULL,
                source_chat INTEGER, source_message INTEGER,
                delivery TEXT NOT NULL DEFAULT 'stored', created_at REAL NOT NULL,
                UNIQUE(source_chat, source_message)
            );
            CREATE INDEX IF NOT EXISTS ticket_messages ON messages(ticket_id, id);
            CREATE TABLE IF NOT EXISTS payment_proofs (
                message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
                file_id TEXT,
                file_kind TEXT CHECK(file_kind IN ('photo','document')),
                CHECK((file_id IS NULL AND file_kind IS NULL)
                    OR (file_id IS NOT NULL AND file_kind IS NOT NULL))
            );
            CREATE TABLE IF NOT EXISTS reply_targets (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                delivered_operator_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS note_targets (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY(chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS customer_reply_targets (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                PRIMARY KEY(chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS operator_modes (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                mode TEXT NOT NULL CHECK(mode IN ('admin','client'))
            );
            CREATE TABLE IF NOT EXISTS user_acquisition (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                source_code TEXT NOT NULL,
                acquired_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticket_acquisition (
                ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
                source_code TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operator_claims (
                ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
                operator_id INTEGER NOT NULL UNIQUE CHECK(operator_id > 0),
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operator_focus (
                operator_id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                prompt_id INTEGER NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS input_drafts (
                user_id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                token TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('operator','proof')),
                body TEXT NOT NULL,
                source_chat INTEGER NOT NULL,
                source_message INTEGER NOT NULL,
                file_id TEXT, file_kind TEXT,
                ticket_version INTEGER NOT NULL,
                expires_at REAL NOT NULL
            );
        """)
        self._migrate()
        path.chmod(0o600)

    def _migrate(self):
        additions = {
            "users": {
                "first_seen_at": "REAL NOT NULL DEFAULT 0",
                "last_seen_at": "REAL NOT NULL DEFAULT 0",
                "operator_note": "TEXT NOT NULL DEFAULT ''",
                "note_updated_at": "REAL",
                "note_updated_by": "INTEGER",
            },
            "tickets": {
                "service_code": "TEXT NOT NULL DEFAULT 'claude'",
                "plan_code": "TEXT NOT NULL DEFAULT 'standard'",
                "price_usd": "TEXT",
                "demo_network": "TEXT",
                "waiting_since": "REAL NOT NULL DEFAULT 0",
                "payment_stage": "TEXT NOT NULL DEFAULT 'legacy'",
            },
            "reply_targets": {
                "delivered_operator_id": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for table, columns in additions.items():
                present = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
                for name, definition in columns.items():
                    if name not in present:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            now = time.time()
            self.db.execute(
                """UPDATE users SET first_seen_at=COALESCE(
                    (SELECT MIN(created_at) FROM tickets WHERE user_id=users.id), ?)
                    WHERE first_seen_at=0""",
                (now,),
            )
            self.db.execute(
                """UPDATE users SET last_seen_at=MAX(first_seen_at, COALESCE(
                    (SELECT MAX(updated_at) FROM tickets WHERE user_id=users.id), first_seen_at))
                    WHERE last_seen_at=0"""
            )

            self.db.execute("UPDATE tickets SET waiting_since=created_at WHERE waiting_since=0")
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS operator_queue ON tickets(waiting_since,id) "
                "WHERE status IN ('new','in_progress')"
            )

    @staticmethod
    def _code(value: str):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_]{1,32}", value):
            raise ValueError("Код должен содержать 1–32 строчных латинских символа, цифры или подчёркивания.")
        return value

    @staticmethod
    def _price(value: str | Decimal | None):
        if value is None:
            return None
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Цена должна быть десятичной строкой, без float.")
        try:
            amount = Decimal(value)
            if not amount.is_finite() or amount <= 0:
                raise ValueError("Цена должна быть положительной.")
            canonical = amount.quantize(Decimal("0.01"))
            if canonical != amount:
                raise ValueError("Цена не может содержать доли цента.")
        except InvalidOperation as exc:
            raise ValueError("Некорректная цена.") from exc
        return format(canonical, ".2f")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.db:
            yield

    def remember_user(self, user_id: int, chat_id: int, name: str, username: str | None):
        now = time.time()
        name = name[:160].strip()
        if not any(not c.isspace() and unicodedata.category(c) not in {"Cf", "Cc", "Mn", "Me"} for c in name):
            name = "Клиент"
        with self.db:
            self.db.execute(
                """INSERT INTO users(id,chat_id,display_name,username,first_seen_at,last_seen_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                chat_id=excluded.chat_id, display_name=excluded.display_name, username=excluded.username,
                last_seen_at=MAX(users.last_seen_at,excluded.last_seen_at)""",
                (user_id, chat_id, name, username, now, now),
            )

    def ticket(self, ticket_id: int) -> Ticket | None:
        row = self.db.execute(
            """SELECT t.id,t.user_id,u.chat_id,u.display_name,u.username,t.status,
            t.version,t.created_at,t.updated_at,t.service_code,t.plan_code,t.price_usd,t.demo_network,t.waiting_since,
            t.payment_stage,
            (SELECT COUNT(*) FROM messages m WHERE m.ticket_id=t.id AND m.role='user' AND m.id>t.last_read_id) unread
            FROM tickets t JOIN users u ON u.id=t.user_id WHERE t.id=?""",
            (ticket_id,),
        ).fetchone()
        return Ticket(**dict(row)) if row else None

    def remember_source(self, user_id: int, source_code: str) -> bool:
        """Keep only the first allowlisted source; this never modifies tickets."""
        if source_code not in SOURCES:
            return False
        with self.db:
            cursor = self.db.execute(
                """INSERT OR IGNORE INTO user_acquisition(user_id,source_code,acquired_at)
                VALUES(?,?,?)""",
                (user_id, source_code, time.time()),
            )
        return cursor.rowcount == 1

    def source_summary(self, exclude_ids: tuple[int, ...] = ()) -> list[dict]:
        excluded = tuple(dict.fromkeys(exclude_ids))
        if any(not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 for uid in excluded):
            raise ValueError("Некорректный Telegram ID.")
        where = f"WHERE a.user_id NOT IN ({','.join('?' for _ in excluded)})" if excluded else ""
        rows = self.db.execute(
            f"""SELECT a.source_code,COUNT(DISTINCT a.user_id) started_users,
                COUNT(DISTINCT CASE WHEN ta.ticket_id IS NOT NULL THEN a.user_id END) requested_users,
                COUNT(ta.ticket_id) tickets
                FROM user_acquisition a
                LEFT JOIN tickets t ON t.user_id=a.user_id
                LEFT JOIN ticket_acquisition ta ON ta.ticket_id=t.id AND ta.source_code=a.source_code
                {where} GROUP BY a.source_code ORDER BY tickets DESC,started_users DESC,a.source_code""",
            excluded,
        ).fetchall()
        return [dict(row) for row in rows if row["source_code"] in SOURCES]

    def for_user(self, user_id: int, active_only: bool = False) -> Ticket | None:
        sql = "SELECT id FROM tickets WHERE user_id=?"
        if active_only:
            sql += " AND status IN ('new','in_progress','waiting_user')"
        row = self.db.execute(sql + " ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        return self.ticket(row["id"]) if row else None

    def create_ticket(
        self,
        user_id: int,
        service_code: str = "claude",
        plan_code: str = "standard",
        price_usd: str | Decimal | None = None,
    ) -> tuple[Ticket, bool]:
        service_code = self._code(service_code)
        plan_code = self._code(plan_code)
        price_usd = self._price(price_usd)
        with self.transaction():
            current = self.for_user(user_id, active_only=True)
            if current:
                return current, False
            now = time.time()
            cursor = self.db.execute(
                """INSERT INTO tickets(user_id,status,created_at,updated_at,consent_at,service_code,
                plan_code,price_usd,waiting_since,payment_stage)
                VALUES(?,'new',?,?,?,?,?,?,?,'not_requested')""",
                (user_id, now, now, now, service_code, plan_code, price_usd, now),
            )
            self.db.execute(
                """INSERT INTO ticket_acquisition(ticket_id,source_code)
                SELECT ?,source_code FROM user_acquisition WHERE user_id=?""",
                (cursor.lastrowid, user_id),
            )
            self.db.execute(
                """INSERT INTO messages(ticket_id,role,body,actor_id,created_at)
                VALUES(?,'system',?,?,?)""",
                (
                    cursor.lastrowid,
                    "Заказ создан. Пользователь подтвердил проверку своего аккаунта на собственные данные.",
                    user_id,
                    now,
                ),
            )
            return self.ticket(cursor.lastrowid), True

    def profile(self, user_id: int) -> ClientProfile | None:
        row = self.db.execute(
            """SELECT u.id,u.chat_id,u.display_name,u.username,u.first_seen_at,u.last_seen_at,
                u.operator_note,COUNT(t.id) total_tickets,
                SUM(CASE WHEN t.status IN ('new','in_progress','waiting_user') THEN 1 ELSE 0 END) active_tickets,
                SUM(CASE WHEN t.status='resolved' THEN 1 ELSE 0 END) resolved_tickets,
                SUM(CASE WHEN t.status='cancelled' THEN 1 ELSE 0 END) cancelled_tickets,
                MAX(t.id) latest_ticket_id
                FROM users u LEFT JOIN tickets t ON t.user_id=u.id WHERE u.id=? GROUP BY u.id""",
            (user_id,),
        ).fetchone()
        return ClientProfile(**dict(row)) if row else None

    def clients_page(
        self,
        offset: int,
        limit: int = 8,
        exclude_ids: tuple[int, ...] = (),
    ) -> tuple[list[ClientProfile], int]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Некорректная страница клиентов.")
        excluded = tuple(dict.fromkeys(exclude_ids))
        if any(
            not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0 for user_id in excluded
        ):
            raise ValueError("Некорректный Telegram ID.")
        where = (
            f"WHERE id NOT IN ({','.join('?' for _ in excluded)}) "
            "OR EXISTS (SELECT 1 FROM tickets WHERE tickets.user_id=users.id)"
            if excluded
            else ""
        )
        total = self.db.execute(f"SELECT COUNT(*) FROM users {where}", excluded).fetchone()[0]
        rows = self.db.execute(
            f"SELECT id FROM users {where} ORDER BY last_seen_at DESC,id DESC LIMIT ? OFFSET ?",
            (*excluded, limit, offset),
        ).fetchall()
        return [self.profile(row["id"]) for row in rows], total

    def operator_mode(self, user_id: int) -> str:
        row = self.db.execute("SELECT mode FROM operator_modes WHERE user_id=?", (user_id,)).fetchone()
        return row["mode"] if row else "admin"

    def set_operator_mode(self, user_id: int, mode: str):
        if mode not in {"admin", "client"}:
            raise ValueError("Неизвестный режим.")
        with self.db:
            self.db.execute(
                "INSERT INTO operator_modes(user_id,mode) VALUES(?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode",
                (user_id, mode),
            )

    def set_note(self, user_id: int, body: str, actor_id: int) -> ClientProfile:
        if not isinstance(body, str) or len(body) > 1200:
            raise ValueError("Заметка должна содержать не более 1200 символов.")
        if not isinstance(actor_id, int) or isinstance(actor_id, bool) or actor_id <= 0:
            raise ValueError("Некорректный ID оператора.")
        with self.db:
            changed = self.db.execute(
                "UPDATE users SET operator_note=?,note_updated_at=?,note_updated_by=? WHERE id=?",
                (body.strip(), time.time(), actor_id, user_id),
            ).rowcount
            if not changed:
                raise ValueError("Клиент не найден.")
        return self.profile(user_id)

    def set_demo_network(self, ticket_id: int, network_code: str) -> Ticket:
        network_code = self._code(network_code)
        with self.db:
            ticket = self.ticket(ticket_id)
            if not ticket or ticket.status not in OPEN_STATUSES:
                raise StaleTicket("Выбор сети доступен только для открытой заявки.")
            self.db.execute(
                "UPDATE tickets SET demo_network=?,updated_at=? WHERE id=?",
                (network_code, time.time(), ticket_id),
            )
            return self.ticket(ticket_id)

    def page(self, scope: str, offset: int, limit: int = 8) -> tuple[list[Ticket], int]:
        where = {
            "active": "status IN ('new','in_progress','waiting_user')",
            "new": "status='new'",
            "closed": "status IN ('resolved','cancelled')",
        }[scope]
        total = self.db.execute(f"SELECT COUNT(*) FROM tickets WHERE {where}").fetchone()[0]
        rows = self.db.execute(
            f"SELECT id FROM tickets WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self.ticket(row[0]) for row in rows], total

    def counts(self) -> dict[str, int]:
        result = {key: 0 for key in STATUS_NAMES}
        for row in self.db.execute("SELECT status,COUNT(*) n FROM tickets GROUP BY status"):
            result[row["status"]] = row["n"]
        return result

    @staticmethod
    def _positive_id(value: int):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("Некорректный идентификатор.")
        return value

    def _purge_claims(self, now: float):
        self.db.execute(
            "DELETE FROM operator_claims WHERE expires_at<=? OR ticket_id IN "
            "(SELECT id FROM tickets WHERE status NOT IN ('new','in_progress','waiting_user'))",
            (now,),
        )

    def queue_count(self, operator_id: int | None = None) -> int:
        """Available requests awaiting an operator, including this operator's own claim."""
        if operator_id is not None:
            self._positive_id(operator_id)
        return self.db.execute(
            """SELECT COUNT(*) FROM tickets t WHERE t.status IN ('new','in_progress')
            AND t.payment_stage<>'awaiting_payment'
            AND NOT EXISTS (
                SELECT 1 FROM operator_claims c WHERE c.ticket_id=t.id AND c.expires_at>?
                AND (? IS NULL OR c.operator_id<>?)
            )""",
            (time.time(), operator_id, operator_id),
        ).fetchone()[0]

    def queue_page(
        self, operator_id: int, offset: int = 0, limit: int = 8
    ) -> tuple[list[Ticket], int]:
        self._positive_id(operator_id)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("Некорректная страница очереди.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("Некорректный размер страницы очереди.")
        predicate = """t.status IN ('new','in_progress') AND t.payment_stage<>'awaiting_payment'
        AND NOT EXISTS (
            SELECT 1 FROM operator_claims c WHERE c.ticket_id=t.id
            AND c.expires_at>? AND c.operator_id<>?
        )"""
        args = (time.time(), operator_id)
        # One read transaction keeps the page and its count from observing different commits.
        with self.db:
            self.db.execute("BEGIN")
            total = self.db.execute(
                f"SELECT COUNT(*) FROM tickets t WHERE {predicate}", args
            ).fetchone()[0]
            rows = self.db.execute(
                f"SELECT t.id FROM tickets t WHERE {predicate} "
                "ORDER BY t.waiting_since,t.id LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
            return [self.ticket(row["id"]) for row in rows], total

    def claim_owner(self, ticket_id: int) -> int | None:
        self._positive_id(ticket_id)
        row = self.db.execute(
            """SELECT c.operator_id FROM operator_claims c JOIN tickets t ON t.id=c.ticket_id
            WHERE c.ticket_id=? AND c.expires_at>?
            AND t.status IN ('new','in_progress','waiting_user')""",
            (ticket_id, time.time()),
        ).fetchone()
        return row["operator_id"] if row else None

    def claim_ticket(self, ticket_id: int, operator_id: int) -> bool:
        """Atomically acquire an explicitly selected open ticket, or leave both claims alone."""
        self._positive_id(ticket_id)
        self._positive_id(operator_id)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            now = time.time()
            self._purge_claims(now)
            row = self.db.execute(
                "SELECT status FROM tickets WHERE id=?", (ticket_id,)
            ).fetchone()
            if not row or row["status"] not in OPEN_STATUSES:
                return False
            owner = self.db.execute(
                "SELECT operator_id FROM operator_claims WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            if owner and owner["operator_id"] != operator_id:
                return False
            self.db.execute("DELETE FROM operator_claims WHERE operator_id=?", (operator_id,))
            self.db.execute(
                "INSERT INTO operator_claims(ticket_id,operator_id,expires_at) VALUES(?,?,?)",
                (ticket_id, operator_id, now + CLAIM_SECONDS),
            )
            return True

    def claim_next(self, operator_id: int, skip_ticket_id: int | None = None) -> Ticket | None:
        """Resume a claim or acquire the oldest unanswered request under one write lock."""
        self._positive_id(operator_id)
        if skip_ticket_id is not None:
            self._positive_id(skip_ticket_id)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            now = time.time()
            self._purge_claims(now)
            if skip_ticket_id is not None:
                self.db.execute("DELETE FROM operator_claims WHERE operator_id=?", (operator_id,))
            else:
                current = self.db.execute(
                    """SELECT c.ticket_id FROM operator_claims c JOIN tickets t ON t.id=c.ticket_id
                    WHERE c.operator_id=? AND t.status IN ('new','in_progress')
                    AND t.payment_stage<>'awaiting_payment'""",
                    (operator_id,),
                ).fetchone()
                if current:
                    self.db.execute(
                        "UPDATE operator_claims SET expires_at=? WHERE ticket_id=?",
                        (now + CLAIM_SECONDS, current["ticket_id"]),
                    )
                    return self.ticket(current["ticket_id"])
            row = self.db.execute(
                """SELECT t.id FROM tickets t WHERE t.status IN ('new','in_progress')
                AND t.payment_stage<>'awaiting_payment'
                AND (? IS NULL OR t.id<>?)
                AND NOT EXISTS (SELECT 1 FROM operator_claims c WHERE c.ticket_id=t.id)
                ORDER BY t.waiting_since,t.id LIMIT 1""",
                (skip_ticket_id, skip_ticket_id),
            ).fetchone()
            if not row:
                return None
            self.db.execute("DELETE FROM operator_claims WHERE operator_id=?", (operator_id,))
            self.db.execute(
                "INSERT INTO operator_claims(ticket_id,operator_id,expires_at) VALUES(?,?,?)",
                (row["id"], operator_id, now + CLAIM_SECONDS),
            )
            return self.ticket(row["id"])

    def release_claim(self, operator_id: int, ticket_id: int | None = None) -> bool:
        self._positive_id(operator_id)
        if ticket_id is not None:
            self._positive_id(ticket_id)
        with self.db:
            self.db.execute(
                "DELETE FROM operator_focus WHERE operator_id=? AND (? IS NULL OR ticket_id=?)",
                (operator_id, ticket_id, ticket_id),
            )
            changed = self.db.execute(
                "DELETE FROM operator_claims WHERE operator_id=? AND (? IS NULL OR ticket_id=?)",
                (operator_id, ticket_id, ticket_id),
            ).rowcount
        return bool(changed)

    def focus_operator(self, operator_id: int, ticket_id: int, prompt_id: int):
        if self.claim_owner(ticket_id) != operator_id:
            raise StaleTicket("Выберите заказ заново.")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO operator_focus VALUES(?,?,?,?)",
                (operator_id, ticket_id, prompt_id, time.time() + CLAIM_SECONDS),
            )

    def focused_ticket(self, operator_id: int):
        row = self.db.execute(
            "SELECT * FROM operator_focus WHERE operator_id=? AND expires_at>?",
            (operator_id, time.time()),
        ).fetchone()
        if not row or self.claim_owner(row["ticket_id"]) != operator_id:
            return None
        if self.stale_operator_reply(operator_id, row["prompt_id"], operator_id):
            return None
        ticket = self.ticket(row["ticket_id"])
        return ticket if ticket and ticket.status in OPEN_STATUSES else None

    def clear_input(self, user_id: int):
        with self.db:
            self.db.execute("DELETE FROM operator_focus WHERE operator_id=?", (user_id,))
            self.db.execute("DELETE FROM input_drafts WHERE user_id=?", (user_id,))

    def save_draft(self, user_id, ticket_id, kind, body, source_chat, source_message,
                   file_id=None, file_kind=None):
        ticket = self.ticket(ticket_id)
        if not ticket or ticket.status not in OPEN_STATUSES:
            raise StaleTicket()
        if kind == "proof" and (ticket.user_id != user_id or ticket.payment_stage not in {"awaiting_payment", "review"}):
            raise StaleTicket()
        if kind == "operator" and self.focused_ticket(user_id) != ticket:
            raise StaleTicket()
        previous = self.draft(user_id)
        if previous and (previous["source_chat"], previous["source_message"]) == (source_chat, source_message):
            return previous
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO input_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, ticket_id, secrets.token_hex(6), kind, body, source_chat, source_message,
                 file_id, file_kind, ticket.version, time.time() + 10 * 60),
            )
        return self.draft(user_id)

    def draft(self, user_id, token=None):
        if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{12}", token)):
            return None
        row = self.db.execute(
            "SELECT * FROM input_drafts WHERE user_id=? AND expires_at>?", (user_id, time.time())
        ).fetchone()
        return row if row and (token is None or secrets.compare_digest(row["token"], token)) else None

    def set_status(self, ticket_id: int, version: int, status: str, actor_id: int) -> Ticket:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            ticket = self.ticket(ticket_id)
            if not ticket or ticket.version != version or status not in TRANSITIONS[ticket.status]:
                raise StaleTicket("Заявка уже изменилась. Откройте актуальную карточку.")
            if ticket.payment_stage not in {"legacy", "confirmed"} and status != "cancelled":
                raise StaleTicket("Сначала подтвердите оплату заказа после проверки.")
            # A customer may cancel their own order even while an operator has it open.
            if not (status == "cancelled" and actor_id == ticket.user_id):
                self._check_claim_actor(ticket_id, actor_id)
            now = time.time()
            self.db.execute(
                """UPDATE tickets SET status=?,version=version+1,updated_at=?,
                waiting_since=CASE WHEN status='waiting_user' AND ?='in_progress'
                    THEN ? ELSE waiting_since END WHERE id=?""",
                (status, now, status, now, ticket_id),
            )
            if status not in OPEN_STATUSES:
                self.db.execute("DELETE FROM operator_claims WHERE ticket_id=?", (ticket_id,))
            self.db.execute(
                "INSERT INTO messages(ticket_id,role,body,actor_id,created_at) VALUES(?,'system',?,?,?)",
                (ticket_id, f"Статус: {STATUS_NAMES[status]}", actor_id, now),
            )
            return self.ticket(ticket_id)

    def _check_claim_actor(self, ticket_id: int, actor_id: int):
        self._positive_id(actor_id)
        owner = self.claim_owner(ticket_id)
        if owner is not None and owner != actor_id:
            raise StaleTicket("Заказ уже открыт другим оператором. Откройте актуальную карточку.")

    def _payment_ticket(self, ticket_id: int, version: int, actor_id: int, stage: str) -> Ticket:
        """Validate a payment operation while its caller holds the write transaction."""
        ticket = self.ticket(ticket_id)
        if (
            not ticket or ticket.version != version
            or ticket.status != "new" or ticket.payment_stage != stage
        ):
            raise StaleTicket("Заказ уже изменился. Откройте актуальную карточку.")
        self._check_claim_actor(ticket_id, actor_id)
        return ticket

    def _payment_event(self, ticket_id: int, body: str, actor_id: int, now: float):
        self.db.execute(
            "INSERT INTO messages(ticket_id,role,body,actor_id,created_at) VALUES(?,'system',?,?,?)",
            (ticket_id, body, actor_id, now),
        )

    def request_payment(self, ticket_id: int, version: int, actor_id: int) -> Ticket:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._payment_ticket(ticket_id, version, actor_id, "not_requested")
            now = time.time()
            self.db.execute(
                "UPDATE tickets SET payment_stage='awaiting_payment',version=version+1,updated_at=? WHERE id=?",
                (now, ticket_id),
            )
            self.db.execute("DELETE FROM operator_claims WHERE ticket_id=?", (ticket_id,))
            self._payment_event(ticket_id, "💳 Ожидает оплаты. Оператор принял заказ.", actor_id, now)
            return self.ticket(ticket_id)

    def submit_payment_proof(
        self, ticket_id: int, body: str, actor_id: int, chat_id: int, message_id: int,
        file_id: str | None = None, file_kind: str | None = None,
    ) -> tuple[int, bool]:
        self._positive_id(actor_id)
        self._positive_id(message_id)
        if not isinstance(body, str) or (not body.strip() and file_id is None):
            raise ValueError("Добавьте подтверждение оплаты.")
        if file_id is None:
            if file_kind is not None:
                raise ValueError("Не найден файл подтверждения.")
        elif not isinstance(file_id, str) or not file_id.strip() or file_kind not in {"photo", "document"}:
            raise ValueError("Неподдерживаемый файл подтверждения.")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            ticket = self.ticket(ticket_id)
            if not ticket or ticket.user_id != actor_id or ticket.chat_id != chat_id:
                raise StaleTicket("Этот заказ недоступен.")
            previous = self.find_source(chat_id, message_id)
            if previous:
                proof = self.db.execute(
                    "SELECT message_id FROM payment_proofs WHERE message_id=?", (previous["id"],)
                ).fetchone()
                if previous["ticket_id"] != ticket_id or previous["actor_id"] != actor_id or not proof:
                    raise StaleTicket("Это сообщение уже сохранено. Пришлите новое подтверждение.")
                return previous["id"], False
            if ticket.status != "new" or ticket.payment_stage not in {"awaiting_payment", "review"}:
                raise StaleTicket("Сейчас подтверждение оплаты для этого заказа не требуется.")
            now = time.time()
            cursor = self.db.execute(
                """INSERT INTO messages(ticket_id,role,body,actor_id,source_chat,source_message,created_at)
                VALUES(?,'user',?,?,?,?,?)""",
                (ticket_id, body, actor_id, chat_id, message_id, now),
            )
            self.db.execute(
                "INSERT INTO payment_proofs(message_id,file_id,file_kind) VALUES(?,?,?)",
                (cursor.lastrowid, file_id, file_kind),
            )
            self.db.execute(
                """UPDATE tickets SET payment_stage='review',version=version+1,updated_at=?,
                waiting_since=CASE WHEN payment_stage='awaiting_payment' THEN ? ELSE waiting_since END
                WHERE id=?""",
                (now, now, ticket_id),
            )
            if ticket.payment_stage == "awaiting_payment":
                self._payment_event(ticket_id, "🔎 Подтверждение оплаты получено. Ожидает проверки.", actor_id, now)
            return cursor.lastrowid, True

    def payment_proofs(self, ticket_id: int):
        return self.db.execute(
            """SELECT m.*,p.message_id,p.file_id,p.file_kind FROM payment_proofs p
            JOIN messages m ON m.id=p.message_id WHERE m.ticket_id=? ORDER BY m.id DESC""",
            (ticket_id,),
        ).fetchall()

    def confirm_payment(self, ticket_id: int, version: int, actor_id: int) -> Ticket:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._payment_ticket(ticket_id, version, actor_id, "review")
            if not self.payment_proofs(ticket_id):
                raise StaleTicket("Подтверждение оплаты ещё не получено.")
            now = time.time()
            self.db.execute(
                """UPDATE tickets SET payment_stage='confirmed',status='in_progress',
                version=version+1,updated_at=? WHERE id=?""",
                (now, ticket_id),
            )
            self._payment_event(ticket_id, "✅ Оплата подтверждена оператором. 🛠 В работе.", actor_id, now)
            return self.ticket(ticket_id)

    def reject_payment(self, ticket_id: int, version: int, actor_id: int) -> Ticket:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._payment_ticket(ticket_id, version, actor_id, "review")
            now = time.time()
            self.db.execute(
                "UPDATE tickets SET payment_stage='awaiting_payment',version=version+1,updated_at=? WHERE id=?",
                (now, ticket_id),
            )
            self.db.execute("DELETE FROM operator_claims WHERE ticket_id=?", (ticket_id,))
            self._payment_event(ticket_id, "💳 Оплата не подтверждена. Нужно новое подтверждение.", actor_id, now)
            return self.ticket(ticket_id)

    def find_source(self, chat_id: int, message_id: int):
        return self.db.execute(
            "SELECT * FROM messages WHERE source_chat=? AND source_message=?", (chat_id, message_id)
        ).fetchone()

    def add_message(
        self, ticket_id: int, role: str, body: str, actor_id: int, chat_id: int, message_id: int
    ) -> tuple[int, bool]:
        with self.transaction():
            previous = self.find_source(chat_id, message_id)
            if previous:
                return previous["id"], False
            ticket = self.ticket(ticket_id)
            if not ticket or ticket.status not in OPEN_STATUSES:
                raise StaleTicket("Заявка закрыта. Создайте новую, если помощь ещё нужна.")
            now = time.time()
            cursor = self.db.execute(
                """INSERT INTO messages(ticket_id,role,body,actor_id,source_chat,source_message,delivery,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    ticket_id,
                    role,
                    body,
                    actor_id,
                    chat_id,
                    message_id,
                    "pending" if role == "operator" else "stored",
                    now,
                ),
            )
            if role == "user":
                self.db.execute(
                    """UPDATE tickets SET
                    waiting_since=CASE WHEN status='waiting_user' THEN ? ELSE waiting_since END,
                    status=CASE WHEN status='waiting_user' THEN 'in_progress' ELSE status END,
                    version=version+1 WHERE id=?""",
                    (now, ticket_id),
                )
            self.db.execute("UPDATE tickets SET updated_at=? WHERE id=?", (now, ticket_id))
            return cursor.lastrowid, True

    def delivery(self, message_id: int, state: str):
        if state not in {"stored", "pending", "delivered", "failed", "uncertain"}:
            raise ValueError("Unknown delivery state")
        with self.db:
            self.db.execute("UPDATE messages SET delivery=? WHERE id=?", (state, message_id))

    def finalize_operator_delivery(self, message_id: int, state: str, actor_id: int) -> Ticket:
        """Commit delivery and queue state together; a later client message always stays actionable."""
        self._positive_id(actor_id)
        if state not in {"delivered", "failed", "uncertain"}:
            raise ValueError("Unknown operator delivery state")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            message = self.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if not message or message["role"] != "operator" or message["actor_id"] != actor_id:
                raise ValueError("Сообщение оператора не найдено.")
            ticket_id = message["ticket_id"]
            if message["delivery"] != "pending":
                return self.ticket(ticket_id)
            self.db.execute("UPDATE messages SET delivery=? WHERE id=?", (state, message_id))
            if state == "delivered":
                now = time.time()
                changed = self.db.execute(
                    """UPDATE tickets SET status='waiting_user',version=version+1,updated_at=?
                    WHERE id=? AND status IN ('new','in_progress')
                    AND payment_stage IN ('legacy','confirmed')
                    AND NOT EXISTS (
                        SELECT 1 FROM messages m WHERE m.ticket_id=tickets.id
                        AND m.role='user' AND m.id>?
                    )""",
                    (now, ticket_id, message_id),
                ).rowcount
                if changed:
                    self.db.execute(
                        "INSERT INTO messages(ticket_id,role,body,actor_id,created_at) "
                        "VALUES(?,'system',?,?,?)",
                        (ticket_id, f"Статус: {STATUS_NAMES['waiting_user']}", actor_id, now),
                    )
                self.db.execute(
                    """UPDATE tickets SET last_read_id=MAX(last_read_id,COALESCE((
                        SELECT MAX(id) FROM messages WHERE ticket_id=? AND role='user' AND id<?
                    ),0)) WHERE id=?""",
                    (ticket_id, message_id, ticket_id),
                )
                self.db.execute(
                    "DELETE FROM operator_claims WHERE ticket_id=? AND operator_id=?",
                    (ticket_id, actor_id),
                )
            return self.ticket(ticket_id)

    def recover_pending(self) -> int:
        with self.db:
            return self.db.execute(
                "UPDATE messages SET delivery='uncertain' WHERE delivery='pending'"
            ).rowcount

    def messages(self, ticket_id: int, page: int = 0, size: int = 4):
        total = self.db.execute("SELECT COUNT(*) FROM messages WHERE ticket_id=?", (ticket_id,)).fetchone()[0]
        rows = self.db.execute(
            "SELECT * FROM messages WHERE ticket_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (ticket_id, size, page * size),
        ).fetchall()
        return list(reversed(rows)), total

    def mark_read(self, ticket_id: int):
        with self.db:
            self.db.execute(
                "UPDATE tickets SET last_read_id=COALESCE((SELECT MAX(id) FROM messages WHERE ticket_id=?),0) WHERE id=?",
                (ticket_id, ticket_id),
            )

    def map_reply(self, chat_id: int, message_id: int, ticket_id: int):
        with self.db:
            self.db.execute(
                "DELETE FROM note_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "DELETE FROM customer_reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                """INSERT OR REPLACE INTO reply_targets(
                    chat_id,message_id,ticket_id,delivered_operator_id
                ) VALUES(?,?,?,COALESCE((
                    SELECT MAX(id) FROM messages WHERE ticket_id=?
                    AND role='operator' AND delivery='delivered'
                ),0))""",
                (chat_id, message_id, ticket_id, ticket_id),
            )

    def unmap_reply(self, chat_id: int, message_id: int):
        with self.db:
            self.db.execute(
                "DELETE FROM reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "DELETE FROM note_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "DELETE FROM customer_reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )

    def map_note_reply(self, chat_id: int, message_id: int, user_id: int):
        with self.db:
            self.db.execute(
                "DELETE FROM reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "DELETE FROM customer_reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "INSERT OR REPLACE INTO note_targets VALUES(?,?,?)", (chat_id, message_id, user_id)
            )

    def note_reply_user(self, chat_id: int, message_id: int) -> int | None:
        row = self.db.execute(
            "SELECT user_id FROM note_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
        ).fetchone()
        return row["user_id"] if row else None

    def reply_ticket(self, chat_id: int, message_id: int) -> Ticket | None:
        row = self.db.execute(
            "SELECT ticket_id FROM reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
        ).fetchone()
        return self.ticket(row[0]) if row else None

    def stale_operator_reply(self, chat_id: int, message_id: int, actor_id: int) -> bool:
        """An old card cannot silently bypass an answer already sent by a colleague."""
        self._positive_id(actor_id)
        return bool(self.db.execute(
            """SELECT EXISTS(
                SELECT 1 FROM reply_targets r JOIN messages m ON m.ticket_id=r.ticket_id
                WHERE r.chat_id=? AND r.message_id=? AND m.role='operator'
                AND m.delivery='delivered' AND m.actor_id<>? AND m.id>r.delivered_operator_id
            )""",
            (chat_id, message_id, actor_id),
        ).fetchone()[0])

    def map_customer_reply(self, chat_id: int, message_id: int, ticket_id: int):
        with self.db:
            self.db.execute(
                "DELETE FROM reply_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "DELETE FROM note_targets WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            )
            self.db.execute(
                "INSERT OR REPLACE INTO customer_reply_targets VALUES(?,?,?)",
                (chat_id, message_id, ticket_id),
            )

    def customer_reply_ticket(self, chat_id: int, message_id: int) -> Ticket | None:
        row = self.db.execute(
            "SELECT ticket_id FROM customer_reply_targets WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        ).fetchone()
        return self.ticket(row[0]) if row else None
