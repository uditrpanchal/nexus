"""
Embedding client abstraction for NEXUS memory engine.

Supports:
  - OpenAI embeddings (text-embedding-3-small)
  - Ollama local embeddings (nomic-embed-text)
  - Sentence-transformers (all-MiniLM-L6-v2) as local fallback — requires no API keys

Uses local sentence-transformers as the default zero-cost provider per the
free-source protocol.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


EMBEDDING_BATCH_SIZE = 64
EMBEDDING_TIMEOUT_S = 30


@dataclass
class EmbeddingClient:
    """Embedding provider abstraction."""
    provider: str  # "openai", "ollama", "local", "none"
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""
        if self.provider == "openai":
            return self._embed_openai(texts)
        elif self.provider == "ollama":
            return self._embed_ollama(texts)
        elif self.provider == "local":
            return self._embed_local(texts)
        else:
            return [[0.0] * 384 for _ in texts]

    def embed_query(self, text: str) -> Optional[list[float]]:
        """Embed a single query text."""
        vectors = self.embed([text])
        return vectors[0] if vectors else None

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            results = []
            for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
                batch = texts[i:i + EMBEDDING_BATCH_SIZE]
                resp = client.embeddings.create(input=batch, model=self.model)
                results.extend([d.embedding for d in resp.data])
            return results
        except Exception:
            return [[0.0] * 1536 for _ in texts]  # fallback on error

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        try:
            import httpx
            base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            results = []
            for text in texts:
                resp = httpx.post(
                    f"{base}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=EMBEDDING_TIMEOUT_S,
                )
                if resp.status_code == 200:
                    results.append(resp.json().get("embedding", [0.0] * 384))
                else:
                    results.append([0.0] * 384)
            return results
        except Exception:
            return [[0.0] * 384 for _ in texts]

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        """Use sentence-transformers locally (zero-cost, no API keys)."""
        try:
            from sentence_transformers import SentenceTransformer
            # Lazy-load and cache the model
            if not hasattr(self, "_local_model"):
                model_name = self.model or "all-MiniLM-L6-v2"
                self._local_model = SentenceTransformer(model_name)
            return self._local_model.encode(
                texts, normalize_embeddings=True
            ).tolist()
        except ImportError:
            # Fallback: simple TF-IDF like bag-of-words embedding
            return [_bag_of_words(t, 384) for t in texts]


def _bag_of_words(text: str, dim: int) -> list[float]:
    """Simple hash-based embedding fallback. No external deps needed."""
    import hashlib
    words = text.lower().split()
    vec = [0.0] * dim
    for w in words:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0
    # Normalize
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def create_embedding_client(
    provider: str = "auto",
    model: Optional[str] = None,
) -> EmbeddingClient:
    """
    Resolve embedding provider.
    Priority: explicit provider > OPENAI_API_KEY > local sentence-transformers
    """
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
            model = model or "text-embedding-3-small"
        elif os.environ.get("OLLAMA_BASE_URL"):
            provider = "ollama"
            model = model or "nomic-embed-text"
        else:
            provider = "local"
            model = model or "all-MiniLM-L6-v2"

    if provider == "openai":
        model = model or "text-embedding-3-small"
    elif provider == "ollama":
        model = model or "nomic-embed-text"
    elif provider == "local":
        model = model or "all-MiniLM-L6-v2"
    else:
        provider = "local"
        model = model or "all-MiniLM-L6-v2"

    return EmbeddingClient(provider=provider, model=model)
