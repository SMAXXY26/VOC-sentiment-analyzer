"""Generic SQL customer backend — works against any SQLAlchemy-supported database
(Postgres, MySQL, SQL Server, SQLite, …) purely from config, no code per DB.

You supply, in the YAML config:
  - connection.url  (a SQLAlchemy URL)  OR host/port/database/user/password/driver
  - mappings.customers / mappings.orders / mappings.tickets — the table (or view)
    name and the column names that hold each normalized field.

Because order history often spans multiple tables, point `mappings.orders.source`
at a flat VIEW that already joins product names in, exposing the columns below.

Requires `sqlalchemy` (lazy-imported) and the appropriate DB driver installed.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from .base import CustomerBackend
from .config import BackendConfig

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name: str, what: str) -> str:
    """Validate a table/column identifier coming from config (defends the f-string SQL)."""
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier for {what}: {name!r}")
    return name


def _hash_sha256(password: str) -> str:
    import hashlib

    return hashlib.sha256(password.encode()).hexdigest()


class SQLAlchemyBackend(CustomerBackend):
    # Default column names (overridable per field in mappings.<section>).
    _CUST_DEFAULTS = {
        "table": "users",
        "id": "id",
        "username": "username",
        "password": "password_hash",
        "name": "name",
        "email": "email",
        "tier": "tier",
        "join_date": "join_date",
    }
    _ORDER_DEFAULTS = {
        "source": "recent_purchases",
        "user_id": "user_id",
        "order_ref": "order_ref",
        "product": "product",
        "category": "category",
        "status": "status",
        "issue": "issue",
        "amount": "amount",
        "order_date": "order_date",
        "delivery_date": "delivery_date",
    }

    def __init__(self, config: BackendConfig):
        try:
            from sqlalchemy import create_engine, text
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "The 'sql' chatbot backend needs SQLAlchemy. Install it (and your DB driver), "
                "e.g. `pip install sqlalchemy psycopg2-binary`."
            ) from e
        self._text = text

        self.cust = {**self._CUST_DEFAULTS, **(config.mappings.get("customers") or {})}
        self.orders = {**self._ORDER_DEFAULTS, **(config.mappings.get("orders") or {})}
        self.tickets = config.mappings.get("tickets")  # optional (writes)
        self.opts = config.options or {}
        self.order_limit = int(self.opts.get("order_limit", 10))
        self.password_scheme = self.opts.get("password_scheme", "sha256")

        self.engine = create_engine(self._build_url(config.connection), pool_pre_ping=True)

    @staticmethod
    def _build_url(conn: dict) -> str:
        if conn.get("url"):
            return conn["url"]
        driver = conn.get("driver", "postgresql+psycopg2")
        user, pw = conn.get("user", ""), conn.get("password", "")
        host, port = conn.get("host", "localhost"), conn.get("port", "")
        db = conn.get("database", "")
        auth = f"{user}:{pw}@" if user else ""
        hostport = f"{host}:{port}" if port else host
        return f"{driver}://{auth}{hostport}/{db}"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _cust_select_cols(self) -> str:
        c = self.cust
        return (
            f"{_ident(c['id'], 'customers.id')} AS id, "
            f"{_ident(c['username'], 'customers.username')} AS username, "
            f"{_ident(c['name'], 'customers.name')} AS name, "
            f"{_ident(c['email'], 'customers.email')} AS email, "
            f"{_ident(c['tier'], 'customers.tier')} AS tier, "
            f"{_ident(c['join_date'], 'customers.join_date')} AS join_date"
        )

    def _verify_password(self, plain: str, stored: str) -> bool:
        if stored is None:
            return False
        if self.password_scheme == "plain":
            return plain == stored
        return _hash_sha256(plain) == stored

    # ── CustomerBackend primitives ────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        c = self.cust
        sql = self._text(
            f"SELECT {self._cust_select_cols()}, {_ident(c['password'], 'customers.password')} AS _pw "
            f"FROM {_ident(c['table'], 'customers.table')} "
            f"WHERE {_ident(c['username'], 'customers.username')} = :u"
        )
        with self.engine.connect() as conn:
            row = conn.execute(sql, {"u": username}).mappings().first()
        if row and self._verify_password(password, row["_pw"]):
            d = dict(row)
            d.pop("_pw", None)
            return d
        return None

    def get_customer(self, username: str) -> Optional[dict]:
        c = self.cust
        sql = self._text(
            f"SELECT {self._cust_select_cols()} FROM {_ident(c['table'], 'customers.table')} "
            f"WHERE {_ident(c['username'], 'customers.username')} = :u"
        )
        with self.engine.connect() as conn:
            row = conn.execute(sql, {"u": username}).mappings().first()
        return dict(row) if row else None

    def _fetch_account(self, user_id) -> Optional[dict]:
        c = self.cust
        sql = self._text(
            f"SELECT {_ident(c['name'], 'customers.name')} AS name, "
            f"{_ident(c['email'], 'customers.email')} AS email, "
            f"{_ident(c['tier'], 'customers.tier')} AS tier, "
            f"{_ident(c['join_date'], 'customers.join_date')} AS join_date "
            f"FROM {_ident(c['table'], 'customers.table')} "
            f"WHERE {_ident(c['id'], 'customers.id')} = :uid"
        )
        with self.engine.connect() as conn:
            row = conn.execute(sql, {"uid": user_id}).mappings().first()
        return dict(row) if row else None

    def _fetch_recent(self, user_id) -> list[dict]:
        o = self.orders
        cols = ", ".join(
            f"{_ident(o[k], f'orders.{k}')} AS {k}"
            for k in ("order_ref", "product", "category", "status", "issue", "amount", "order_date", "delivery_date")
        )
        sql = self._text(
            f"SELECT {cols} FROM {_ident(o['source'], 'orders.source')} "
            f"WHERE {_ident(o['user_id'], 'orders.user_id')} = :uid "
            f"ORDER BY {_ident(o['order_date'], 'orders.order_date')} DESC LIMIT :lim"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql, {"uid": user_id, "lim": self.order_limit}).mappings().all()
        return [dict(r) for r in rows]

    def create_ticket(self, user_id, ticket_type: str, purchase_id=None) -> str:
        ref = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        if not self.tickets:  # read-only DB / no tickets table configured
            return ref  # best-effort ref so the chatbot still confirms; not persisted
        t = self.tickets
        sql = self._text(
            f"INSERT INTO {_ident(t['table'], 'tickets.table')} "
            f"({_ident(t['user_id'], 'tickets.user_id')}, {_ident(t['ticket_ref'], 'tickets.ticket_ref')}, "
            f"{_ident(t['ticket_type'], 'tickets.ticket_type')}) VALUES (:uid, :ref, :ttype)"
        )
        with self.engine.begin() as conn:
            conn.execute(sql, {"uid": user_id, "ref": ref, "ttype": ticket_type})
        return ref
