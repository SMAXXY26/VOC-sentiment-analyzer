"""Chatbot DB backend configuration.

Config is read once at startup from a YAML file (path in `$CHATBOT_DB_CONFIG`),
with environment overrides. If no file is given, the bundled SQLite demo backend
is used — so the system works out of the box and only needs a config to point at
a real database.

`${VAR}` references inside the `connection` block are expanded from the
environment, so secrets stay out of the file. See
`config/chatbot_db.example.yaml`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_ENV_RE = re.compile(r"\$\{([^}{]+)\}")


def _expand(value):
    """Recursively expand ${ENV_VAR} references in strings/dicts/lists."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class BackendConfig:
    backend: str = "sqlite"  # sqlite | sql
    connection: dict = field(default_factory=dict)
    mappings: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)


def load_config() -> BackendConfig:
    """Build a BackendConfig from $CHATBOT_DB_CONFIG (YAML) + env overrides."""
    data: dict = {}
    path = os.getenv("CHATBOT_DB_CONFIG")
    if path:
        if not os.path.exists(path):
            raise FileNotFoundError(f"CHATBOT_DB_CONFIG points to a missing file: {path}")
        import yaml  # lazy (PyYAML); only needed when a config file is used

        with open(path) as f:
            data = yaml.safe_load(f) or {}

    backend = os.getenv("CHATBOT_DB_BACKEND", data.get("backend", "sqlite"))
    connection = _expand(data.get("connection") or {})
    # Single-variable convenience override for the SQLAlchemy URL.
    if os.getenv("CHATBOT_DB_URL"):
        connection["url"] = os.getenv("CHATBOT_DB_URL")

    return BackendConfig(
        backend=backend,
        connection=connection,
        mappings=data.get("mappings") or {},
        options=data.get("options") or {},
    )
