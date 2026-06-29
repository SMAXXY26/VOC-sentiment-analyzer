"""Customer-data access for the chatbot — a thin facade over the pluggable backend.

Historically this module *was* the SQLite EDBMS. The implementation now lives in
`analyzer/chatbot/backends/` and is selected by config (SQLite demo by default;
any SQL database via `backends/sql_backend.py`). These module-level functions
delegate to the configured backend so existing call sites keep working unchanged.

To point the chatbot at a real database, set `CHATBOT_DB_CONFIG` to a YAML file
(see `config/chatbot_db.example.yaml`).

Demo users (SQLite backend): alice/bob/carol/dave/eve — password `pass123`.
"""

from __future__ import annotations

from typing import Optional

from .backends import get_backend


def authenticate(username: str, password: str) -> Optional[dict]:
    return get_backend().authenticate(username, password)


def get_customer(username: str) -> Optional[dict]:
    return get_backend().get_customer(username)


def get_account_info(user_id) -> dict:
    return get_backend().get_account_info(user_id)


def get_recent_purchases(user_id, keywords: str = "") -> list[dict]:
    return get_backend().get_recent_purchases(user_id, keywords)


def create_ticket(user_id, ticket_type: str, purchase_id=None) -> str:
    return get_backend().create_ticket(user_id, ticket_type, purchase_id)
