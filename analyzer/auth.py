"""Dashboard operator authentication — SQLite-backed users + stateless tokens.

Separate from the chatbot EDBMS `users` table (which holds *customers*). Operator
credentials live in a `dashboard_users` table in the same SQLite file, hashed with
salted PBKDF2. Login issues an HMAC-signed, expiring bearer token (stateless — no
session store, so it works across k3s replicas).

Bootstrap: on first init, if no operators exist, one is seeded from
DASHBOARD_ADMIN_USER / DASHBOARD_ADMIN_PASSWORD (default admin/admin — override in
prod). Add more with `python -m analyzer.auth add <user> <password>`.

Env:
  AUTH_SECRET             secret for signing tokens (set in prod; dev fallback warns)
  AUTH_TOKEN_TTL          token lifetime in seconds (default 86400 = 24h)
  DASHBOARD_ADMIN_USER    bootstrap admin username (default "admin")
  DASHBOARD_ADMIN_PASSWORD bootstrap admin password (default "admin")
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
import time
import warnings
from contextlib import contextmanager
from typing import Optional

_DB_PATH = os.path.join(os.path.dirname(__file__), "chatbot", "edbms.db")
_PBKDF2_ROUNDS = 200_000
_TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL", "86400"))


def _secret() -> bytes:
    s = os.getenv("AUTH_SECRET")
    if not s:
        warnings.warn(
            "AUTH_SECRET is not set — using an insecure dev default. Set AUTH_SECRET in production.",
            stacklevel=2,
        )
        s = "dev-insecure-secret-change-me"
    return s.encode()


@contextmanager
def _conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ── Password hashing (salted PBKDF2) ─────────────────────────────────────────────


def _hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return dk.hex()


def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    return hmac.compare_digest(_hash_password(password, salt), hash_hex)


# ── Schema + bootstrap ──────────────────────────────────────────────────────────


def _init() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_users (
                id            INTEGER PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                salt          TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT DEFAULT 'admin',
                created_at    TEXT DEFAULT (datetime('now'))
            )
        """)
        count = con.execute("SELECT COUNT(*) FROM dashboard_users").fetchone()[0]
    if count == 0:
        admin_user = os.getenv("DASHBOARD_ADMIN_USER", "admin")
        admin_pass = os.getenv("DASHBOARD_ADMIN_PASSWORD", "admin")
        create_user(admin_user, admin_pass, role="admin")
        if admin_pass == "admin":
            warnings.warn(
                "Seeded dashboard admin with default password 'admin' — "
                "set DASHBOARD_ADMIN_PASSWORD before exposing the dashboard.",
                stacklevel=2,
            )


def create_user(username: str, password: str, role: str = "admin") -> None:
    salt = os.urandom(16)
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO dashboard_users(username,salt,password_hash,role) VALUES(?,?,?,?)",
            (username, salt.hex(), _hash_password(password, salt), role),
        )


def verify_credentials(username: str, password: str) -> Optional[dict]:
    """Return {username, role} on success, else None.

    Checks dashboard_users first (operators), then falls through to EDBMS
    customers so a single login page works for both operator and customer accounts.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT username, salt, password_hash, role FROM dashboard_users WHERE username=?",
            (username,),
        ).fetchone()
    if row and _verify_password(password, row["salt"], row["password_hash"]):
        return {"username": row["username"], "role": row["role"]}

    # Fall through to EDBMS customer accounts.
    try:
        from .chatbot.edbms import authenticate as edbms_auth
        result = edbms_auth(username, password)
        if result:
            return {"username": username, "role": "customer"}
    except Exception:
        pass
    return None


# ── Stateless bearer tokens (HMAC-signed) ────────────────────────────────────────


def _sign(payload: str) -> str:
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def issue_token(username: str, ttl: Optional[int] = None) -> dict:
    exp = int(time.time()) + (ttl or _TOKEN_TTL)
    payload = f"{username}:{exp}"
    token = f"{base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')}.{_sign(payload)}"
    return {"token": token, "username": username, "expires_at": exp}


def verify_token(token: str) -> Optional[str]:
    """Return the username if the token is valid and unexpired, else None."""
    try:
        body, sig = token.rsplit(".", 1)
        padded = body + "=" * (-len(body) % 4)
        payload = base64.urlsafe_b64decode(padded).decode()
        username, exp = payload.rsplit(":", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if int(exp) < int(time.time()):
            return None
        return username
    except Exception:
        return None


# Initialise on import so the dashboard login works out of the box.
_init()


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 4 and sys.argv[1] == "add":
        create_user(sys.argv[2], sys.argv[3])
        print(f"Created dashboard user '{sys.argv[2]}'.")
    else:
        print("usage: python -m analyzer.auth add <username> <password>")
