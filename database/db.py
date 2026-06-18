"""
database/db.py
SQLite connection pool + schema migrations for Saturday.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from threading import local

log = logging.getLogger(__name__)

# ── Path ──────────────────────────────────────────────────────────────────────
_APP_DATA = Path(os.getenv("APPDATA", Path.home())) / "Saturday"
_DB_PATH = _APP_DATA / "saturday.db"

# Thread-local connection storage
_local = local()


def _db_path() -> Path:
    _APP_DATA.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (creates if absent)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def close_connection() -> None:
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


# ── Migrations ────────────────────────────────────────────────────────────────

_MIGRATIONS: list[str] = [
    # v1 – initial schema
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS memories (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        content     TEXT    NOT NULL,
        summary     TEXT,
        embedding   BLOB,
        tags        TEXT    DEFAULT '',
        importance  REAL    DEFAULT 0.5,
        created_at  TEXT    DEFAULT (datetime('now')),
        accessed_at TEXT    DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS reminders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT    NOT NULL,
        body        TEXT    DEFAULT '',
        trigger_at  TEXT    NOT NULL,
        recurrence  TEXT    DEFAULT NULL,
        done        INTEGER DEFAULT 0,
        created_at  TEXT    DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        type        TEXT    NOT NULL,
        data        TEXT    DEFAULT '{}',
        occurred_at TEXT    DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT DEFAULT (datetime('now'))
    );
    """,
]


def initialize() -> None:
    """Run all pending migrations."""
    conn = get_connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    conn.commit()

    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] if row[0] is not None else -1

    for idx, sql in enumerate(_MIGRATIONS):
        if idx > current:
            log.info("Applying migration v%d", idx + 1)
            conn.executescript(sql)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (idx,)
            )
            conn.commit()

    log.info("Database ready at %s", _db_path())
