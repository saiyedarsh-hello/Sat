"""
automation/reminder_engine.py
APScheduler-based reminder daemon.
Stores reminders in SQLite; fires them as Qt signals via a callback.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Callable, Optional

from database import models

log = logging.getLogger(__name__)

# ── Time expression parser ─────────────────────────────────────────────────────

_RELATIVE_PATTERNS = [
    (re.compile(r"in\s+(\d+)\s+second", re.I),  "seconds"),
    (re.compile(r"in\s+(\d+)\s+minute", re.I),  "minutes"),
    (re.compile(r"in\s+(\d+)\s+hour",   re.I),  "hours"),
    (re.compile(r"in\s+(\d+)\s+day",    re.I),  "days"),
]

_ABSOLUTE_PATTERNS = [
    re.compile(r"at\s+(\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
    re.compile(r"at\s+(\d{1,2})\s*(am|pm)", re.I),
]


def _parse_time_expr(expr: str) -> Optional[datetime]:
    """Parse natural time expression into a future datetime."""
    now = datetime.now()

    # Relative: "in 30 minutes"
    for pattern, unit in _RELATIVE_PATTERNS:
        m = pattern.search(expr)
        if m:
            n = int(m.group(1))
            delta = timedelta(**{unit: n})
            return now + delta

    # Absolute: "at 3pm", "at 14:30"
    for pattern in _ABSOLUTE_PATTERNS:
        m = pattern.search(expr)
        if m:
            groups = m.groups()
            hour = int(groups[0])
            minute = int(groups[1]) if len(groups) > 2 and groups[1] else 0
            meridiem = (groups[-1] or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            trigger = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if trigger <= now:
                trigger += timedelta(days=1)
            return trigger

    return None


class ReminderEngine:
    """Schedules and fires reminders using APScheduler."""

    def __init__(self, fire_callback: Callable[[str, str], None] | None = None) -> None:
        self._callback = fire_callback
        self._scheduler = None
        self._running = False

    def start(self) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
                import os
                from pathlib import Path
                db_url = "sqlite:///" + str(
                    Path(os.getenv("APPDATA", Path.home())) / "Saturday" / "saturday.db"
                )
                jobstores = {"default": SQLAlchemyJobStore(url=db_url, tablename="apscheduler_jobs")}
            except Exception:
                from apscheduler.jobstores.memory import MemoryJobStore
                jobstores = {"default": MemoryJobStore()}
                log.warning("SQLAlchemy jobstore unavailable — using in-memory jobstore.")
            self._scheduler = BackgroundScheduler(jobstores=jobstores)
            self._scheduler.start()
            self._running = True
            log.info("ReminderEngine started.")
            self._reload_pending()
        except ImportError:
            log.warning("APScheduler not installed — reminders disabled.")
        except Exception as exc:
            log.error("ReminderEngine start error: %s", exc)

    def stop(self) -> None:
        if self._scheduler and self._running:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
            self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def add_from_text(self, title: str, time_expr: str) -> str:
        """Parse a time expression and schedule a reminder. Returns confirmation string."""
        trigger_dt = _parse_time_expr(time_expr)
        if trigger_dt is None:
            return (f"I got your reminder request, "
                    f"but I couldn't parse the time. Try 'in 30 minutes' or 'at 3pm'.")
        return self.add(title, "", trigger_dt)

    def add(self, title: str, body: str, trigger_at: datetime,
            recurrence: str | None = None) -> str:
        """Schedule a reminder and persist to SQLite."""
        db_id = models.insert_reminder(title, body, trigger_at, recurrence)

        if self._scheduler and self._running:
            self._scheduler.add_job(
                self._fire,
                trigger="date",
                run_date=trigger_at,
                args=[db_id, title, body],
                id=f"reminder_{db_id}",
                replace_existing=True,
            )

        fmt = trigger_at.strftime("%I:%M %p on %b %d")
        log.info("Reminder set: '%s' at %s", title, fmt)
        return f'Reminder set: "{title}" at {fmt}.'

    def list_upcoming(self, limit: int = 5) -> list[str]:
        """Return upcoming reminder strings for display."""
        rows = models.fetch_all_reminders()
        upcoming = []
        now = datetime.now().isoformat()
        for row in rows:
            if row["done"] == 0 and row["trigger_at"] >= now:
                dt = datetime.fromisoformat(row["trigger_at"])
                upcoming.append(f'{row["title"]} — {dt.strftime("%I:%M %p, %b %d")}')
        return upcoming[:limit]

    def _fire(self, reminder_id: int, title: str, body: str) -> None:
        log.info("Reminder fired: %s", title)
        models.mark_reminder_done(reminder_id)
        if self._callback:
            self._callback(title, body or "Reminder!")

    def _reload_pending(self) -> None:
        """Re-queue any future reminders from SQLite on startup."""
        if not self._scheduler:
            return
        rows = models.fetch_all_reminders()
        now = datetime.now()
        count = 0
        for row in rows:
            if row["done"]:
                continue
            try:
                dt = datetime.fromisoformat(row["trigger_at"])
                if dt > now:
                    self._scheduler.add_job(
                        self._fire,
                        trigger="date",
                        run_date=dt,
                        args=[row["id"], row["title"], row["body"]],
                        id=f"reminder_{row['id']}",
                        replace_existing=True,
                    )
                    count += 1
            except Exception as exc:
                log.debug("Skip malformed reminder %s: %s", row["id"], exc)
        if count:
            log.info("Re-queued %d pending reminder(s).", count)
