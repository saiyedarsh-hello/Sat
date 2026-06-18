"""
memory/memory_manager.py
Unified read/write API for both short-term (deque) and long-term (ChromaDB) memory.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from .short_term import ShortTermMemory
from .long_term import LongTermMemory
from database import models

log = logging.getLogger(__name__)


class MemoryManager:
    """Single interface for all memory operations."""

    def __init__(self) -> None:
        self.short = ShortTermMemory()
        self.long = LongTermMemory()

    def load(self) -> None:
        """Initialise long-term store (call once at startup)."""
        self.long.load()

    # ── Conversation buffer ───────────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        self.short.add_user(text)

    def add_assistant(self, text: str) -> None:
        self.short.add_assistant(text)

    def get_history(self) -> list[dict]:
        return self.short.get_history()

    def clear_session(self) -> None:
        self.short.clear()

    # ── Long-term memory ──────────────────────────────────────────────────────

    def remember(self, text: str, tags: str = "", importance: float = 0.5) -> str:
        """
        Persist a fact/memory to both SQLite and ChromaDB.
        Returns a human-readable confirmation string.
        """
        mem_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        # SQLite row
        try:
            db_id = models.insert_memory(
                content=text,
                summary=text[:120],
                tags=tags,
                importance=importance,
            )
            mem_id = f"mem_{db_id}"
        except Exception as exc:
            log.error("SQLite memory insert failed: %s", exc)

        # ChromaDB vector
        self.long.store(
            memory_id=mem_id,
            text=text,
            metadata={"tags": tags, "importance": importance, "created_at": timestamp},
        )

        log.info("Memory stored: %r", text[:80])
        return f"I'll remember that: '{text[:80]}{'…' if len(text) > 80 else ''}'"

    def recall(self, query: str, n: int = 5) -> list[str]:
        """
        Semantic search across long-term memory.
        Returns list of relevant memory strings.
        """
        results = self.long.search(query, n_results=n)
        if not results:
            # Fall back to SQLite keyword search
            rows = models.fetch_recent_memories(limit=n)
            return [r["content"] for r in rows if query.lower() in r["content"].lower()]
        return [r["text"] for r in results if r["distance"] < 0.85]

    def recall_as_context(self, query: str) -> str:
        """
        Return recalled memories formatted as LLM context block.
        """
        memories = self.recall(query)
        if not memories:
            return ""
        lines = "\n".join(f"- {m}" for m in memories)
        return f"Relevant memories:\n{lines}"

    def memory_count(self) -> int:
        return self.long.count()
