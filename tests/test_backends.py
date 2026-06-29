"""Tests for the pluggable chatbot customer-data backends.

Covers the SQLite reference adapter, config loading + env expansion, the factory,
and the generic SQL adapter (against a temp SQLite DB with a deliberately
*different* schema, proving config-driven column mapping). CI-safe: no external DB.
"""

import sqlite3

import pytest
import yaml

from analyzer.chatbot import edbms
from analyzer.chatbot.backends import get_backend, load_config, reset_backend
from analyzer.chatbot.backends.base import ACTIVE_STATUSES, keyword_filter
from analyzer.chatbot.backends.config import BackendConfig, _expand
from analyzer.chatbot.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def sqlite_be(tmp_path):
    return SQLiteBackend(BackendConfig(connection={"path": str(tmp_path / "demo.db")}))


# ── SQLite reference backend ────────────────────────────────────────────────────


class TestSQLiteBackend:
    def test_authenticate_ok(self, sqlite_be):
        c = sqlite_be.authenticate("alice", "pass123")
        assert c["name"] == "Alice Nguyen"
        assert c["tier"] == "premium"
        assert "password_hash" not in c  # secret must not leak into the session

    def test_authenticate_bad_password(self, sqlite_be):
        assert sqlite_be.authenticate("alice", "wrong") is None

    def test_account_info_rollup(self, sqlite_be):
        uid = sqlite_be.authenticate("alice", "pass123")["id"]
        info = sqlite_be.get_account_info(uid)
        assert info["tier"] == "premium"
        assert info["total_orders"] == 5
        assert info["active_orders"] == 2  # out_for_delivery + processing

    def test_recent_purchases_surfaces_active_first(self, sqlite_be):
        uid = sqlite_be.authenticate("alice", "pass123")["id"]
        # generic status query → stopwords drop out → all recent, newest first
        orders = sqlite_be.get_recent_purchases(uid, keywords="what is the status of my order")
        assert orders[0]["status"] in ACTIVE_STATUSES

    def test_recent_purchases_keyword_filter(self, sqlite_be):
        uid = sqlite_be.authenticate("alice", "pass123")["id"]
        coffee = sqlite_be.get_recent_purchases(uid, keywords="coffee maker")
        assert all("coffee" in o["product"].lower() for o in coffee)

    def test_create_ticket_returns_ref(self, sqlite_be):
        uid = sqlite_be.authenticate("alice", "pass123")["id"]
        ref = sqlite_be.create_ticket(uid, "refund")
        assert ref.startswith("TKT-")


# ── keyword filter helper ───────────────────────────────────────────────────────


class TestKeywordFilter:
    rows = [
        {"product": "Coffee Maker", "category": "Appliances", "status": "delivered", "issue": "damaged"},
        {"product": "Gaming Mouse", "category": "Electronics", "status": "out_for_delivery", "issue": None},
    ]

    def test_empty_keywords_returns_all(self):
        assert keyword_filter(self.rows, "") == self.rows

    def test_only_stopwords_returns_all(self):
        assert keyword_filter(self.rows, "what is the status of my order") == self.rows

    def test_meaningful_token_filters(self):
        out = keyword_filter(self.rows, "coffee")
        assert len(out) == 1 and out[0]["product"] == "Coffee Maker"


# ── config loading ──────────────────────────────────────────────────────────────


class TestConfig:
    def test_default_is_sqlite(self, monkeypatch):
        monkeypatch.delenv("CHATBOT_DB_CONFIG", raising=False)
        monkeypatch.delenv("CHATBOT_DB_BACKEND", raising=False)
        assert load_config().backend == "sqlite"

    def test_env_overrides_backend(self, monkeypatch):
        monkeypatch.delenv("CHATBOT_DB_CONFIG", raising=False)
        monkeypatch.setenv("CHATBOT_DB_BACKEND", "sql")
        assert load_config().backend == "sql"

    def test_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("DB_PASS", "s3cret")
        assert _expand({"password": "${DB_PASS}"}) == {"password": "s3cret"}

    def test_yaml_file_loaded(self, tmp_path, monkeypatch):
        cfg = tmp_path / "db.yaml"
        cfg.write_text(yaml.safe_dump({"backend": "sqlite", "connection": {"path": "/data/x.db"}}))
        monkeypatch.setenv("CHATBOT_DB_CONFIG", str(cfg))
        loaded = load_config()
        assert loaded.backend == "sqlite"
        assert loaded.connection["path"] == "/data/x.db"

    def test_missing_config_file_raises(self, monkeypatch):
        monkeypatch.setenv("CHATBOT_DB_CONFIG", "/nope/missing.yaml")
        with pytest.raises(FileNotFoundError):
            load_config()


# ── factory + facade ────────────────────────────────────────────────────────────


def _point_at_sqlite(tmp_path, monkeypatch):
    cfg = tmp_path / "db.yaml"
    cfg.write_text(yaml.safe_dump({"backend": "sqlite", "connection": {"path": str(tmp_path / "f.db")}}))
    monkeypatch.setenv("CHATBOT_DB_CONFIG", str(cfg))
    reset_backend()


class TestFactoryAndFacade:
    def teardown_method(self):
        reset_backend()

    def test_factory_returns_sqlite(self, tmp_path, monkeypatch):
        _point_at_sqlite(tmp_path, monkeypatch)
        assert isinstance(get_backend(), SQLiteBackend)

    def test_facade_delegates(self, tmp_path, monkeypatch):
        _point_at_sqlite(tmp_path, monkeypatch)
        assert edbms.authenticate("alice", "pass123")["name"] == "Alice Nguyen"

    def test_unknown_backend_raises(self, tmp_path, monkeypatch):
        cfg = tmp_path / "db.yaml"
        cfg.write_text(yaml.safe_dump({"backend": "mongo"}))
        monkeypatch.setenv("CHATBOT_DB_CONFIG", str(cfg))
        reset_backend()
        with pytest.raises(ValueError, match="Unknown chatbot DB backend"):
            get_backend()


# ── generic SQL adapter (config-mapped) against a different schema ──────────────


def _make_custom_db(path):
    """A DB whose table/column names differ from the chatbot's defaults."""
    import hashlib

    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE members (member_id INTEGER PRIMARY KEY, login TEXT, secret TEXT,
                              full_name TEXT, mail TEXT, plan TEXT, since TEXT);
        CREATE TABLE order_log (owner INTEGER, ref TEXT, item TEXT, cat TEXT,
                                state TEXT, problem TEXT, total REAL, placed TEXT, delivered TEXT);
    """)
    pw = hashlib.sha256(b"hunter2").hexdigest()
    con.execute("INSERT INTO members VALUES (1,'zoe',?,'Zoe Quinn','zoe@x.com','gold','2023-01-01')", (pw,))
    con.executemany(
        "INSERT INTO order_log VALUES (1,?,?,?,?,?,?,?,?)",
        [
            ("OL-1", "Lamp", "Home", "out_for_delivery", None, 20.0, "2024-06-01", None),
            ("OL-2", "Book", "Media", "delivered", None, 12.0, "2024-05-01", "2024-05-03"),
        ],
    )
    con.commit()
    con.close()


class TestSQLAlchemyBackend:
    def _backend(self, db_path):
        pytest.importorskip("sqlalchemy")
        from analyzer.chatbot.backends.sql_backend import SQLAlchemyBackend

        _make_custom_db(db_path)
        cfg = BackendConfig(
            backend="sql",
            connection={"url": f"sqlite:///{db_path}"},
            mappings={
                "customers": {
                    "table": "members",
                    "id": "member_id",
                    "username": "login",
                    "password": "secret",
                    "name": "full_name",
                    "email": "mail",
                    "tier": "plan",
                    "join_date": "since",
                },
                "orders": {
                    "source": "order_log",
                    "user_id": "owner",
                    "order_ref": "ref",
                    "product": "item",
                    "category": "cat",
                    "status": "state",
                    "issue": "problem",
                    "amount": "total",
                    "order_date": "placed",
                    "delivery_date": "delivered",
                },
            },
        )
        return SQLAlchemyBackend(cfg)

    def test_authenticate_via_mappings(self, tmp_path):
        be = self._backend(tmp_path / "custom.db")
        c = be.authenticate("zoe", "hunter2")
        assert c["name"] == "Zoe Quinn" and c["tier"] == "gold"
        assert be.authenticate("zoe", "nope") is None

    def test_account_and_orders_normalized(self, tmp_path):
        be = self._backend(tmp_path / "custom.db")
        info = be.get_account_info(1)
        assert info["total_orders"] == 2 and info["active_orders"] == 1
        orders = be.get_recent_purchases(1)
        assert orders[0]["order_ref"] == "OL-1"  # newest first
        assert orders[0]["product"] == "Lamp"

    def test_create_ticket_without_tickets_table(self, tmp_path):
        be = self._backend(tmp_path / "custom.db")
        # no tickets mapping → best-effort ref, not persisted, but never raises
        assert be.create_ticket(1, "refund").startswith("TKT-")
