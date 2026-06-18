"""
memory/short_term.py
In-session conversation buffer — a bounded deque of {role, content} dicts.
Zero latency, no disk I/O.
"""

from __future__ import annotations

from collections import deque
from typing import Iterator

from config import config


class ShortTermMemory:
    """Rolling conversation buffer for the current session."""

    def __init__(self) -> None:
        maxlen = int(config.get("memory", "short_term_max", default=20))
        self._buffer: deque[dict] = deque(maxlen=maxlen)

    def add(self, role: str, content: str) -> None:
        """Append a message. role ∈ {'user', 'assistant', 'system'}."""
        self._buffer.append({"role": role, "content": content})

    def add_user(self, text: str) -> None:
        self.add("user", text)

    def add_assistant(self, text: str) -> None:
        self.add("assistant", text)

    def get_history(self) -> list[dict]:
        """Return full conversation history as a list (oldest first)."""
        return list(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)

    def last_user_message(self) -> str:
        """Return the most recent user message text, or empty string."""
        for msg in reversed(self._buffer):
            if msg["role"] == "user":
                return msg["content"]
        return ""
