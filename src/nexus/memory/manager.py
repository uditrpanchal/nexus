"""
Memory Manager for NEXUS — central coordinator for the memory engine.

Manages:
  - SQLite + FTS5 database
  - Embedding client
  - Hybrid search (vector + keyword)
  - MMR re-ranking with temporal decay
  - Session context loading
  - Memory file operations
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from .database import MemoryDatabase
from .embeddings import create_embedding_client, EmbeddingClient
from .mmr import apply_mmr
from .temporal_decay import apply_temporal_decay


# Default memory directory under the project root
DEFAULT_MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ))),
    ".heon", "memory"
)


class MemoryStore:
    """File operations for memory markdown files."""

    def __init__(self, memory_dir: str = DEFAULT_MEMORY_DIR):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def ensure_exists(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def list_files(self) -> list[str]:
        return sorted([
            f.name for f in self.memory_dir.glob("*.md")
        ])

    def read_file(self, filename: str) -> str:
        path = self.memory_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def append_file(self, filename: str, text: str):
        path = self.memory_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def read_lines(
        self, path: str, offset: int = 0, limit: int = 100
    ) -> dict:
        """Read lines from a memory file."""
        full_path = self.memory_dir / path
        if not full_path.exists():
            return {"content": "", "total_lines": 0}
        lines = full_path.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        selected = lines[offset:offset + limit]
        return {"content": "\n".join(selected), "total_lines": total}

    def load_session_context(self, max_tokens: int = 2000) -> dict:
        """
        Load recent memory context for injection into the agent system prompt.
        Returns most recent MEMORY.md content (or today's date file) up to max_tokens.
        """
        today = time.strftime("%Y-%m-%d")
        today_file = f"{today}.md"

        # Prefer today's file, fall back to MEMORY.md
        content = ""
        if today_file in self.list_files():
            content = self.read_file(today_file)
        else:
            content = self.read_file("MEMORY.md")

        # Truncate to approximate token count (chars ÷ 4)
        max_chars = max_tokens * 4
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... [truncated]"

        return {"text": content, "source": "memory"}


class MemoryManager:
    """Central memory coordinator for NEXUS."""

    _instance: Optional["MemoryManager"] = None

    def __init__(
        self,
        memory_dir: str = DEFAULT_MEMORY_DIR,
        embedding_provider: str = "auto",
        embedding_model: Optional[str] = None,
    ):
        self.memory_dir = memory_dir
        self.store = MemoryStore(memory_dir)
        self.db: Optional[MemoryDatabase] = None
        self.embedding_client: Optional[EmbeddingClient] = None
        self._init_error: Optional[str] = None

        # Config
        self.max_results = 6
        self.min_score = 0.1
        self.vector_weight = 0.7
        self.text_weight = 0.3
        self.temporal_decay_enabled = True
        self.half_life_days = 30.0
        self.mmr_enabled = True
        self.mmr_lambda = 0.7

        # Initialize
        try:
            self._initialize(embedding_provider, embedding_model)
        except Exception as e:
            self._init_error = str(e)

    def _initialize(self, embedding_provider: str, embedding_model: Optional[str]):
        """Set up database and embedding client."""
        self.store.ensure_exists()
        db_path = os.path.join(self.memory_dir, "index.sqlite")
        self.db = MemoryDatabase(db_path)

        self.embedding_client = create_embedding_client(
            provider=embedding_provider,
            model=embedding_model,
        )

        fingerprint = f"{self.embedding_client.provider}:{self.embedding_client.model}"
        existing = self.db.get_provider_fingerprint()
        if existing and existing != fingerprint:
            self.db.clear_embeddings()
        self.db.set_provider_fingerprint(fingerprint)

    @classmethod
    def get(cls, **kwargs) -> "MemoryManager":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def is_available(self) -> bool:
        return self.db is not None and self._init_error is None

    def get_unavailable_reason(self) -> Optional[str]:
        return self._init_error

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 6,
        min_score: float = 0.1,
    ) -> list[dict]:
        """
        Hybrid search: vector + FTS5 keyword with MMR re-ranking and temporal decay.
        """
        if not self.db or not self.embedding_client:
            return []

        # Vector search
        vec_results = []
        query_embedding = self.embedding_client.embed_query(query)
        if query_embedding:
            vec_candidates = self.db.search_vector(query_embedding, max_results * 2)
            results = self.db.load_results_by_ids(
                [c["chunk_id"] for c in vec_candidates]
            )
            for r, c in zip(results, vec_candidates):
                r["score"] = c["score"] * self.vector_weight
                r["source"] = "vector"
            vec_results = results

        # Keyword search
        kw_candidates = self.db.search_keyword(query, max_results * 2)
        results = self.db.load_results_by_ids(
            [c["chunk_id"] for c in kw_candidates]
        )
        for r, c in zip(results, kw_candidates):
            r["score"] = c["score"] * self.text_weight
            r["source"] = "keyword"
        kw_results = results

        # Merge and deduplicate
        seen = set()
        merged = []
        for r in vec_results + kw_results:
            key = (r.get("file_path", ""), r.get("start_line", 0))
            if key not in seen:
                seen.add(key)
                merged.append(r)
            else:
                # Boost score for items found by both methods
                for existing in merged:
                    ek = (existing.get("file_path", ""), existing.get("start_line", 0))
                    if ek == key:
                        existing["score"] = max(existing["score"], r["score"])
                        existing["source"] = "hybrid"
                        break

        # Filter by min score
        merged = [r for r in merged if r.get("score", 0) >= min_score]

        # Sort by score
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Apply temporal decay
        if self.temporal_decay_enabled:
            merged = apply_temporal_decay(merged, self.half_life_days)

        # Re-sort after decay
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Apply MMR re-ranking
        if self.mmr_enabled:
            merged = apply_mmr(merged, {"lambda": self.mmr_lambda})

        return merged[:max_results]

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    def append_memory(self, content: str, file: str = "MEMORY.md"):
        """Append a memory entry."""
        self.store.append_file(file, content)

    def list_files(self) -> list[str]:
        return self.store.list_files()

    def load_session_context(self, max_tokens: int = 2000) -> dict:
        return self.store.load_session_context(max_tokens)

    # ------------------------------------------------------------------
    # Indexing helpers
    # ------------------------------------------------------------------

    def index_text(
        self,
        content: str,
        file_path: str = "memory:unknown",
        source: str = "memory",
    ) -> Optional[int]:
        """Index a text block into the memory database."""
        if not self.db or not self.embedding_client:
            return None

        import hashlib
        content_hash = hashlib.md5(content.encode()).hexdigest()

        # Get or create embedding
        embedding = None
        cached = self.db.get_cached_embedding(content_hash)
        if cached:
            embedding = cached
        elif self.embedding_client.provider != "none":
            vecs = self.embedding_client.embed([content])
            if vecs:
                embedding = vecs[0]
                self.db.set_cached_embedding(
                    content_hash, embedding,
                    self.embedding_client.provider,
                    self.embedding_client.model,
                )

        result = self.db.upsert_chunk(
            file_path=file_path,
            start_line=1,
            end_line=content.count("\n") + 1,
            content=content,
            content_hash=content_hash,
            embedding=embedding,
            provider=self.embedding_client.provider if embedding else None,
            model=self.embedding_client.model if embedding else None,
            source=source,
        )
        return result["id"]

    def close(self):
        if self.db:
            self.db.close()
