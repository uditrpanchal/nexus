"""
Simple file-based cache with TTL support.
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Any


class Cache:
    """File-based TTL cache for API responses."""

    def __init__(self, cache_dir: str = None, default_ttl: int = 300):
        if cache_dir is None:
            cache_dir = str(Path.home() / ".heon" / "cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def _key_to_filename(self, key: str) -> str:
        h = hashlib.md5(key.encode()).hexdigest()
        return f"{h}.json"

    def get(self, key: str) -> Any | None:
        fpath = self.cache_dir / self._key_to_filename(key)
        if not fpath.exists():
            return None
        try:
            data = json.loads(fpath.read_text())
            if time.time() - data["timestamp"] > data["ttl"]:
                fpath.unlink(missing_ok=True)
                return None
            return data["value"]
        except (json.JSONDecodeError, KeyError):
            fpath.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        ttl = ttl or self.default_ttl
        fpath = self.cache_dir / self._key_to_filename(key)
        data = {"timestamp": time.time(), "ttl": ttl, "value": value}
        fpath.write_text(json.dumps(data, default=str))

    def clear(self) -> None:
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
