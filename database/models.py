"""
database/models.py
Data-access helpers (thin wrappers around raw SQL).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from .db import get_connection


# ── Memories ──────────────────────────────────────────────────────────────────

def insert_memory(content: str, summary: str = "", tags: str = "", importance: float = 0.5) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO memories (content, summary, tags, importance) VALUES (?, ?, ?, ?)",
        (content, summary, tags, importance),
    )
    conn.commit()
    return cur.lastrowid


def fetch_recent_memories(limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM memories ORDER BY accessed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def search_memories_by_tag(tag: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM memories WHERE tags LIKE ? ORDER BY importance DESC",
        (f"%{tag}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_memory(memory_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE memories SET accessed_at = datetime('now') WHERE id = ?", (memory_id,)
    )
    conn.commit()


def delete_memory(memory_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()


# ── Reminders ─────────────────────────────────────────────────────────────────

def insert_reminder(title: str, body: str, trigger_at: datetime, recurrence: Optional[str] = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO reminders (title, body, trigger_at, recurrence) VALUES (?, ?, ?, ?)",
        (title, body, trigger_at.isoformat(), recurrence),
    )
    conn.commit()
    return cur.lastrowid


def fetch_pending_reminders() -> list[dict]:
    conn = get_connection()
    now = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE done = 0 AND trigger_at <= ? ORDER BY trigger_at",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_all_reminders() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM reminders ORDER BY trigger_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_done(reminder_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()


def delete_reminder(reminder_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()


# ── Events ────────────────────────────────────────────────────────────────────

def log_event(event_type: str, data: dict | None = None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO events (type, data) VALUES (?, ?)",
        (event_type, json.dumps(data or {})),
    )
    conn.commit()


def fetch_events(limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY occurred_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Settings ──────────────────────────────────────────────────────────────────

def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, value),
    )
    conn.commit()


def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default
