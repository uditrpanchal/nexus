"""
Formal Evaluation Suite for NEXUS Agent.

Provides:
  - 36 financial questions in a flat CSV structure
  - Rubric-based LLM-as-judge scoring
  - LangSmith-compatible tracking hooks
  - Real-time accuracy monitoring
"""

from .runner import EvaluationRunner, EvalResult, EvalReport
from .tracking import LangSmithTracker

__all__ = ["EvaluationRunner", "EvalResult", "EvalReport", "LangSmithTracker"]
