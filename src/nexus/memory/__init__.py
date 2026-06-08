"""
Core Vector & Text Memory Engine for NEXUS.

Implements persistent local memory infrastructure at .heon/memory/ with:
- SQLite + FTS5 for ultra-fast full-text search
- Local vector embedding pipeline with caching
- Maximal Marginal Relevance (MMR) re-ranking with temporal decay factor
- Graceful degradation of old data while preserving user risk profiles and preferences
"""

from .database import MemoryDatabase
from .embeddings import EmbeddingClient, create_embedding_client
from .mmr import apply_mmr, jaccard_similarity, tokenize
from .temporal_decay import apply_temporal_decay, compute_temporal_weight
from .manager import MemoryManager

__all__ = [
    "MemoryDatabase",
    "EmbeddingClient",
    "create_embedding_client",
    "apply_mmr",
    "jaccard_similarity",
    "tokenize",
    "apply_temporal_decay",
    "compute_temporal_weight",
    "MemoryManager",
]