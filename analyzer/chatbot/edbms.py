"""Dummy EDBMS — SQLite-backed customer database for the chatbot.

Auto-created and seeded on first import. Provides authentication and
keyword-aware purchase history queries for the agent's reasoning loop.

Demo users: alice/pass123, bob/pass123, carol/pass123, dave/pass123, eve/pass123
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

_DB_PATH = os.path.join(os.path.dirname(__file__), "edbms.db")

# Query/filler words to ignore when keyword-filtering orders, so generic phrasings
# ("what is the status of my order?") fall through to "show recent orders" instead
# of spuriously matching a product/category substring. Product/issue words (shoes,
# damaged, late, missing…) are deliberately NOT here so they still filter.
_STOPWORDS = {
    "what",
    "when",
    "where",
    "which",
    "status",
    "order",
    "orders",
    "mine",
    "have",
    "with",
    "will",
    "your",
    "about",
    "please",
    "want",
    "need",
    "tell",
    "show",
    "give",
    "could",
    "would",
    "there",
    "here",
    "from",
    "like",
    "just",
    "also",
    "some",
    "this",
    "that",
    "they",
    "them",
    "does",
    "recent",
    "latest",
    "update",
}


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


@contextmanager
def _conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_schema() -> None:
    with _conn() as con:
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
        -- status: processing | in_transit | delivered | cancelled
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


def _seed() -> None:
    with _conn() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return  # already seeded

        users = [
            ("alice", _hash("pass123"), "Alice Nguyen", "alice@example.com", "premium"),
            ("bob", _hash("pass123"), "Bob Smith", "bob@example.com", "standard"),
            ("carol", _hash("pass123"), "Carol Davis", "carol@example.com", "vip"),
            ("dave", _hash("pass123"), "Dave Lee", "dave@example.com", "standard"),
            ("eve", _hash("pass123"), "Eve Martinez", "eve@example.com", "premium"),
        ]
        con.executemany(
            "INSERT INTO users(username,password_hash,name,email,tier,join_date) VALUES(?,?,?,?,?,date('now','-'||abs(random()%730)||' days'))",
            users,
        )

        products = [
            ("Wireless Headphones", "Electronics", 89.99),
            ("Running Shoes", "Footwear", 129.00),
            ("Coffee Maker", "Appliances", 59.99),
            ("Yoga Mat", "Fitness", 35.00),
            ("Desk Lamp", "Home Office", 45.00),
            ("Protein Powder", "Nutrition", 49.99),
            ("Gaming Mouse", "Electronics", 69.99),
            ("Water Bottle", "Fitness", 25.00),
        ]
        con.executemany(
            "INSERT INTO products(name,category,price) VALUES(?,?,?)",
            products,
        )

        now = time.time()
        purchases = [
            # (user_id, product_id, order_ref, order_date_offset_days, delivery_offset, amount, status, issue)
            # status: processing | in_transit | out_for_delivery | delivered | cancelled
            # Each user has at least one *live* (not-yet-delivered) order so "what's my
            # order status?" has something current to report ("on the way", etc.).
            (1, 1, "ORD-A001", -30, -27, 89.99, "delivered", None),
            (1, 5, "ORD-A002", -14, -11, 45.00, "delivered", None),
            (1, 3, "ORD-A003", -3, 0, 59.99, "delivered", "damaged"),
            (1, 7, "ORD-A004", -1, None, 69.99, "out_for_delivery", None),  # alice: on the way today
            (1, 4, "ORD-A005", 0, None, 35.00, "processing", None),  # alice: just placed
            (2, 2, "ORD-B001", -60, -57, 129.00, "delivered", None),
            (2, 7, "ORD-B002", -7, -4, 69.99, "delivered", "wrong_item"),
            (2, 4, "ORD-B003", -1, None, 35.00, "in_transit", None),
            (3, 6, "ORD-C001", -10, -7, 49.99, "delivered", None),
            (3, 8, "ORD-C002", -5, -2, 25.00, "delivered", "missing"),
            (3, 1, "ORD-C003", -2, 0, 89.99, "delivered", None),
            (3, 2, "ORD-C004", -1, None, 129.00, "out_for_delivery", None),  # carol: on the way
            (4, 3, "ORD-D001", -45, -42, 59.99, "delivered", None),
            (4, 5, "ORD-D002", -3, 0, 45.00, "delivered", "late"),
            (4, 8, "ORD-D003", -1, None, 25.00, "in_transit", None),  # dave: in transit
            (5, 2, "ORD-E001", -20, -17, 129.00, "delivered", None),
            (5, 7, "ORD-E002", -1, None, 69.99, "processing", None),
        ]
        rows = []
        for uid, pid, ref, o_off, d_off, amt, status, issue in purchases:
            odate = time.strftime("%Y-%m-%d", time.localtime(now + o_off * 86400))
            ddate = time.strftime("%Y-%m-%d", time.localtime(now + d_off * 86400)) if d_off is not None else None
            rows.append((uid, pid, ref, odate, ddate, amt, status, issue))
        con.executemany(
            "INSERT INTO recent_purchases(user_id,product_id,order_ref,order_date,delivery_date,amount,status,issue) VALUES(?,?,?,?,?,?,?,?)",
            rows,
        )


# ── Init on import ─────────────────────────────────────────────────────────────

_init_schema()
_seed()


# ── Public API ─────────────────────────────────────────────────────────────────


def authenticate(username: str, password: str) -> Optional[dict]:
    """Return customer dict if credentials match, else None."""
    with _conn() as con:
        row = con.execute(
            "SELECT id, username, password_hash, name, email, tier FROM users WHERE username=?",
            (username,),
        ).fetchone()
    if row and row["password_hash"] == _hash(password):
        return dict(row)
    return None


def get_customer(username: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT id, username, name, email, tier, join_date FROM users WHERE username=?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def get_account_info(user_id: int) -> dict:
    """Account profile plus a rollup of the customer's orders, for the chatbot to
    report from ("you're a premium member with 5 orders, 2 still on the way")."""
    with _conn() as con:
        row = con.execute("SELECT name, email, tier, join_date FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return {}
        info = dict(row)
        counts = con.execute(
            """SELECT COUNT(*) AS total_orders,
                      SUM(CASE WHEN status IN ('processing','in_transit','out_for_delivery')
                               THEN 1 ELSE 0 END) AS active_orders
               FROM recent_purchases WHERE user_id=?""",
            (user_id,),
        ).fetchone()
    info["total_orders"] = counts["total_orders"] or 0
    info["active_orders"] = counts["active_orders"] or 0
    return info


def get_recent_purchases(user_id: int, keywords: str = "") -> list[dict]:
    """Return recent purchases for user_id, optionally filtered by keywords.
    Keyword matching checks product name, category, status, and issue columns.
    """
    with _conn() as con:
        rows = con.execute(
            """SELECT rp.order_ref, rp.order_date, rp.delivery_date, rp.amount,
                      rp.status, rp.issue, p.name as product, p.category
               FROM recent_purchases rp
               JOIN products p ON rp.product_id = p.id
               WHERE rp.user_id = ?
               ORDER BY rp.order_date DESC LIMIT 10""",
            (user_id,),
        ).fetchall()

    results = [dict(r) for r in rows]

    if keywords and keywords.strip():
        # Only match on meaningful tokens: drop stopwords and very short words so
        # "status **of** my order" doesn't spuriously match "Home **Of**fice" and
        # hide the live orders. When nothing meaningful matches, fall through to
        # returning all recent orders (most-recent-first), which surfaces the
        # active ones for generic "what's my order status?" questions.
        kws = {k.lower() for k in keywords.split() if len(k) >= 4 and k.lower() not in _STOPWORDS}
        filtered = [
            r
            for r in results
            if any(
                kw in (r.get("product") or "").lower()
                or kw in (r.get("category") or "").lower()
                or kw in (r.get("status") or "").lower()
                or kw in (r.get("issue") or "").lower()
                for kw in kws
            )
        ]
        if filtered:
            return filtered

    return results


def create_ticket(user_id: int, ticket_type: str, purchase_id: Optional[int] = None) -> str:
    """Create a support ticket and return its reference ID."""
    import uuid

    ref = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    with _conn() as con:
        con.execute(
            "INSERT INTO support_tickets(user_id,purchase_id,ticket_ref,ticket_type,status,created_at) VALUES(?,?,?,?,?,datetime('now'))",
            (user_id, purchase_id, ref, ticket_type, "open"),
        )
    return ref
