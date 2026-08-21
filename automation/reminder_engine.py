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
    clean_expr = expr.strip()
    if not clean_expr:
        return None

    # 1. Try dateparser first for rich natural language support ("in 5 mins", "in an hour", "tomorrow at 9")
    try:
        import dateparser
        parsed = dateparser.parse(
            clean_expr,
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now,
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if parsed and parsed > now:
            return parsed
    except Exception as exc:
        log.debug("dateparser parse failed for %r: %s", clean_expr, exc)

    # 2. Relative regex fallback: "in 30 minutes", "in 5 mins", "in 1 hr"
    rel_m = re.search(r"in\s+(\d+|an?)\s*(sec|second|min|minute|hr|hour|day)s?", clean_expr, re.I)
    if rel_m:
        count_str = rel_m.group(1).lower()
        n = 1 if count_str in ("a", "an") else int(count_str)
        unit_str = rel_m.group(2).lower()
        if unit_str.startswith("sec"):
            delta = timedelta(seconds=n)
        elif unit_str.startswith("min"):
            delta = timedelta(minutes=n)
        elif unit_str.startswith("hr") or unit_str.startswith("hour"):
            delta = timedelta(hours=n)
        else:
            delta = timedelta(days=n)
        return now + delta

    # 3. Absolute regex fallback: "at 3pm", "at 14:30"
    for pattern in _ABSOLUTE_PATTERNS:
        m = pattern.search(clean_expr)
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
            from apscheduler.jobstores.memory import MemoryJobStore
            self._scheduler = BackgroundScheduler(jobstores={"default": MemoryJobStore()})
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
        now = datetime.now()
        if trigger_at <= now:
            # If time was parsed as slightly in the past due to execution delay, nudge to future
            trigger_at = now + timedelta(seconds=2)

        db_id = models.insert_reminder(title, body, trigger_at, recurrence)

        if self._scheduler and self._running:
            try:
                job = self._scheduler.add_job(
                    self._fire,
                    trigger="date",
                    run_date=trigger_at,
                    args=[db_id, title, body],
                    id=f"reminder_{db_id}",
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                log.info("Scheduled APScheduler job '%s' -> %s", job.id, job.next_run_time)
            except Exception as exc:
                log.error("Failed to add reminder job to scheduler: %s", exc)

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
                        misfire_grace_time=300,
                    )
                    count += 1

            except Exception as exc:
                log.debug("Skip malformed reminder %s: %s", row["id"], exc)
        if count:
            log.info("Re-queued %d pending reminder(s).", count)
