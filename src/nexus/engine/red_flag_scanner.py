"""
Red Flag Scanner — Automated sequential risk detection for stock analysis.

V10 upgrade:
- 4 Red Flags instead of 3:
  RF1: Revenue and Net Income decline across 3-4 trailing quarters OR 2+ earnings misses
  RF2: Balance sheet stress — D/E > 2.0 AND Interest Coverage < 1.5
  RF3: Poor Cash Flow Quality — OCF negative 2+ quarters OR Adjusted FCF (OCF-CapEx-SBC) negative
  RF4: Capital Destruction — ROIC < WACC (negative Economic Spread)

Penalty Schedule (V10):
  - 0 flags: No deduction
  - 1 flag:  No penalty (note in verdict)
  - 2 flags: -1.0 from final weighted score + MULTI-RED-FLAG WARNING + downgrade rating
  - 3 flags: -2.0 from final weighted score + downgrade 2 tiers
  - 4 flags: Automatic AVOID verdict (overrides all pillar scores)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FlagStatus(Enum):
    CLEAR = "clear"
    WARNING = "warning"
    TRIGGERED = "triggered"


@dataclass
class RedFlagResult:
    """Result for a single red flag check."""
    flag_number: int
    flag_name: str
    status: FlagStatus
    details: str
    threshold: str
    actual_value: str
    deduction: float = 0.0


@dataclass
class RedFlagScanResults:
    """Aggregate results from all 4 red flag checks."""
    ticker: str
    results: list[RedFlagResult] = field(default_factory=list)
    total_flags_triggered: int = 0
    total_deduction: float = 0.0
    verdict_override: Optional[str] = None  # "AVOID" if 4 flags triggered
    score_penalty: float = 0.0  # V10: 2 flags = -1.0, 3 flags = -2.0

    @property
    def is_avoid(self) -> bool:
        return self.verdict_override == "AVOID"

    @property
    def summary(self) -> str:
        lines = [f"Red Flag Scan: {self.ticker}"]
        lines.append(f"  Flags triggered: {self.total_flags_triggered}/4")
        lines.append(f"  Score penalty: {self.score_penalty}")
        if self.verdict_override:
            lines.append(f"  VERDICT OVERRIDE: {self.verdict_override}")
        for r in self.results:
            icon = "🔴" if r.status == FlagStatus.TRIGGERED else "🟡" if r.status == FlagStatus.WARNING else "🟢"
            lines.append(f"  {icon} RF{r.flag_number}: {r.flag_name} — {r.actual_value}")
        return "\n".join(lines)


class RedFlagScanner:
    """
    Sequential validator for the 4 Red Flags per V10 framework.
    """

    # Thresholds
    DEBT_TO_EQUITY_THRESHOLD = 2.0
    INTEREST_COVERAGE_THRESHOLD = 1.5
    QUARTERS_TO_CHECK = 4
    EARNINGS_MISS_THRESHOLD = 2  # 2+ misses triggers RF1
    SBC_DRAG_THRESHOLD = 0.15  # 15% SBC drag triggers RF3
    OCF_NEGATIVE_QUARTERS = 2  # 2+ consecutive OCF negative

    # V10 Penalty schedule
    def compute_penalty(self, flags_triggered: int) -> tuple[float, Optional[str]]:
        """V10: 1 flag = no penalty, 2 flags = -1.0, 3 flags = -2.0, 4 flags = AVOID."""
        if flags_triggered >= 4:
            return float("-inf"), "AVOID"
        elif flags_triggered == 3:
            return -2.0, None
        elif flags_triggered == 2:
            return -1.0, None
        else:
            return 0.0, None

    def scan(
        self,
        ticker: str,
        income_statements: list[dict[str, Any]],
        balance_sheets: list[dict[str, Any]],
        cash_flow_statements: list[dict[str, Any]],
        interest_expense: Optional[float] = None,
        ebit: Optional[float] = None,
        stock_based_compensation: Optional[float] = None,
        roic: Optional[float] = None,
        wacc: Optional[float] = None,
        earnings_misses: int = 0,
        sbc_ttm: Optional[float] = None,
    ) -> RedFlagScanResults:
        """
        Run all 4 red flag checks sequentially.

        Args:
            ticker: Stock ticker symbol
            income_statements: Quarterly income statements (min 4 quarters)
            balance_sheets: Quarterly balance sheets (min 1)
            cash_flow_statements: Quarterly cash flow statements (min 4 quarters)
            interest_expense: Interest expense from income statement
            ebit: EBIT from income statement
            stock_based_compensation: SBC value for RF3 adjustment
            roic: Return on Invested Capital for RF4
            wacc: Weighted Average Cost of Capital for RF4
            earnings_misses: Count of earnings misses in last 4 quarters (for RF1)
            sbc_ttm: TTM Stock-Based Compensation for SBC drag calc
        """
        results = RedFlagScanResults(ticker=ticker)

        # Filter out error entries
        income = [s for s in income_statements if "error" not in s]
        balance = [s for s in balance_sheets if "error" not in s]
        cashflow = [s for s in cash_flow_statements if "error" not in s]

        # Red Flag 1: Revenue & Net Income decline + earnings misses
        rf1 = self._check_revenue_income_decline(ticker, income, earnings_misses)
        results.results.append(rf1)

        # Red Flag 2: Balance sheet health
        rf2 = self._check_balance_sheet_health(ticker, balance, interest_expense, ebit)
        results.results.append(rf2)

        # Red Flag 3: Cash flow quality with SBC adjustment
        rf3 = self._check_cash_flow_quality(ticker, cashflow, sbc_ttm)
        results.results.append(rf3)

        # Red Flag 4 (NEW): Capital Destruction — ROIC < WACC
        rf4 = self._check_capital_destruction(ticker, roic, wacc)
        results.results.append(rf4)

        # Compute aggregate with V10 penalty schedule
        triggered = [r for r in results.results if r.status == FlagStatus.TRIGGERED]
        results.total_flags_triggered = len(triggered)
        penalty, override = self.compute_penalty(results.total_flags_triggered)
        results.score_penalty = penalty
        results.verdict_override = override
        if override == "AVOID":
            results.total_deduction = float("-inf")
        else:
            results.total_deduction = penalty

        return results

    # ------------------------------------------------------------------
    # RED FLAG 1: Declining Revenue or Earnings (V10: + earnings misses)
    # ------------------------------------------------------------------

    def _check_revenue_income_decline(
        self, ticker: str, income: list[dict[str, Any]], earnings_misses: int = 0
    ) -> RedFlagResult:
        """
        V10: Trigger if:
          - Revenue AND net income declining for 3+ consecutive quarters OR
          - 2+ consecutive earnings misses relative to consensus
        """
        decline_triggered = False
        details_parts = []
        actual_parts = []

        # Part A: Revenue & Net Income trend
        if len(income) < 4:
            # Less than 4 quarters: partial check
            decline_triggered = False
            details_parts.append(f"Insufficient data: {len(income)} quarters (need 4)")
        else:
            recent = income[:4]
            revenues = []
            net_incomes = []
            for q in recent:
                rev = q.get("revenue")
                ni = q.get("net_income")
                revenues.append(float(rev) if rev is not None else None)
                net_incomes.append(float(ni) if ni is not None else None)

            # Check QoQ dual-declines (V10: need 3+ consecutive quarters)
            consecutive_declines = 0
            max_consecutive = 0
            for i in range(len(revenues) - 1):
                r_curr, r_prev = revenues[i], revenues[i + 1]
                ni_curr, ni_prev = net_incomes[i], net_incomes[i + 1]
                if r_curr is not None and r_prev is not None and ni_curr is not None and ni_prev is not None:
                    if r_curr < r_prev and ni_curr < ni_prev:
                        consecutive_declines += 1
                        max_consecutive = max(max_consecutive, consecutive_declines)
                    else:
                        consecutive_declines = 0

            if max_consecutive >= 3:
                decline_triggered = True
                details_parts.append(
                    f"Revenue AND net income declining for {max_consecutive} consecutive quarters"
                )

            rev_str = f"Rev: ${revenues[0]:,.0f}" if revenues[0] else "Rev: N/A"
            ni_str = f"NI: ${net_incomes[0]:,.0f}" if net_incomes[0] else "NI: N/A"
            actual_parts.append(f"{rev_str}, {ni_str}")
            actual_parts.append(f"{max_consecutive}/3 consecutive dual-declines")

        # Part B: Earnings misses (V10 addition)
        if earnings_misses >= 2:
            details_parts.append(f"{earnings_misses} earnings misses in last 4 quarters (threshold: 2)")
            if not decline_triggered:
                decline_triggered = True

        actual_parts.append(f"Earnings misses: {earnings_misses}")

        actual = " | ".join(actual_parts)
        details = "; ".join(details_parts)

        if decline_triggered:
            return RedFlagResult(
                flag_number=1,
                flag_name="Declining Revenue or Earnings",
                status=FlagStatus.TRIGGERED,
                details=details or "Multiple trigger conditions met",
                threshold="3+ consecutive dual-declines OR 2+ earnings misses",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=1,
                flag_name="Declining Revenue or Earnings",
                status=FlagStatus.CLEAR,
                details=details or "No sustained decline pattern detected",
                threshold="3+ consecutive dual-declines OR 2+ earnings misses",
                actual_value=actual,
            )

    # ------------------------------------------------------------------
    # RED FLAG 2: High Debt Levels (no change from V9)
    # ------------------------------------------------------------------

    def _check_balance_sheet_health(
        self,
        ticker: str,
        balance: list[dict[str, Any]],
        interest_expense: Optional[float] = None,
        ebit: Optional[float] = None,
    ) -> RedFlagResult:
        """V10: D/E > 2.0 AND Interest Coverage Ratio < 1.5."""
        if not balance:
            return RedFlagResult(
                flag_number=2,
                flag_name="High Debt Levels",
                status=FlagStatus.WARNING,
                details="No balance sheet data available.",
                threshold="D/E < 2.0 AND ICR > 1.5",
                actual_value="No data",
            )

        latest = balance[0]
        total_debt = latest.get("total_debt")
        total_equity = latest.get("total_equity")

        de_ratio = None
        if total_debt is not None and total_equity is not None and total_equity != 0:
            de_ratio = float(total_debt) / float(total_equity)

        icr = None
        if ebit is not None and interest_expense is not None and interest_expense != 0:
            icr = float(ebit) / float(interest_expense)

        de_str = f"D/E = {de_ratio:.2f}" if de_ratio is not None else "D/E = N/A"
        icr_str = f"ICR = {icr:.2f}" if icr is not None else "ICR = N/A"
        actual = f"{de_str}, {icr_str}"

        de_triggered = de_ratio is not None and de_ratio > self.DEBT_TO_EQUITY_THRESHOLD
        icr_triggered = icr is not None and icr < self.INTEREST_COVERAGE_THRESHOLD

        if de_triggered and icr_triggered:
            return RedFlagResult(
                flag_number=2, flag_name="High Debt Levels",
                status=FlagStatus.TRIGGERED,
                details=f"D/E {de_ratio:.2f} > {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR {icr:.2f} < {self.INTEREST_COVERAGE_THRESHOLD}",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )
        elif de_triggered:
            return RedFlagResult(
                flag_number=2, flag_name="High Debt Levels",
                status=FlagStatus.WARNING,
                details=f"D/E {de_ratio:.2f} exceeds {self.DEBT_TO_EQUITY_THRESHOLD}, ICR acceptable.",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )
        elif icr_triggered:
            return RedFlagResult(
                flag_number=2, flag_name="High Debt Levels",
                status=FlagStatus.WARNING,
                details=f"ICR {icr:.2f} below {self.INTEREST_COVERAGE_THRESHOLD}, D/E acceptable.",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=2, flag_name="High Debt Levels",
                status=FlagStatus.CLEAR,
                details="Both D/E and ICR within ranges.",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )

    # ------------------------------------------------------------------
    # RED FLAG 3: Poor Cash Flow Quality (V10: + SBC adjustment)
    # ------------------------------------------------------------------

    def _check_cash_flow_quality(
        self, ticker: str, cashflow: list[dict[str, Any]], sbc_ttm: Optional[float] = None
    ) -> RedFlagResult:
        """
        V10: Trigger if:
          - OCF negative for 2+ consecutive quarters OR
          - Adjusted FCF (OCF - CapEx - SBC) negative over TTM
        """
        if not cashflow:
            return RedFlagResult(
                flag_number=3, flag_name="Poor Cash Flow Quality",
                status=FlagStatus.WARNING,
                details="No cash flow data available.",
                threshold="Adjusted FCF > 0 (OCF - CapEx - SBC)",
                actual_value="No data",
            )

        recent = cashflow[:4]
        ttm_ocf = 0.0
        ttm_capex = 0.0
        negative_quarters = 0
        valid = 0

        for q in recent:
            ocf = q.get("operating_cash_flow")
            capex = q.get("capital_expenditure")
            if ocf is not None:
                ttm_ocf += float(ocf)
                valid += 1
                if float(ocf) < 0:
                    negative_quarters += 1
            if capex is not None:
                ttm_capex += float(capex)

        ttm_raw_fcf = ttm_ocf - ttm_capex
        sbc = float(sbc_ttm) if sbc_ttm is not None else 0.0
        ttm_adjusted_fcf = ttm_raw_fcf - sbc

        sbc_drag_pct = (sbc / ttm_raw_fcf * 100) if ttm_raw_fcf and ttm_raw_fcf != 0 else 0.0

        actual = (
            f"TTM OCF: ${ttm_ocf:,.0f}, "
            f"CapEx: ${ttm_capex:,.0f}, "
            f"SBC: ${sbc:,.0f}, "
            f"Raw FCF: ${ttm_raw_fcf:,.0f}, "
            f"Adjusted FCF: ${ttm_adjusted_fcf:,.0f}, "
            f"SBC Drag: {sbc_drag_pct:.1f}%, "
            f"OCF negative quarters: {negative_quarters}/{valid}"
        )

        ocf_negative = negative_quarters >= self.OCF_NEGATIVE_QUARTERS
        adj_fcf_negative = ttm_adjusted_fcf < 0

        if ocf_negative or adj_fcf_negative:
            reasons = []
            if ocf_negative:
                reasons.append(f"OCF negative for {negative_quarters} quarters")
            if adj_fcf_negative:
                reasons.append(f"Adjusted FCF negative: ${ttm_adjusted_fcf:,.0f}")
            return RedFlagResult(
                flag_number=3, flag_name="Poor Cash Flow Quality",
                status=FlagStatus.TRIGGERED,
                details="; ".join(reasons),
                threshold="OCF positive 3+ quarters AND Adjusted FCF > 0",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=3, flag_name="Poor Cash Flow Quality",
                status=FlagStatus.CLEAR,
                details=f"Cash flow healthy: Adjusted FCF ${ttm_adjusted_fcf:,.0f}",
                threshold="OCF positive 3+ quarters AND Adjusted FCF > 0",
                actual_value=actual,
            )

    # ------------------------------------------------------------------
    # RED FLAG 4 (NEW): Capital Destruction — ROIC < WACC
    # ------------------------------------------------------------------

    def _check_capital_destruction(
        self, ticker: str, roic: Optional[float], wacc: Optional[float]
    ) -> RedFlagResult:
        """
        V10: Trigger if ROIC < WACC (negative Economic Spread).
        The company is destroying economic value.
        """
        if roic is None or wacc is None:
            return RedFlagResult(
                flag_number=4, flag_name="Capital Destruction",
                status=FlagStatus.WARNING,
                details="ROIC or WACC data not available. Cannot compute Economic Spread.",
                threshold="ROIC >= WACC",
                actual_value=f"ROIC: {'N/A' if roic is None else f'{roic:.1%}'}, "
                            f"WACC: {'N/A' if wacc is None else f'{wacc:.1%}'}",
            )

        economic_spread = roic - wacc
        actual = f"ROIC: {roic:.1%}, WACC: {wacc:.1%}, Spread: {economic_spread:+.1%}"

        if economic_spread < 0:
            return RedFlagResult(
                flag_number=4, flag_name="Capital Destruction",
                status=FlagStatus.TRIGGERED,
                details=f"ROIC ({roic:.1%}) < WACC ({wacc:.1%}). Economic Spread: {economic_spread:.1%} — capital is being destroyed.",
                threshold="ROIC >= WACC (positive Economic Spread)",
                actual_value=actual,
            )
        elif economic_spread < 0.02:
            return RedFlagResult(
                flag_number=4, flag_name="Capital Destruction",
                status=FlagStatus.WARNING,
                details=f"ROIC barely covers WACC. Spread: {economic_spread:.1%} — close to destruction line.",
                threshold="ROIC >= WACC (positive Economic Spread)",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=4, flag_name="Capital Destruction",
                status=FlagStatus.CLEAR,
                details=f"ROIC ({roic:.1%}) > WACC ({wacc:.1%}). Positive Economic Spread. Value creation.",
                threshold="ROIC >= WACC (positive Economic Spread)",
                actual_value=actual,
            )


# Convenience: compute ICR from income statement data
def extract_interest_coverage(income: list[dict]) -> tuple[float | None, float | None]:
    """
    Extract EBIT and Interest Expense from income statements.
    Returns (ebit, interest_expense) from the most recent period.
    """
    if not income:
        return None, None
    latest = income[0]
    ebit = latest.get("ebit")
    interest = latest.get("interest_expense")
    if interest is None:
        interest = latest.get("interestExpense") or latest.get("Interest Expense")
    return (
        float(ebit) if ebit is not None else None,
        float(interest) if interest is not None else None,
    )