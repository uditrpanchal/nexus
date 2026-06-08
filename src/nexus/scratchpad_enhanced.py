"""
Enhanced Scratchpad with Tool Limit & Loop Detection for NEXUS.

Features:
  - Sequential execution count tracking per tool
  - Jaccard similarity threshold for query deduplication
  - Soft limit: max 3 calls per tool per query (warning intervention)
  - Guided fallback prompts when limit exceeded
  - Persistent JSONL format at .heon/scratchpad/
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SCRATCHPAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ))),
    ".heon", "scratchpad"
)


@dataclass
class ToolLimitConfig:
    max_calls_per_tool: int = 3
    similarity_threshold: float = 0.7  # Jaccard threshold for similar queries


@dataclass
class ToolUsageStatus:
    tool_name: str = ""
    call_count: int = 0
    max_calls: int = 3
    remaining_calls: int = 3
    recent_queries: list[str] = field(default_factory=list)
    over_limit: bool = False
    warnings: list[str] = field(default_factory=list)


class Scratchpad:
    """
    Enhanced scratchpad with tool limit enforcement and loop detection.

    Uses JSONL for resilient append-only logging.
    """

    def __init__(
        self,
        query: str,
        limit_config: Optional[ToolLimitConfig] = None,
        scratchpad_dir: str = SCRATCHPAD_DIR,
    ):
        self.limit_config = limit_config or ToolLimitConfig()
        self.scratchpad_dir = scratchpad_dir

        # Ensure directory exists
        Path(self.scratchpad_dir).mkdir(parents=True, exist_ok=True)

        # Create unique file for this query
        h = hashlib.md5(query.encode()).hexdigest()[:12]
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.filepath = os.path.join(self.scratchpad_dir, f"{ts}_{h}.jsonl")

        # In-memory tracking
        self._tool_call_counts: dict[str, int] = {}
        self._tool_queries: dict[str, list[str]] = {}
        self._tool_entries: list[dict] = []
        self._thinking_log: list[str] = []

        # Write initial entry
        self._append({
            "type": "init",
            "content": query,
            "timestamp": time.time(),
        })

    def _append(self, entry: dict):
        """Append a JSON line to the scratchpad file."""
        with open(self.filepath, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        if entry.get("type") == "tool_result":
            self._tool_entries.append(entry)

    # ------------------------------------------------------------------
    # Tool recording
    # ------------------------------------------------------------------

    def add_tool_result(
        self,
        tool_name: str,
        args: dict,
        result: str,
        duration: float = 0.0,
    ):
        """Record a tool execution result."""
        self._append({
            "type": "tool_result",
            "timestamp": time.time(),
            "tool_name": tool_name,
            "args": args,
            "result": result[:5000],  # Cap for brevity
            "duration": duration,
        })
        self.record_tool_call(tool_name)

    def add_thinking(self, text: str):
        """Record agent thinking."""
        self._thinking_log.append(text)
        self._append({
            "type": "thinking",
            "content": text,
            "timestamp": time.time(),
        })

    def record_tool_call(self, tool_name: str, query: Optional[str] = None):
        """Increment call count and track query for loop detection."""
        count = self._tool_call_counts.get(tool_name, 0)
        self._tool_call_counts[tool_name] = count + 1

        if query:
            queries = self._tool_queries.get(tool_name, [])
            queries.append(query)
            self._tool_queries[tool_name] = queries

    # ------------------------------------------------------------------
    # Limit enforcement
    # ------------------------------------------------------------------

    def can_call_tool(
        self,
        tool_name: str,
        query: Optional[str] = None,
    ) -> dict:
        """
        Check if a tool call can proceed.
        Returns {allowed: bool, warning: str | None}
        Never blocks — only warns.
        """
        current = self._tool_call_counts.get(tool_name, 0)
        max_calls = self.limit_config.max_calls_per_tool
        warnings = []

        # Count limit
        if current >= max_calls:
            warnings.append(
                f"Tool '{tool_name}' has been called {current} times "
                f"(suggested limit: {max_calls}). "
                f"Consider trying a different tool or approach."
            )

        # Similarity check
        if query:
            prev = self._tool_queries.get(tool_name, [])
            similar = self._find_similar_query(query, prev)
            if similar:
                remaining = max(0, max_calls - current)
                warnings.append(
                    f"This query is similar to a previous '{tool_name}' call. "
                    f"You have {remaining} attempt(s) before reaching the limit."
                )

        # Near-limit
        if current == max_calls - 1:
            warnings.append(
                f"Approaching limit for '{tool_name}' ({current + 1}/{max_calls}). "
                f"Make this call count."
            )

        if warnings:
            return {"allowed": True, "warning": "; ".join(warnings)}
        return {"allowed": True, "warning": None}

    def get_tool_usage_status(self) -> list[ToolUsageStatus]:
        """Get status for all tools."""
        statuses = []
        for name, count in self._tool_call_counts.items():
            max_calls = self.limit_config.max_calls_per_tool
            statuses.append(ToolUsageStatus(
                tool_name=name,
                call_count=count,
                max_calls=max_calls,
                remaining_calls=max(0, max_calls - count),
                recent_queries=self._tool_queries.get(name, [])[-3:],
                over_limit=count >= max_calls,
                warnings=(
                    [f"Over suggested limit of {max_calls}"] if count >= max_calls else []
                ),
            ))
        return statuses

    def format_tool_usage_for_prompt(self) -> Optional[str]:
        """Build tool usage warning for injection into agent prompt."""
        statuses = self.get_tool_usage_status()
        if not statuses:
            return None

        lines = ["## Tool Usage This Query", ""]
        for s in statuses:
            status = (
                f"{s.call_count} calls (over suggested limit of {s.max_calls})"
                if s.over_limit
                else f"{s.call_count}/{s.max_calls} calls"
            )
            lines.append(f"- {s.tool_name}: {status}")

        lines.append("")
        lines.append(
            "If a tool isn't returning useful results after several attempts, "
            "consider trying a different tool or approach."
        )
        return "\n".join(lines)

    def get_fallback_prompt(self, tool_name: str) -> str:
        """
        Generate a guided fallback prompt when a tool is repeatedly failing.
        """
        return (
            f"The tool '{tool_name}' has been called multiple times without success. "
            f"Please consider:\n"
            f"1. Using a different tool that may provide the same data\n"
            f"2. Trying different search terms or parameters\n"
            f"3. Proceeding with available data and noting any gaps to the user\n"
            f"4. Acknowledging the data limitation and moving on"
        )

    # ------------------------------------------------------------------
    # Loop detection (Jaccard similarity)
    # ------------------------------------------------------------------

    def _tokenize(self, text: str) -> set[str]:
        """Tokenize into normalized words."""
        return set(
            re.findall(r"[a-z0-9_]+", text.lower())
        )

    def _jaccard_similarity(self, set_a: set[str], set_b: set[str]) -> float:
        """Jaccard similarity between two sets."""
        if not set_a and not set_b:
            return 1.0
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _find_similar_query(
        self, new_query: str, previous_queries: list[str]
    ) -> Optional[str]:
        """Find a previous query that is too similar (above threshold)."""
        new_tokens = self._tokenize(new_query)
        threshold = self.limit_config.similarity_threshold

        for prev in reversed(previous_queries):  # Check most recent first
            prev_tokens = self._tokenize(prev)
            sim = self._jaccard_similarity(new_tokens, prev_tokens)
            if sim >= threshold:
                return prev
        return None

    # ------------------------------------------------------------------
    # Query & retrieval
    # ------------------------------------------------------------------

    def get_tool_call_records(self) -> list[dict]:
        """Get all tool call records for reporting."""
        return [
            {
                "tool": e.get("tool_name", "unknown"),
                "args": e.get("args", {}),
                "result": str(e.get("result", ""))[:500],
            }
            for e in self._tool_entries
        ]

    def get_summary(self) -> str:
        """Get a readable summary of tool activity."""
        lines = []
        for e in self._tool_entries:
            tn = e.get("tool_name", "?")
            res = str(e.get("result", ""))[:200]
            lines.append(f"[{tn}] {res}")
        return "\n\n".join(lines)

    def get_tool_entries(self) -> list[dict]:
        return list(self._tool_entries)
