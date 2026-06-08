"""
Maximal Marginal Relevance (MMR) re-ranking algorithm for NEXUS memory.

MMR balances relevance with diversity by iteratively selecting results
that maximize: λ * relevance - (1-λ) * max_similarity_to_selected

Based on Carbonell & Goldstein (1998).
"""

from __future__ import annotations

from typing import Optional


def tokenize(text: str) -> set[str]:
    """Tokenize text into normalized word tokens for similarity computation."""
    import re
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    return set(tokens)


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two token sets. Returns [0, 1]."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _max_similarity_to_selected(
    item_tokens: set[str],
    selected_tokens: list[set[str]],
) -> float:
    """Maximum Jaccard similarity to any already-selected item."""
    if not selected_tokens:
        return 0.0
    return max(jaccard_similarity(item_tokens, s) for s in selected_tokens)


def _mmr_rerank(
    items: list[dict],
    config: Optional[dict] = None,
) -> list[dict]:
    """
    Re-rank items using Maximal Marginal Relevance.

    Items must have 'score' (float) and 'content' (str) keys.
    Config: {enabled: bool, lambda: float} — lambda in [0,1] controls
    relevance vs diversity tradeoff.
    """
    if not items or len(items) <= 1:
        return [dict(it) for it in items]

    enabled = True
    lam = 0.7
    if config:
        enabled = config.get("enabled", True)
        lam = config.get("lambda", 0.7)

    if not enabled:
        return sorted(items, key=lambda x: x.get("score", 0), reverse=True)

    lam = max(0.0, min(1.0, lam))
    if lam == 1.0:
        return sorted(items, key=lambda x: x.get("score", 0), reverse=True)

    # Pre-tokenize
    token_cache = {}
    for i, item in enumerate(items):
        content = item.get("content", item.get("snippet", ""))
        token_cache[i] = tokenize(content)

    # Normalize scores to [0, 1]
    scores = [it.get("score", 0) for it in items]
    max_s = max(scores) if scores else 1
    min_s = min(scores) if scores else 0
    score_range = max_s - min_s

    def norm_score(s: float) -> float:
        if score_range == 0:
            return 1.0
        return (s - min_s) / score_range

    remaining = set(range(len(items)))
    selected_idx: list[int] = []
    selected_token_sets: list[set[str]] = []

    while remaining:
        best_idx = -1
        best_mmr = float("-inf")

        for idx in remaining:
            norm_rel = norm_score(scores[idx])
            max_sim = _max_similarity_to_selected(
                token_cache[idx], selected_token_sets
            )
            mmr_score = lam * norm_rel - (1 - lam) * max_sim

            if mmr_score > best_mmr or (
                mmr_score == best_mmr
                and scores[idx] > (scores[best_idx] if best_idx >= 0 else float("-inf"))
            ):
                best_mmr = mmr_score
                best_idx = idx

        if best_idx < 0:
            break

        selected_idx.append(best_idx)
        selected_token_sets.append(token_cache[best_idx])
        remaining.discard(best_idx)

    # Preserve remaining items that weren't selected (shouldn't happen)
    for idx in remaining:
        selected_idx.append(idx)

    return [dict(items[i]) for i in selected_idx]


def apply_mmr(
    results: list[dict],
    config: Optional[dict] = None,
) -> list[dict]:
    """
    Apply MMR re-ranking to search results.
    Adds a 'mmr_rank' field to each result indicating its position after re-ranking.
    """
    if not results:
        return results

    reranked = _mmr_rerank(results, config)
    for i, item in enumerate(reranked):
        item["mmr_rank"] = i + 1
    return reranked
