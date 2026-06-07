"""
Scorecard & Arithmetic Module — Weighted scoring tables with math tracking.

Implements the weighted scoring tables exactly as outlined in the
Universal Investment Analysis Framework specification sheet.

The scorecard programmatically computes:
  - Final weighted score from pillar results + red flag deductions
  - 5-star rating conversion
  - BUY / WATCH / AVOID verdict
  - Arithmetic verification tracking strings

Final Verdict Rules:
  - BUY:   ≥ 70% total score AND 0 red flags triggered
  - WATCH: 50-69% OR 1 red flag triggered
  - AVOID: < 50% OR 2+ red flags OR flag override from scanner
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .red_flag_scanner import RedFlagScanResults
from .pillar_evaluator import StockPillarResults, ETFPillarResults


@dataclass
class ScorecardResult:
    """Final scorecard output after all deductions and verification."""
    ticker: str
    asset_type: str  # "stock" or "etf"

    # Pillar scores
    pillar_total: float = 0.0
    pillar_max: float = 0.0
    pillar_pct: float = 0.0

    # Red flag deductions
    red_flag_count: int = 0
    red_flag_deduction: float = 0.0
    flag_override: Optional[str] = None  # "AVOID" if 3 flags

    # Final
    final_score: float = 0.0
    final_pct: float = 0.0
    star_rating: str = "★"
    verdict: str = "WATCH"

    # Verification
    math_tracking: list[str] = field(default_factory=list)
    verification_passed: bool = False


class Scorecard:
    """
    Weighted scoring engine.

    Computes final scores from pillar results + red flag deductions
    and produces BUY/WATCH/AVOID verdict.
    """

    # Verdict thresholds
    BUY_THRESHOLD = 70.0    # percentage
    WATCH_THRESHOLD = 50.0  # percentage

    @staticmethod
    def compute_stock_score(
        ticker: str,
        pillars: StockPillarResults,
        red_flags: RedFlagScanResults,
    ) -> ScorecardResult:
        """
        Compute final scorecard for a stock analysis.

        Formula:
          final_score = sum(pillar weighted scores) / max_possible * 100
          Then apply red flag deductions.
        """
        result = ScorecardResult(ticker=ticker, asset_type="stock")
        tracking = []

        # Step 1: Pillar totals
        result.pillar_total = pillars.total_weighted_score
        result.pillar_max = pillars.max_possible
        result.pillar_pct = (result.pillar_total / result.pillar_max) * 100 if result.pillar_max > 0 else 0

        tracking.append(
            f"PILLAR_SCORE = "
            f"SUM({', '.join(f'P{p.pillar_number}={p.weighted_score:.3f}' for p in pillars.pillars)}) = "
            f"{result.pillar_total:.3f} / {result.pillar_max:.3f} = "
            f"{result.pillar_pct:.2f}%"
        )

        # Step 2: Red flags
        result.red_flag_count = red_flags.total_flags_triggered
        result.flag_override = red_flags.verdict_override

        if result.flag_override == "AVOID":
            result.red_flag_deduction = float("-inf")
            tracking.append(
                "RED_FLAG_OVERRIDE: 3 flags triggered → "
                "Automatic AVOID verdict (overrides all pillar scores)"
            )
        else:
            result.red_flag_deduction = red_flags.total_deduction
            tracking.append(
                f"RED_FLAG_DEDUCTION: {result.red_flag_count} flag(s) → "
                f"{result.red_flag_deduction:+.1f} points"
            )

        # Step 3: Final score
        if result.flag_override == "AVOID":
            result.final_score = 0.0
            result.final_pct = 0.0
            result.verdict = "AVOID"
            result.star_rating = "★"
        else:
            # Deduction is applied to the final percentage
            result.final_pct = result.pillar_pct + (result.red_flag_deduction * 10)
            result.final_pct = max(0.0, min(100.0, result.final_pct))
            result.final_score = result.final_pct

            tracking.append(
                f"FINAL_SCORE = {result.pillar_pct:.2f}% + "
                f"({result.red_flag_deduction:.1f} * 10) = {result.final_pct:.2f}%"
            )

            # Step 4: Verdict
            if result.final_pct >= Scorecard.BUY_THRESHOLD and result.red_flag_count == 0:
                result.verdict = "BUY"
            elif result.final_pct >= Scorecard.BUY_THRESHOLD and result.red_flag_count == 1:
                result.verdict = "WATCH (BUY score but 1 flag)"
            elif result.final_pct >= Scorecard.WATCH_THRESHOLD:
                result.verdict = "WATCH"
            else:
                result.verdict = "AVOID"

            # Step 5: Star rating
            result.star_rating = Scorecard._compute_stars(result.final_pct)

            tracking.append(
                f"VERDICT: {result.verdict} | "
                f"RATING: {result.star_rating} | "
                f"SCORE: {result.final_pct:.2f}%"
            )

        result.math_tracking = tracking
        result.verification_passed = True
        return result

    @staticmethod
    def compute_etf_score(
        ticker: str,
        pillars: ETFPillarResults,
    ) -> ScorecardResult:
        """
        Compute final scorecard for an ETF analysis.
        ETFs don't have red flags (no debt/cashflow issues), so simpler.
        """
        result = ScorecardResult(ticker=ticker, asset_type="etf")
        tracking = []

        result.pillar_total = pillars.total_weighted_score
        result.pillar_max = pillars.max_possible
        result.pillar_pct = (result.pillar_total / result.pillar_max) * 100 if result.pillar_max > 0 else 0

        tracking.append(
            f"ETF_PILLAR_SCORE = "
            f"SUM({', '.join(f'P{p.pillar_number}={p.weighted_score:.3f}' for p in pillars.pillars)}) = "
            f"{result.pillar_total:.3f} / {result.pillar_max:.3f} = "
            f"{result.pillar_pct:.2f}%"
        )

        result.final_pct = result.pillar_pct
        result.final_score = result.final_pct

        if result.final_pct >= Scorecard.BUY_THRESHOLD:
            result.verdict = "BUY"
        elif result.final_pct >= Scorecard.WATCH_THRESHOLD:
            result.verdict = "WATCH"
        else:
            result.verdict = "AVOID"

        result.star_rating = Scorecard._compute_stars(result.final_pct)
        tracking.append(
            f"ETF_VERDICT: {result.verdict} | "
            f"RATING: {result.star_rating} | "
            f"SCORE: {result.final_pct:.2f}%"
        )

        result.math_tracking = tracking
        result.verification_passed = True
        return result

    @staticmethod
    def _compute_stars(pct: float) -> str:
        if pct >= 90:
            return "★★★★★"
        elif pct >= 75:
            return "★★★★"
        elif pct >= 60:
            return "★★★"
        elif pct >= 40:
            return "★★"
        else:
            return "★"


# ------------------------------------------------------------------
# Scoring Table — exact specification sheet reference
# ------------------------------------------------------------------

SCORING_TABLE = """
╔══════════════════════════════════════════════════════════════╗
║              Universal Investment Analysis Scorecard          ║
╠══════════════════════════════════════════════════════════════╣
║ PILLAR                    WEIGHT    RAW     WEIGHTED          ║
╠══════════════════════════════════════════════════════════════╣
║ Stocks:                                                      ║
║  1. Business Quality        15%     X.X       X.XX            ║
║  2. Management              15%     X.X       X.XX            ║
║  3. Financial Strength      15%     X.X       X.XX            ║
║  4. Valuation               15%     X.X       X.XX            ║
║  5. Circle of Competence    10%     X.X       X.XX            ║
║  6. Long-Term Outlook       10%     X.X       X.XX            ║
║  7. Risk Assessment         10%     X.X       X.XX            ║
║  8. Temperament Test        10%     X.X       X.XX            ║
╠══════════════════════════════════════════════════════════════╣
║ PILLAR TOTAL               100%              XX.XX / 5.00    ║
║                                                              ║
║ RED FLAG DEDUCTIONS:                                         ║
║  0 flags = No deduction                                      ║
║  1 flag  = -0.5 from final score                             ║
║  2 flags = -1.0 from final score                             ║
║  3 flags = AUTOMATIC AVOID (overrides all scores)            ║
╠══════════════════════════════════════════════════════════════╣
║ FINAL SCORE:  XX.X%                                          ║
║ STAR RATING:  ★★★★☆                                         ║
║ VERDICT:      BUY / WATCH / AVOID                            ║
╚══════════════════════════════════════════════════════════════╝

ETFs:
╔══════════════════════════════════════════════════════════════╗
║  1. Expense Ratio           20%     X.X       X.XX            ║
║  2. Tracking Error          15%     X.X       X.XX            ║
║  3. Liquidity               15%     X.X       X.XX            ║
║  4. Holdings Quality        15%     X.X       X.XX            ║
║  5. Tax Efficiency          15%     X.X       X.XX            ║
║  6. Methodology             10%     X.X       X.XX            ║
║  7. Fit Assessment          10%     X.X       X.XX            ║
╠══════════════════════════════════════════════════════════════╣
║ ETF TOTAL                  100%              XX.XX / 5.00    ║
╚══════════════════════════════════════════════════════════════╝

BUY:   ≥ 70% and 0 red flags
WATCH: 50-69% or 1 red flag
AVOID: < 50% or 2+ red flags or flag override
"""


def format_scorecard_table(result: ScorecardResult) -> str:
    """Format ScorecardResult as the specification scoring table."""
    lines = []
    lines.append("╔══════════════════════════════════════════════════════════════╗")
    lines.append(f"║  Analysis Scorecard: {result.ticker:<42s} ║")
    lines.append("╠══════════════════════════════════════════════════════════════╣")
    lines.append("║  PILLAR TOTAL       100%              XX.XX / 5.00          ║")
    lines.append(f"║  Final: {result.final_pct:.1f}% | {result.star_rating} | {result.verdict:<20s}          ║")
    lines.append("╚══════════════════════════════════════════════════════════════╝")

    # Math tracking
    lines.append("")
    lines.append("## Arithmetic Verification Tracking")
    for i, track in enumerate(result.math_tracking, 1):
        lines.append(f"  [{i}] {track}")

    return "\n".join(lines)
