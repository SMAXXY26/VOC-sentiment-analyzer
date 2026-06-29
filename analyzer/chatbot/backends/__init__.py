"""Pluggable customer-data backends for the chatbot.

`get_backend()` returns the configured backend (a `CustomerBackend`), chosen from
config: SQLite demo by default, or the generic SQL adapter when configured. To add
a new database, implement `CustomerBackend` and route to it here.
"""

from __future__ import annotations

from functools import lru_cache

from .base import CustomerBackend
from .config import BackendConfig, load_config


@lru_cache(maxsize=1)
def get_backend() -> CustomerBackend:
    cfg = load_config()
    name = (cfg.backend or "sqlite").lower()
    if name in ("sqlite", "demo"):
        from .sqlite_backend import SQLiteBackend

        return SQLiteBackend(cfg)
    if name in ("sql", "sqlalchemy"):
        from .sql_backend import SQLAlchemyBackend

        return SQLAlchemyBackend(cfg)
    raise ValueError(f"Unknown chatbot DB backend: {cfg.backend!r} (expected 'sqlite' or 'sql')")


def reset_backend() -> None:
    """Drop the cached backend so the next get_backend() re-reads config (tests/reload)."""
    get_backend.cache_clear()


__all__ = ["CustomerBackend", "BackendConfig", "load_config", "get_backend", "reset_backend"]
