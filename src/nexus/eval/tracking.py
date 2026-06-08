"""
LangSmith-compatible tracking hooks for NEXUS evaluation.

Provides:
  - Run-level tracing with metadata
  - Feedback collection and scoring
  - Export-compatible JSON format for LangSmith ingestion
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional


LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "nexus-eval")
LANGSMITH_ENDPOINT = os.environ.get(
    "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
)


@dataclass
class TraceRun:
    """A single traced run compatible with LangSmith format."""
    id: str
    name: str
    run_type: str = "chain"
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    error: Optional[str] = None
    extra: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    feedback: list[dict] = field(default_factory=list)

    def to_langsmith_dict(self) -> dict:
        """Export in LangSmith-compatible format."""
        return {
            "id": self.id,
            "name": self.name,
            "run_type": self.run_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error": self.error,
            "extra": self.extra,
            "tags": self.tags,
        }


class LangSmithTracker:
    """
    Tracks NEXUS evaluation runs in LangSmith-compatible format.

    Usage:
        tracker = LangSmithTracker(project="nexus-eval")
        with tracker.trace("eval-q001"):
            # run evaluation
            tracker.log_feedback("accuracy", 0.85)
    """

    def __init__(
        self,
        project: str = LANGSMITH_PROJECT,
        api_key: str = LANGSMITH_API_KEY,
        endpoint: str = LANGSMITH_ENDPOINT,
    ):
        self.project = project
        self.api_key = api_key
        self.endpoint = endpoint
        self._runs: list[TraceRun] = []
        self._active_run: Optional[TraceRun] = None

    @property
    def is_connected(self) -> bool:
        return bool(self.api_key)

    def start_run(self, name: str, inputs: dict = None, **tags: str) -> TraceRun:
        """Start a new traced run."""
        run = TraceRun(
            id=f"nexus-{name}-{int(time.time() * 1000)}",
            name=name,
            inputs=inputs or {},
            tags=list(tags.values()) if tags else [],
        )
        self._active_run = run
        self._runs.append(run)
        return run

    def end_run(
        self,
        outputs: dict = None,
        error: Optional[str] = None,
    ):
        """End the active traced run."""
        if self._active_run:
            self._active_run.end_time = time.time()
            if outputs:
                self._active_run.outputs = outputs
            if error:
                self._active_run.error = error
        self._active_run = None

    def log_feedback(
        self,
        key: str,
        score: float,
        comment: str = "",
        run_id: Optional[str] = None,
    ):
        """Log feedback/score for a run."""
        target_id = run_id or (self._active_run.id if self._active_run else None)
        if not target_id:
            return

        feedback = {
            "key": key,
            "score": score,
            "comment": comment,
            "run_id": target_id,
            "timestamp": time.time(),
        }

        if self._active_run:
            self._active_run.feedback.append(feedback)
        else:
            for run in self._runs:
                if run.id == target_id:
                    run.feedback.append(feedback)
                    break

    def trace(self, name: str, **inputs):
        """Context manager for tracing a run."""
        import contextlib

        @contextlib.contextmanager
        def _trace():
            self.start_run(name, inputs)
            try:
                yield self._active_run
            except Exception as e:
                self.end_run(error=str(e))
                raise
            else:
                self.end_run()

        return _trace()

    def get_runs(self) -> list[dict]:
        """Get all runs as LangSmith-compatible dicts."""
        return [r.to_langsmith_dict() for r in self._runs]

    def get_feedback(self) -> list[dict]:
        """Get all feedback across runs."""
        all_feedback = []
        for run in self._runs:
            all_feedback.extend(run.feedback)
        return all_feedback

    def export_json(self, path: str):
        """Export all runs and feedback to JSON file."""
        with open(path, "w") as f:
            json.dump(
                {
                    "project": self.project,
                    "runs": self.get_runs(),
                    "feedback": self.get_feedback(),
                },
                f,
                indent=2,
            )

    def get_summary(self) -> dict:
        """Get aggregate summary of all tracked runs."""
        runs = self._runs
        if not runs:
            return {"total_runs": 0}

        completed = [r for r in runs if r.end_time is not None]
        errors = [r for r in runs if r.error]

        scores = []
        for r in runs:
            for fb in r.feedback:
                if fb["key"] == "accuracy":
                    scores.append(fb["score"])

        return {
            "total_runs": len(runs),
            "completed": len(completed),
            "errors": len(errors),
            "avg_accuracy": sum(scores) / len(scores) if scores else 0,
            "total_feedback": sum(len(r.feedback) for r in runs),
        }

    def flush_to_langsmith(self):
        """Flush tracked runs to LangSmith API (requires API key)."""
        if not self.is_connected:
            return

        try:
            import httpx
            headers = {
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            }
            for run in self._runs:
                if run.end_time:
                    httpx.post(
                        f"{self.endpoint}/runs",
                        json=run.to_langsmith_dict(),
                        headers=headers,
                        timeout=10,
                    )
                    for fb in run.feedback:
                        httpx.post(
                            f"{self.endpoint}/feedback",
                            json=fb,
                            headers=headers,
                            timeout=10,
                        )
        except Exception:
            pass  # Silently fail if LangSmith is unreachable
