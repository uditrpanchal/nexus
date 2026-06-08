"""
Temporal decay module for NEXUS memory engine.

Applies exponential decay to search result scores based on chunk age.
Older data gracefully degrades while recent/preference data persists.
"""

from __future__ import annotations

import time
from typing import Optional


def compute_temporal_weight(
    chunk_timestamp: int,
    half_life_days: float = 30.0,
    now: Optional[float] = None,
) -> float:
    """
    Compute temporal decay weight for a chunk.

    Uses exponential decay: weight = 0.5 ^ (age_days / half_life_days)
    Returns a multiplier in [0, 1] where 1 = brand new, ~0 = very old.
    """
    if now is None:
        now = time.time()

    age_seconds = max(0, now - chunk_timestamp)
    age_days = age_seconds / 86400.0

    if age_days <= 0:
        return 1.0

    return 0.5 ** (age_days / half_life_days)


def apply_temporal_decay(
    results: list[dict],
    half_life_days: float = 30.0,
    now: Optional[float] = None,
) -> list[dict]:
    """
    Apply temporal decay to search result scores.

    Each result is expected to have an 'updated_at' field (unix timestamp).
    The 'score' field is multiplied by the temporal weight.

    Results missing 'updated_at' are left unchanged.
    """
    if now is None:
        now = time.time()

    decayed = []
    for item in results:
        ts = item.get("updated_at")
        if ts is not None:
            weight = compute_temporal_weight(int(ts), half_life_days, now)
            item = dict(item)
            item["temporal_weight"] = weight
            item["score"] = item.get("score", 0) * weight
        decayed.append(item)

    return decayed
