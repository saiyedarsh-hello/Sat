"""
ai/intent_result.py
Canonical result types and the safe_handler decorator used across every
Saturday intent handler.

Design rules:
  - All _handle_* methods must be decorated with @safe_handler.
  - Any unhandled exception → logged with full traceback + spoken apology.
    Never a silent swallow, never a raw exception string in the response.
  - Known, user-facing ValueErrors (e.g. "couldn't parse the time") are
    constructed as strings *before* an exception is raised by the handler,
    so they pass through normally. The decorator only catches *unexpected* crashes.
"""

from __future__ import annotations

import functools
import logging

log = logging.getLogger(__name__)


class IntentResult:
    """Canonical status codes for intent handler outcomes."""
    SUCCESS             = "success"
    NEEDS_CLARIFICATION = "needs_clarification"   # ask, then remember the answer
    NEEDS_CONFIRMATION  = "needs_confirmation"     # irreversible — pause for OK first
    FAILED              = "failed"                 # always has a reason, never silent


# Actions that must be confirmed before executing.
# Any handler that *would* perform one of these must return NEEDS_CONFIRMATION
# and set a _pending_action — not execute it directly.
IRREVERSIBLE_ACTIONS: frozenset[str] = frozenset({
    "delete_file",
    "delete_folder",
    "shutdown",
    "restart",
    "uninstall_app",
})

_FAILURE_RESPONSE = "I couldn't do that — something went wrong on my end."


def safe_handler(fn):
    """
    Decorator for every _handle_* method in Agent.

    Guarantees:
      1. Any unhandled exception is logged with full traceback (not swallowed).
      2. The spoken response is always a clean string — never a raw traceback
         or generic canned message with no debugging trace.
      3. Zero migration cost: all existing callers already consume strings from
         run(), so decorating a method changes nothing visible to them.

    Usage:
        @safe_handler
        def _handle_reminder_set(self, slots, raw):
            ...
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            log.error(
                "%s raised %s: %s",
                fn.__qualname__, type(exc).__name__, exc,
                exc_info=True,
            )
            return _FAILURE_RESPONSE
    return wrapper
