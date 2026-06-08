"""
SQLite + FTS5 database for NEXUS memory engine.

Schema:
  - chunks: core content storage with file_path, line ranges, content hash, embeddings
  - chunks_fts: FTS5 virtual table for ultra-fast full-text search
  - embedding_cache: dedup cache for embedding vectors
  - meta: key-value metadata store
"""

from __future__ import annotations

import os
import struct
from typing import Optional

import sqlite3


CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding BLOB,
    embedding_provider TEXT,
    embedding_model TEXT,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'memory'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_updated ON chunks(updated_at);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    chunk_id UNINDEXED
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _to_blob(vector: list[float]) -> bytes:
    """Pack float list to binary blob (float32 little-endian)."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _from_blob(blob: bytes) -> list[float]:
    """Unpack binary blob to float list."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two float vectors."""
    if len(a) == 0 or len(b) == 0 or len(a) != len(b):
        return 0.0
    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = sum(ai * ai for ai in a) ** 0.5
    norm_b = sum(bi * bi for bi in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_fts_query(raw: str) -> str:
    """Build FTS5 AND query with quoted, Unicode-aware tokens."""
    import re
    tokens = re.findall(r"[\w]+", raw, re.UNICODE)
    if not tokens:
        return ""
    quoted = [f'"{t}"' for t in tokens]
    return " AND ".join(quoted)


class MemoryDatabase:
    """SQLite + FTS5 database for the NEXUS memory engine."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(CREATE_SCHEMA_SQL)
        self._conn.commit()
        self._run_migrations()

    def _run_migrations(self):
        """Add missing columns to existing tables."""
        cols = [row[1] for row in self._conn.execute("PRAGMA table_info(chunks)")]
        if "source" not in cols:
            self._conn.execute(
                "ALTER TABLE chunks ADD COLUMN source TEXT NOT NULL DEFAULT 'memory'"
            )
            self._conn.commit()

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------------
    # Provider fingerprint (detect embedding model changes)
    # ------------------------------------------------------------------

    def get_provider_fingerprint(self) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("provider_fingerprint",)
        ).fetchone()
        return row[0] if row else None

    def set_provider_fingerprint(self, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("provider_fingerprint", value),
        )
        self._conn.commit()

    def clear_embeddings(self):
        self._conn.execute(
            "UPDATE chunks SET embedding = NULL, embedding_provider = NULL, embedding_model = NULL"
        )
        self._conn.execute("DELETE FROM embedding_cache")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Embedding cache
    # ------------------------------------------------------------------

    def get_cached_embedding(self, content_hash: str) -> Optional[list[float]]:
        row = self._conn.execute(
            "SELECT embedding FROM embedding_cache WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if not row:
            return None
        return _from_blob(row[0])

    def set_cached_embedding(
        self,
        content_hash: str,
        embedding: list[float],
        provider: str,
        model: str,
    ):
        self._conn.execute(
            "INSERT OR REPLACE INTO embedding_cache "
            "(content_hash, embedding, provider, model, created_at) VALUES (?, ?, ?, ?, ?)",
            (content_hash, _to_blob(embedding), provider, model, int(__import__("time").time())),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Chunk CRUD
    # ------------------------------------------------------------------

    def get_chunk_by_hash(self, content_hash: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, file_path, start_line, end_line, content, content_hash, "
            "embedding, source, updated_at FROM chunks WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "file_path": row[1], "start_line": row[2],
            "end_line": row[3], "content": row[4], "content_hash": row[5],
            "embedding": _from_blob(row[6]) if row[6] else None,
            "source": row[7], "updated_at": row[8],
        }

    def upsert_chunk(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        content: str,
        content_hash: str,
        embedding: Optional[list[float]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        source: str = "memory",
    ) -> dict:
        """Insert or update a chunk. Returns {id, inserted}."""
        existing = self.get_chunk_by_hash(content_hash)
        embedding_blob = _to_blob(embedding) if embedding else None
        now = int(__import__("time").time())

        if existing:
            self._conn.execute(
                "UPDATE chunks SET file_path=?, start_line=?, end_line=?, content=?, "
                "embedding=?, embedding_provider=?, embedding_model=?, updated_at=?, "
                "source=? WHERE id=?",
                (file_path, start_line, end_line, content, embedding_blob,
                 provider, model, now, source, existing["id"]),
            )
            self._conn.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (existing["id"],))
            self._conn.execute(
                "INSERT INTO chunks_fts (content, chunk_id) VALUES (?, ?)",
                (content, existing["id"]),
            )
            self._conn.commit()
            return {"id": existing["id"], "inserted": False}

        self._conn.execute(
            "INSERT INTO chunks (file_path, start_line, end_line, content, content_hash, "
            "embedding, embedding_provider, embedding_model, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_path, start_line, end_line, content, content_hash,
             embedding_blob, provider, model, now, source),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM chunks WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if not row:
            raise RuntimeError("Failed to resolve inserted chunk id")
        self._conn.execute(
            "INSERT INTO chunks_fts (content, chunk_id) VALUES (?, ?)",
            (content, row[0]),
        )
        self._conn.commit()
        return {"id": row[0], "inserted": True}

    def delete_chunks_for_file(self, file_path: str) -> int:
        rows = self._conn.execute(
            "SELECT id FROM chunks WHERE file_path = ?", (file_path,)
        ).fetchall()
        for (cid,) in rows:
            self._conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (cid,))
        self._conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
        self._conn.commit()
        return len(rows)

    def list_indexed_files(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT file_path FROM chunks"
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_vector(
        self, query_embedding: list[float], max_results: int = 20
    ) -> list[dict]:
        """Vector similarity search via brute-force cosine."""
        rows = self._conn.execute(
            "SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL"
        ).fetchall()
        scored = []
        for cid, emb_blob in rows:
            if not emb_blob:
                continue
            score = _cosine_similarity(query_embedding, _from_blob(emb_blob))
            scored.append({"chunk_id": cid, "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_results]

    def search_keyword(
        self, query: str, max_results: int = 20
    ) -> list[dict]:
        """FTS5 full-text search with BM25 ranking."""
        sanitized = _build_fts_query(query)
        if not sanitized:
            return []
        rows = self._conn.execute(
            "SELECT chunk_id, bm25(chunks_fts) AS rank "
            "FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (sanitized, max_results),
        ).fetchall()
        return [
            {"chunk_id": r[0], "score": 1.0 / (1.0 + max(0, r[1]))}
            for r in rows
        ]

    def load_results_by_ids(self, ids: list[int]) -> list[dict]:
        """Load full chunk data by IDs, preserving input order."""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, file_path, start_line, end_line, content, content_hash, "
            f"embedding, source, updated_at FROM chunks WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        row_by_id = {}
        for r in rows:
            row_by_id[r[0]] = {
                "id": r[0], "file_path": r[1], "start_line": r[2],
                "end_line": r[3], "content": r[4], "content_hash": r[5],
                "embedding": _from_blob(r[6]) if r[6] else None,
                "source": r[7], "updated_at": r[8],
            }
        return [row_by_id[i] for i in ids if i in row_by_id]
