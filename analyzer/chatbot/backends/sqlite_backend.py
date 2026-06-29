"""Bundled SQLite customer backend — the demo/reference implementation.

Self-creates and seeds a small customer DB (users, products, recent_purchases,
support_tickets) on first use, so the chatbot works with zero external infra.
This is also the worked example of the `CustomerBackend` contract: a new adapter
only needs to provide the same four primitives.

Config (optional): connection.path — SQLite file path (default analyzer/chatbot/edbms.db).
Demo users: alice/bob/carol/dave/eve — password `pass123`.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Optional

from .base import CustomerBackend
from .config import BackendConfig

# analyzer/chatbot/edbms.db (one level up from this backends/ package)
_DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "edbms.db")


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


class SQLiteBackend(CustomerBackend):
    def __init__(self, config: BackendConfig | None = None):
        conn = (config.connection if config else {}) or {}
        self.db_path = conn.get("path", _DEFAULT_DB)
        self._init_schema()
        self._seed()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ── schema + seed ─────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._conn() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY,
                username    TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name        TEXT NOT NULL,
                email       TEXT,
                tier        TEXT DEFAULT 'standard',
                join_date   TEXT
            );
            CREATE TABLE IF NOT EXISTS products (
                id          INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                category    TEXT,
                price       REAL
            );
            CREATE TABLE IF NOT EXISTS recent_purchases (
                id              INTEGER PRIMARY KEY,
                user_id         INTEGER REFERENCES users(id),
                product_id      INTEGER REFERENCES products(id),
                order_ref       TEXT,
                order_date      TEXT,
                delivery_date   TEXT,
                amount          REAL,
                status          TEXT DEFAULT 'delivered',
                issue           TEXT
            );
            -- status: processing | in_transit | out_for_delivery | delivered | cancelled
            -- issue:  NULL | damaged | wrong_item | late | missing
            CREATE TABLE IF NOT EXISTS support_tickets (
                id          INTEGER PRIMARY KEY,
                user_id     INTEGER REFERENCES users(id),
                purchase_id INTEGER REFERENCES recent_purchases(id),
                ticket_ref  TEXT UNIQUE,
                ticket_type TEXT,
                status      TEXT DEFAULT 'open',
                created_at  TEXT
            );
            """)

    def _seed(self) -> None:
        with self._conn() as con:
            if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
                return  # already seeded

            con.executemany(
                "INSERT INTO users(username,password_hash,name,email,tier,join_date) "
                "VALUES(?,?,?,?,?,date('now','-'||abs(random()%730)||' days'))",
                [
                    ("alice", _hash("pass123"), "Alice Nguyen", "alice@example.com", "premium"),
                    ("bob", _hash("pass123"), "Bob Smith", "bob@example.com", "standard"),
                    ("carol", _hash("pass123"), "Carol Davis", "carol@example.com", "vip"),
                    ("dave", _hash("pass123"), "Dave Lee", "dave@example.com", "standard"),
                    ("eve", _hash("pass123"), "Eve Martinez", "eve@example.com", "premium"),
                ],
            )
            con.executemany(
                "INSERT INTO products(name,category,price) VALUES(?,?,?)",
                [
                    ("Wireless Headphones", "Electronics", 89.99),
                    ("Running Shoes", "Footwear", 129.00),
                    ("Coffee Maker", "Appliances", 59.99),
                    ("Yoga Mat", "Fitness", 35.00),
                    ("Desk Lamp", "Home Office", 45.00),
                    ("Protein Powder", "Nutrition", 49.99),
                    ("Gaming Mouse", "Electronics", 69.99),
                    ("Water Bottle", "Fitness", 25.00),
                ],
            )
            now = time.time()
            purchases = [
                # (user_id, product_id, order_ref, order_off_days, delivery_off, amount, status, issue)
                # Each user has a live (not-yet-delivered) order so "what's my order status?" has
                # something current to report.
                (1, 1, "ORD-A001", -30, -27, 89.99, "delivered", None),
                (1, 5, "ORD-A002", -14, -11, 45.00, "delivered", None),
                (1, 3, "ORD-A003", -3, 0, 59.99, "delivered", "damaged"),
                (1, 7, "ORD-A004", -1, None, 69.99, "out_for_delivery", None),
                (1, 4, "ORD-A005", 0, None, 35.00, "processing", None),
                (2, 2, "ORD-B001", -60, -57, 129.00, "delivered", None),
                (2, 7, "ORD-B002", -7, -4, 69.99, "delivered", "wrong_item"),
                (2, 4, "ORD-B003", -1, None, 35.00, "in_transit", None),
                (3, 6, "ORD-C001", -10, -7, 49.99, "delivered", None),
                (3, 8, "ORD-C002", -5, -2, 25.00, "delivered", "missing"),
                (3, 1, "ORD-C003", -2, 0, 89.99, "delivered", None),
                (3, 2, "ORD-C004", -1, None, 129.00, "out_for_delivery", None),
                (4, 3, "ORD-D001", -45, -42, 59.99, "delivered", None),
                (4, 5, "ORD-D002", -3, 0, 45.00, "delivered", "late"),
                (4, 8, "ORD-D003", -1, None, 25.00, "in_transit", None),
                (5, 2, "ORD-E001", -20, -17, 129.00, "delivered", None),
                (5, 7, "ORD-E002", -1, None, 69.99, "processing", None),
            ]
            rows = []
            for uid, pid, ref, o_off, d_off, amt, status, issue in purchases:
                odate = time.strftime("%Y-%m-%d", time.localtime(now + o_off * 86400))
                ddate = time.strftime("%Y-%m-%d", time.localtime(now + d_off * 86400)) if d_off is not None else None
                rows.append((uid, pid, ref, odate, ddate, amt, status, issue))
            con.executemany(
                "INSERT INTO recent_purchases(user_id,product_id,order_ref,order_date,"
                "delivery_date,amount,status,issue) VALUES(?,?,?,?,?,?,?,?)",
                rows,
            )

    # ── CustomerBackend primitives ────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        with self._conn() as con:
            row = con.execute(
                "SELECT id, username, password_hash, name, email, tier FROM users WHERE username=?",
                (username,),
            ).fetchone()
        if row and row["password_hash"] == _hash(password):
            d = dict(row)
            d.pop("password_hash", None)  # never carry the secret into the session
            return d
        return None

    def get_customer(self, username: str) -> Optional[dict]:
        with self._conn() as con:
            row = con.execute(
                "SELECT id, username, name, email, tier, join_date FROM users WHERE username=?",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def _fetch_account(self, user_id) -> Optional[dict]:
        with self._conn() as con:
            row = con.execute("SELECT name, email, tier, join_date FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def _fetch_recent(self, user_id) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                """SELECT rp.order_ref, rp.order_date, rp.delivery_date, rp.amount,
                          rp.status, rp.issue, p.name AS product, p.category
                   FROM recent_purchases rp
                   JOIN products p ON rp.product_id = p.id
                   WHERE rp.user_id = ?
                   ORDER BY rp.order_date DESC LIMIT 10""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_ticket(self, user_id, ticket_type: str, purchase_id=None) -> str:
        ref = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        with self._conn() as con:
            con.execute(
                "INSERT INTO support_tickets(user_id,purchase_id,ticket_ref,ticket_type,status,created_at) "
                "VALUES(?,?,?,?,?,datetime('now'))",
                (user_id, purchase_id, ref, ticket_type, "open"),
            )
        return ref
