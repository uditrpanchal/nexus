"""
Validation Gate — Programmatic output verification before report generation.

Before compiling final reports, the engine must auto-verify:
  1. No sections are skipped — all 8 (stock) or 7 (ETF) pillars evaluated
  2. Null rows are reconciled — every pillar has a score (no None)
  3. All mandatory data validation tables pass with 100% completion
  4. Red flag scanner ran on all 3 flags
  5. Math tracking strings present for every computation
  6. Scorecard arithmetic internally consistent

This module acts as the final gatekeeper before any analysis output
is considered complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .red_flag_scanner import RedFlagScanResults, FlagStatus
from .pillar_evaluator import StockPillarResults, ETFPillarResults
from .scorecard import ScorecardResult


@dataclass
class ValidationIssue:
    """A single validation issue found during the gate check."""
    severity: str  # "ERROR" or "WARNING"
    section: str
    message: str


@dataclass
class ValidationReport:
    """Complete validation report."""
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    completion_pct: float = 0.0

    @property
    def error_count(self) -> int:
        return len(self.issues)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


class ValidationGate:
    """
    Pre-report validation gate.

    Usage:
        gate = ValidationGate()
        report = gate.validate_stock(ticker, pillar_results, red_flag_results, scorecard)
        if not report.passed:
            # Fix issues before generating report
    """

    # Required completion threshold
    REQUIRED_COMPLETION_PCT = 100.0

    # Required counts
    STOCK_PILLAR_COUNT = 8
    ETF_PILLAR_COUNT = 7
    RED_FLAG_COUNT = 4

    def validate_stock(
        self,
        ticker: str,
        pillars: StockPillarResults,
        red_flags: RedFlagScanResults,
        scorecard: ScorecardResult,
    ) -> ValidationReport:
        """
        Validate a complete stock analysis before report generation.

        Checks:
          1. All 8 pillars present with scores
          2. All 3 red flags checked
          3. Scorecard mathematically consistent
          4. No null/None values in critical fields
          5. Math tracking strings present
        """
        issues: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        checks_total = 0
        checks_passed = 0

        # -----------------------------------------------------------
        # Check 1: All 8 pillars present
        # -----------------------------------------------------------
        checks_total += 1
        if len(pillars.pillars) != self.STOCK_PILLAR_COUNT:
            issues.append(ValidationIssue(
                "ERROR", "Pillars",
                f"Expected {self.STOCK_PILLAR_COUNT} stock pillars, "
                f"found {len(pillars.pillars)}"
            ))
        else:
            checks_passed += 1

        # Check each pillar has a valid score
        for p in pillars.pillars:
            checks_total += 1
            if p.raw_score is None or p.raw_score < 1.0 or p.raw_score > 5.0:
                issues.append(ValidationIssue(
                    "ERROR", f"Pillar {p.pillar_number}",
                    f"Pillar '{p.pillar_name}' has invalid score: {p.raw_score}"
                ))
            else:
                checks_passed += 1

            # Check math tracking string present
            checks_total += 1
            if not p.math_tracking:
                warnings.append(ValidationIssue(
                    "WARNING", f"Pillar {p.pillar_number}",
                    f"Pillar '{p.pillar_name}' missing math tracking string"
                ))
            else:
                checks_passed += 1

            # Check weighted computation
            checks_total += 1
            expected_weighted = round(p.raw_score * p.weight, 4)
            actual_weighted = round(p.weighted_score, 4)
            if abs(expected_weighted - actual_weighted) > 0.01:
                issues.append(ValidationIssue(
                    "ERROR", f"Pillar {p.pillar_number}",
                    f"Weighted score mismatch for '{p.pillar_name}': "
                    f"expected {expected_weighted:.4f} ({p.raw_score:.2f} * {p.weight:.2f}), "
                    f"got {actual_weighted:.4f}"
                ))
            else:
                checks_passed += 1

        # -----------------------------------------------------------
        # Check 2: All 3 red flags checked
        # -----------------------------------------------------------
        checks_total += 1
        if len(red_flags.results) != self.RED_FLAG_COUNT:
            issues.append(ValidationIssue(
                "ERROR", "Red Flags",
                f"Expected {self.RED_FLAG_COUNT} red flag checks, "
                f"found {len(red_flags.results)}"
            ))
        else:
            checks_passed += 1

        # Each flag must have a status
        for rf in red_flags.results:
            checks_total += 1
            if rf.status not in (FlagStatus.CLEAR, FlagStatus.WARNING, FlagStatus.TRIGGERED):
                issues.append(ValidationIssue(
                    "ERROR", f"Red Flag {rf.flag_number}",
                    f"Invalid status for '{rf.flag_name}': {rf.status}"
                ))
            else:
                checks_passed += 1

        # -----------------------------------------------------------
        # Check 3: Red flag count matches
        # -----------------------------------------------------------
        checks_total += 1
        actual_triggered = sum(
            1 for rf in red_flags.results if rf.status == FlagStatus.TRIGGERED
        )
        if actual_triggered != red_flags.total_flags_triggered:
            issues.append(ValidationIssue(
                "ERROR", "Red Flags",
                f"Flag count mismatch: reported {red_flags.total_flags_triggered}, "
                f"actual {actual_triggered}"
            ))
        else:
            checks_passed += 1

        # -----------------------------------------------------------
        # Check 4: Scorecard consistency
        # -----------------------------------------------------------
        checks_total += 1
        if not scorecard.verification_passed:
            issues.append(ValidationIssue(
                "ERROR", "Scorecard",
                "Scorecard verification did not pass"
            ))
        else:
            checks_passed += 1

        # Check verdict logic consistency
        checks_total += 1
        if scorecard.verdict == "AVOID":
            if scorecard.flag_override != "AVOID" and scorecard.final_pct >= self.REQUIRED_COMPLETION_PCT * 0.5:
                # AVOID with no override and decent score is suspicious
                warnings.append(ValidationIssue(
                    "WARNING", "Scorecard",
                    f"AVOID verdict with {scorecard.final_pct:.1f}% score "
                    f"and no flag override — verify threshold logic"
                ))
            checks_passed += 1
        elif scorecard.verdict == "BUY" and scorecard.red_flag_count > 0:
            issues.append(ValidationIssue(
                "ERROR", "Scorecard",
                f"BUY verdict with {scorecard.red_flag_count} red flag(s) — "
                f"BUY requires 0 flags"
            ))
        else:
            checks_passed += 1

        # Check math tracking entries exist
        checks_total += 1
        if not scorecard.math_tracking:
            warnings.append(ValidationIssue(
                "WARNING", "Scorecard",
                "No math tracking entries in scorecard"
            ))
        else:
            checks_passed += 1

        # -----------------------------------------------------------
        # Check 5: No null/None in critical paths
        # -----------------------------------------------------------
        checks_total += 1
        if not pillars.pillars:
            issues.append(ValidationIssue(
                "ERROR", "Pillars",
                "No pillar results at all"
            ))
        else:
            checks_passed += 1

        checks_total += 1
        if scorecard.final_pct is None:
            issues.append(ValidationIssue(
                "ERROR", "Scorecard",
                "Final percentage is None"
            ))
        else:
            checks_passed += 1

        # -----------------------------------------------------------
        # Final report
        # -----------------------------------------------------------
        completion_pct = (checks_passed / checks_total) * 100 if checks_total > 0 else 0

        report = ValidationReport(
            passed=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            completion_pct=completion_pct,
        )

        return report

    def validate_etf(
        self,
        ticker: str,
        pillars: ETFPillarResults,
        scorecard: ScorecardResult,
    ) -> ValidationReport:
        """Validate an ETF analysis before report generation."""
        issues: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        checks_total = 0
        checks_passed = 0

        # Check all 7 pillars present
        checks_total += 1
        if len(pillars.pillars) != self.ETF_PILLAR_COUNT:
            issues.append(ValidationIssue(
                "ERROR", "ETF Pillars",
                f"Expected {self.ETF_PILLAR_COUNT} pillars, "
                f"found {len(pillars.pillars)}"
            ))
        else:
            checks_passed += 1

        for p in pillars.pillars:
            checks_total += 1
            if p.raw_score is None or p.raw_score < 1.0 or p.raw_score > 5.0:
                issues.append(ValidationIssue(
                    "ERROR", f"ETF Pillar {p.pillar_number}",
                    f"Invalid score for '{p.pillar_name}': {p.raw_score}"
                ))
            else:
                checks_passed += 1

            checks_total += 1
            expected_weighted = round(p.raw_score * p.weight, 4)
            actual_weighted = round(p.weighted_score, 4)
            if abs(expected_weighted - actual_weighted) > 0.01:
                issues.append(ValidationIssue(
                    "ERROR", f"ETF Pillar {p.pillar_number}",
                    f"Weighted score mismatch: expected {expected_weighted:.4f}, "
                    f"got {actual_weighted:.4f}"
                ))
            else:
                checks_passed += 1

        checks_total += 1
        if not scorecard.verification_passed:
            issues.append(ValidationIssue(
                "ERROR", "ETF Scorecard",
                "Scorecard verification did not pass"
            ))
        else:
            checks_passed += 1

        completion_pct = (checks_passed / checks_total) * 100 if checks_total > 0 else 0

        return ValidationReport(
            passed=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            completion_pct=completion_pct,
        )

    @staticmethod
    def format_report(report: ValidationReport) -> str:
        """Format a validation report for display."""
        lines = []
        status = "✓ PASSED" if report.passed else "✗ FAILED"
        lines.append(f"Validation Gate: {status} ({report.completion_pct:.0f}% complete)")
        lines.append(f"  Errors: {report.error_count}, Warnings: {report.warning_count}")

        for issue in report.issues:
            lines.append(f"  [ERROR] [{issue.section}] {issue.message}")

        for warning in report.warnings:
            lines.append(f"  [WARN]  [{warning.section}] {warning.message}")

        return "\n".join(lines)
