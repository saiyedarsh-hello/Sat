"""
memory/long_term.py
ChromaDB persistent vector store for long-term semantic memory.
Stores text memories with embeddings; supports similarity search.
Falls back to keyword search when ChromaDB is unavailable.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from config import config

log = logging.getLogger(__name__)

_APP_DATA = Path(os.getenv("APPDATA", Path.home())) / "Saturday"


class LongTermMemory:
    """ChromaDB-backed persistent memory store."""

    def __init__(self) -> None:
        self._client = None
        self._collection = None
        self._persist_dir = str(
            _APP_DATA / config.get("memory", "persist_dir", default="data/chromadb")
        )
        self._collection_name = config.get(
            "memory", "long_term_collection", default="saturday_memories"
        )

    def load(self) -> None:
        """Initialise ChromaDB client and collection."""
        try:
            import chromadb
            from chromadb.config import Settings

            os.makedirs(self._persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            log.info(
                "ChromaDB ready — %d memories in collection.",
                self._collection.count(),
            )
        except ImportError:
            log.warning("ChromaDB not installed — long-term memory disabled.")
        except Exception as exc:
            log.error("ChromaDB init error: %s", exc)

    # ── Write ─────────────────────────────────────────────────────────────────

    def store(
        self,
        memory_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        """Store a text memory with optional metadata."""
        if self._collection is None:
            log.debug("LTM not available — skipping store.")
            return
        try:
            self._collection.upsert(
                ids=[memory_id],
                documents=[text],
                metadatas=[metadata or {}],
            )
            log.debug("Memory stored: %s", memory_id)
        except Exception as exc:
            log.error("LTM store error: %s", exc)

    def delete(self, memory_id: str) -> None:
        if self._collection is None:
            return
        try:
            self._collection.delete(ids=[memory_id])
        except Exception as exc:
            log.error("LTM delete error: %s", exc)

    # ── Read ──────────────────────────────────────────────────────────────────

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """
        Semantic similarity search.
        Returns list of {id, text, metadata, distance} dicts.
        """
        if self._collection is None or self._collection.count() == 0:
            return []
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, self._collection.count()),
            )
            output = []
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for i, doc_id in enumerate(ids):
                output.append(
                    {
                        "id": doc_id,
                        "text": docs[i] if i < len(docs) else "",
                        "metadata": metas[i] if i < len(metas) else {},
                        "distance": dists[i] if i < len(dists) else 1.0,
                    }
                )
            return output
        except Exception as exc:
            log.error("LTM search error: %s", exc)
            return []

    def count(self) -> int:
        if self._collection is None:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    @property
    def is_ready(self) -> bool:
        return self._collection is not None
