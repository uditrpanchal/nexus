"""
Evaluation runner for NEXUS agent validation.

Loads 36 financial questions from questions.csv and runs them through
the agent with rubric-based scoring. Produces a comprehensive report
compatible with LangSmith tracking.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


EVAL_CSV_PATH = Path(__file__).parent / "questions.csv"


@dataclass
class EvalResult:
    """Result of evaluating a single question."""
    question_id: str
    question: str
    category: str
    difficulty: str
    passed: bool
    score: float
    max_score: float
    agent_output: str
    rubric_scores: dict[str, float] = field(default_factory=dict)
    tool_calls: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """Aggregate evaluation report."""
    total_questions: int
    passed: int
    failed: int
    total_score: float
    max_possible: float
    overall_pct: float
    by_category: dict[str, dict] = field(default_factory=dict)
    by_difficulty: dict[str, dict] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)
    duration_seconds: float = 0.0


class RubricScorer:
    """Scores agent output against rubric criteria using simple heuristics."""

    def score(self, rubric: str, agent_output: str, max_score: float) -> tuple[float, dict[str, float]]:
        """
        Parse rubric and score agent output.
        Rubric format: "criterion1=weight1,criterion2=weight2,..."
        """
        rubric_scores = {}
        total = 0.0

        if not rubric or rubric == "none":
            # No rubric: pass/fail based on content presence
            if agent_output and len(agent_output.strip()) > 20:
                total = max_score
            return total, {"content_present": total}

        pairs = [p.strip() for p in rubric.split(",")]
        for pair in pairs:
            if "=" not in pair:
                continue
            key, weight_str = pair.split("=", 1)
            try:
                weight = float(weight_str)
            except ValueError:
                continue

            # Simple heuristic: check if agent output contains relevant keywords
            score = self._score_criterion(key, agent_output, weight)
            rubric_scores[key] = score
            total += score

        return min(total, max_score), rubric_scores

    def _score_criterion(self, key: str, output: str, max_weight: float) -> float:
        """Heuristic-based criterion scoring."""
        output_lower = output.lower()
        key_lower = key.lower().replace("_", " ")

        # Check for key concepts in output
        words = key_lower.split()
        matches = sum(1 for w in words if w in output_lower)
        if matches >= len(words) * 0.75:
            return max_weight
        elif matches >= len(words) * 0.5:
            return max_weight * 0.7
        elif matches >= len(words) * 0.25:
            return max_weight * 0.4
        elif any(w in output_lower for w in words):
            return max_weight * 0.2
        return 0.0


class EvaluationRunner:
    """
    Runs the NEXUS evaluation suite.

    Usage:
        runner = EvaluationRunner()
        report = await runner.run_full_suite(agent_factory)
    """

    def __init__(self):
        self.scorer = RubricScorer()
        self._questions: list[dict] = []

    def load_questions(self) -> list[dict]:
        """Load questions from CSV."""
        if self._questions:
            return self._questions

        questions = []
        with open(EVAL_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                questions.append({
                    "id": row["id"],
                    "question": row["question"],
                    "category": row["category"],
                    "difficulty": row["difficulty"],
                    "expected_tools": row["expected_tools"],
                    "rubric": row["scoring_rubric"],
                    "max_score": float(row.get("max_score", 5)),
                })
        self._questions = questions
        return questions

    async def run_question(
        self,
        question: dict,
        agent,
    ) -> EvalResult:
        """Run a single question through the agent and score the result."""
        start = time.time()

        try:
            output = ""
            tool_count = 0
            async for event in agent.run(question["question"]):
                if hasattr(event, "type"):
                    if event.type == "done":
                        output = event.data.get("answer", "")
                        tool_count = len(event.data.get("tool_calls", []))
                    elif event.type in ("tool_start",):
                        tool_count += 1

            duration = time.time() - start
            score, rubric_scores = self.scorer.score(
                question["rubric"],
                output,
                question["max_score"],
            )
            passed = score >= question["max_score"] * 0.5

            return EvalResult(
                question_id=question["id"],
                question=question["question"],
                category=question["category"],
                difficulty=question["difficulty"],
                passed=passed,
                score=score,
                max_score=question["max_score"],
                agent_output=output[:500],
                rubric_scores=rubric_scores,
                tool_calls=tool_count,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start
            return EvalResult(
                question_id=question["id"],
                question=question["question"],
                category=question["category"],
                difficulty=question["difficulty"],
                passed=False,
                score=0.0,
                max_score=question["max_score"],
                agent_output="",
                errors=[str(e)],
                duration_seconds=duration,
            )

    async def run_full_suite(
        self,
        agent_factory,
        categories: Optional[list[str]] = None,
    ) -> EvalReport:
        """Run the complete evaluation suite."""
        start = time.time()
        questions = self.load_questions()
        agent = agent_factory()

        if categories:
            questions = [q for q in questions if q["category"] in categories]

        results: list[EvalResult] = []
        for q in questions:
            result = await self.run_question(q, agent)
            results.append(result)

        # Aggregate
        passed = sum(1 for r in results if r.passed)
        total_score = sum(r.score for r in results)
        max_possible = sum(r.max_score for r in results)

        by_category = {}
        by_difficulty = {}
        for r in results:
            cat = r.category
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "total": 0, "score": 0.0, "max": 0.0}
            by_category[cat]["total"] += 1
            by_category[cat]["score"] += r.score
            by_category[cat]["max"] += r.max_score
            if r.passed:
                by_category[cat]["passed"] += 1

            diff = r.difficulty
            if diff not in by_difficulty:
                by_difficulty[diff] = {"passed": 0, "total": 0, "score": 0.0, "max": 0.0}
            by_difficulty[diff]["total"] += 1
            by_difficulty[diff]["score"] += r.score
            by_difficulty[diff]["max"] += r.max_score
            if r.passed:
                by_difficulty[diff]["passed"] += 1

        for cat_data in by_category.values():
            cat_data["pct"] = (cat_data["score"] / cat_data["max"] * 100) if cat_data["max"] > 0 else 0
        for diff_data in by_difficulty.values():
            diff_data["pct"] = (diff_data["score"] / diff_data["max"] * 100) if diff_data["max"] > 0 else 0

        duration = time.time() - start

        return EvalReport(
            total_questions=len(results),
            passed=passed,
            failed=len(results) - passed,
            total_score=total_score,
            max_possible=max_possible,
            overall_pct=(total_score / max_possible * 100) if max_possible > 0 else 0,
            by_category=by_category,
            by_difficulty=by_difficulty,
            results=results,
            duration_seconds=duration,
        )

    def format_report(self, report: EvalReport) -> str:
        """Format evaluation report as markdown."""
        lines = []
        lines.append("# NEXUS Agent Evaluation Report")
        lines.append("")
        lines.append(f"**Total Questions:** {report.total_questions}")
        lines.append(f"**Passed:** {report.passed} | **Failed:** {report.failed}")
        lines.append(f"**Overall Score:** {report.total_score:.1f}/{report.max_possible:.0f} ({report.overall_pct:.1f}%)")
        lines.append(f"**Duration:** {report.duration_seconds:.1f}s")
        lines.append("")

        # By category
        lines.append("## By Category")
        lines.append("| Category | Passed | Total | Score | Pct |")
        lines.append("|----------|--------|-------|-------|-----|")
        for cat, data in sorted(report.by_category.items()):
            lines.append(f"| {cat} | {data['passed']} | {data['total']} | {data['score']:.1f}/{data['max']:.0f} | {data['pct']:.0f}% |")

        lines.append("")
        lines.append("## By Difficulty")
        lines.append("| Difficulty | Passed | Total | Score | Pct |")
        lines.append("|------------|--------|-------|-------|-----|")
        for diff, data in sorted(report.by_difficulty.items()):
            lines.append(f"| {diff} | {data['passed']} | {data['total']} | {data['score']:.1f}/{data['max']:.0f} | {data['pct']:.0f}% |")

        lines.append("")
        lines.append("## Detailed Results")
        for r in report.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"- [{status}] **{r.question_id}** ({r.category}/{r.difficulty}): {r.score:.1f}/{r.max_score:.0f} — {r.question[:80]}...")

        return "\n".join(lines)
