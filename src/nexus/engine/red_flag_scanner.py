"""
Red Flag Scanner — Automated sequential risk detection for stock analysis.

Implements the Universal Investment Analysis Framework's 3 Red Flags:
  Red Flag 1: Revenue and Net Income decline across 3-4 trailing quarters
  Red Flag 2: Balance sheet stress — Debt/Equity > 2.0 AND Interest Coverage < 1.5
  Red Flag 3: Cash flow validation — TTM Free Cash Flow (OCF - CapEx) negative

Scoring:
  - 0 flags: No deduction
  - 1 flag:  -0.5 from final score
  - 2 flags: -1.0 from final score
  - 3 flags: Automatic AVOID verdict (overrides all other scores)
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
    """Aggregate results from all 3 red flag checks."""
    ticker: str
    results: list[RedFlagResult] = field(default_factory=list)
    total_flags_triggered: int = 0
    total_deduction: float = 0.0
    verdict_override: Optional[str] = None  # "AVOID" if 3 flags triggered

    @property
    def is_avoid(self) -> bool:
        return self.verdict_override == "AVOID"

    @property
    def summary(self) -> str:
        lines = [f"Red Flag Scan: {self.ticker}"]
        lines.append(f"  Flags triggered: {self.total_flags_triggered}/3")
        lines.append(f"  Score deduction: {self.total_deduction}")
        if self.verdict_override:
            lines.append(f"  VERDICT OVERRIDE: {self.verdict_override}")
        for r in self.results:
            icon = "🔴" if r.status == FlagStatus.TRIGGERED else "🟡" if r.status == FlagStatus.WARNING else "🟢"
            lines.append(f"  {icon} RF{r.flag_number}: {r.flag_name} — {r.actual_value}")
        return "\n".join(lines)


class RedFlagScanner:
    """
    Sequential validator for the 3 Red Flags in the Universal Investment
    Analysis Framework. Works with data from FreeFinanceAPI.

    Usage:
        scanner = RedFlagScanner()
        results = scanner.scan(ticker, income_data, balance_data, cashflow_data)
    """

    # Thresholds
    DEBT_TO_EQUITY_THRESHOLD = 2.0
    INTEREST_COVERAGE_THRESHOLD = 1.5
    QUARTERS_TO_CHECK = 4  # trailing quarters for RF1

    # Deduction schedule
    DEDUCTION_1_FLAG = -0.5
    DEDUCTION_2_FLAGS = -1.0
    DEDUCTION_3_FLAGS = "AVOID"  # special override

    def scan(
        self,
        ticker: str,
        income_statements: list[dict[str, Any]],
        balance_sheets: list[dict[str, Any]],
        cash_flow_statements: list[dict[str, Any]],
        interest_expense: Optional[float] = None,
        ebit: Optional[float] = None,
    ) -> RedFlagScanResults:
        """
        Run all 3 red flag checks sequentially.

        Args:
            ticker: Stock ticker symbol
            income_statements: Quarterly income statements (min 4 quarters)
            balance_sheets: Quarterly balance sheets (min 1)
            cash_flow_statements: Quarterly cash flow statements (min 4 quarters for TTM)
            interest_expense: Manual override for interest expense (from income statement)
            ebit: Manual override for EBIT (from income statement)
        """
        results = RedFlagScanResults(ticker=ticker)

        # Filter out error entries
        income = [s for s in income_statements if "error" not in s]
        balance = [s for s in balance_sheets if "error" not in s]
        cashflow = [s for s in cash_flow_statements if "error" not in s]

        # Red Flag 1: Revenue & Net Income tracking
        rf1 = self._check_revenue_income_decline(ticker, income)
        results.results.append(rf1)

        # Red Flag 2: Balance sheet health
        rf2 = self._check_balance_sheet_health(ticker, balance, interest_expense, ebit)
        results.results.append(rf2)

        # Red Flag 3: Free Cash Flow validation
        rf3 = self._check_free_cash_flow(ticker, cashflow)
        results.results.append(rf3)

        # Compute aggregate
        triggered = [r for r in results.results if r.status == FlagStatus.TRIGGERED]
        results.total_flags_triggered = len(triggered)

        if results.total_flags_triggered >= 3:
            results.total_deduction = float("-inf")  # practical sentinel
            results.verdict_override = "AVOID"
        elif results.total_flags_triggered == 2:
            results.total_deduction = self.DEDUCTION_2_FLAGS
        elif results.total_flags_triggered == 1:
            results.total_deduction = self.DEDUCTION_1_FLAG
        else:
            results.total_deduction = 0.0

        return results

    # ------------------------------------------------------------------
    # RED FLAG 1: Revenue & Net Income Decline
    # ------------------------------------------------------------------

    def _check_revenue_income_decline(
        self, ticker: str, income: list[dict[str, Any]]
    ) -> RedFlagResult:
        """
        Check if revenue AND net income are declining across 3-4 trailing quarters.

        Algorithm: For each quarter pair (current vs prior), check direction.
        If both revenue and net income decline in >= 2 of the last 3 quarter pairs,
        flag is triggered.
        """
        if len(income) < 4:
            return RedFlagResult(
                flag_number=1,
                flag_name="Revenue & Net Income Decline",
                status=FlagStatus.WARNING,
                details=f"Insufficient data: only {len(income)} quarterly periods available (need 4)",
                threshold="Both revenue AND net income declining in 2+ of last 3 QoQ comparisons",
                actual_value=f"Data points: {len(income)}",
            )

        # Use most recent 4 quarters, ordered newest-first
        recent = income[:4]

        # Extract revenue and net income for each quarter
        revenues = []
        net_incomes = []
        for q in recent:
            rev = q.get("revenue")
            ni = q.get("net_income")
            if rev is not None:
                revenues.append(float(rev))
            else:
                revenues.append(None)
            if ni is not None:
                net_incomes.append(float(ni))
            else:
                net_incomes.append(None)

        # Check QoQ comparisons (newest vs prior)
        decline_count = 0
        decline_details = []

        for i in range(len(revenues) - 1):
            rev_curr = revenues[i]
            rev_prev = revenues[i + 1]
            ni_curr = net_incomes[i]
            ni_prev = net_incomes[i + 1]

            if rev_curr is None or rev_prev is None or ni_curr is None or ni_prev is None:
                continue

            rev_declined = rev_curr < rev_prev
            ni_declined = ni_curr < ni_prev

            if rev_declined and ni_declined:
                decline_count += 1
                pct_rev = ((rev_curr - rev_prev) / abs(rev_prev)) * 100 if rev_prev != 0 else 0
                pct_ni = ((ni_curr - ni_prev) / abs(ni_prev)) * 100 if ni_prev != 0 else 0
                decline_details.append(
                    f"Q{i}→Q{i+1}: Rev {pct_rev:.1f}%, NI {pct_ni:.1f}%"
                )

        # Build actual value string
        if revenues[0] and net_incomes[0]:
            actual = f"Latest Q Rev: ${revenues[0]:,.0f}, NI: ${net_incomes[0]:,.0f}; "
            actual += f"{decline_count}/3 QoQ dual-declines"
        else:
            actual = f"{decline_count}/3 QoQ dual-declines"

        if decline_count >= 2:
            return RedFlagResult(
                flag_number=1,
                flag_name="Revenue & Net Income Decline",
                status=FlagStatus.TRIGGERED,
                details=f"Dual revenue+net income decline in {decline_count} of last 3 QoQ comparisons: "
                        f"{'; '.join(decline_details)}" if decline_details else "",
                threshold="< 2 dual-decline quarters out of 3",
                actual_value=actual,
                deduction=0.0,  # aggregate at top level
            )
        elif decline_count == 1:
            return RedFlagResult(
                flag_number=1,
                flag_name="Revenue & Net Income Decline",
                status=FlagStatus.WARNING,
                details="One dual-decline quarter detected. Monitor closely.",
                threshold="< 2 dual-decline quarters out of 3",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=1,
                flag_name="Revenue & Net Income Decline",
                status=FlagStatus.CLEAR,
                details="No dual revenue+net income decline pattern detected.",
                threshold="< 2 dual-decline quarters out of 3",
                actual_value=actual,
            )

    # ------------------------------------------------------------------
    # RED FLAG 2: Balance Sheet Health (Debt/Equity + Interest Coverage)
    # ------------------------------------------------------------------

    def _check_balance_sheet_health(
        self,
        ticker: str,
        balance: list[dict[str, Any]],
        interest_expense: Optional[float] = None,
        ebit: Optional[float] = None,
    ) -> RedFlagResult:
        """
        Check if Debt-to-Equity > 2.0 AND Interest Coverage Ratio < 1.5.

        The flag triggers ONLY when BOTH conditions are met simultaneously.
        """
        if not balance:
            return RedFlagResult(
                flag_number=2,
                flag_name="Balance Sheet Stress",
                status=FlagStatus.WARNING,
                details="No balance sheet data available.",
                threshold="D/E < 2.0 AND ICR > 1.5",
                actual_value="No data",
            )

        latest = balance[0]

        total_debt = latest.get("total_debt")
        total_equity = latest.get("total_equity")

        # Compute D/E
        de_ratio = None
        if total_debt is not None and total_equity is not None and total_equity != 0:
            de_ratio = float(total_debt) / float(total_equity)

        # Compute Interest Coverage Ratio (ICR) = EBIT / Interest Expense
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
                flag_number=2,
                flag_name="Balance Sheet Stress",
                status=FlagStatus.TRIGGERED,
                details=f"Both conditions met: D/E {de_ratio:.2f} > {self.DEBT_TO_EQUITY_THRESHOLD} "
                        f"AND ICR {icr:.2f} < {self.INTEREST_COVERAGE_THRESHOLD}",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )
        elif de_triggered:
            return RedFlagResult(
                flag_number=2,
                flag_name="Balance Sheet Stress",
                status=FlagStatus.WARNING,
                details=f"D/E {de_ratio:.2f} exceeds {self.DEBT_TO_EQUITY_THRESHOLD}, but ICR is acceptable.",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )
        elif icr_triggered:
            return RedFlagResult(
                flag_number=2,
                flag_name="Balance Sheet Stress",
                status=FlagStatus.WARNING,
                details=f"ICR {icr:.2f} below {self.INTEREST_COVERAGE_THRESHOLD}, but D/E is acceptable.",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=2,
                flag_name="Balance Sheet Stress",
                status=FlagStatus.CLEAR,
                details="Both D/E and ICR within acceptable ranges.",
                threshold=f"D/E <= {self.DEBT_TO_EQUITY_THRESHOLD} AND ICR >= {self.INTEREST_COVERAGE_THRESHOLD}",
                actual_value=actual,
            )

    # ------------------------------------------------------------------
    # RED FLAG 3: Free Cash Flow Validation
    # ------------------------------------------------------------------

    def _check_free_cash_flow(
        self, ticker: str, cashflow: list[dict[str, Any]]
    ) -> RedFlagResult:
        """
        Verify TTM Free Cash Flow = Operating Cash Flow - Capital Expenditure.

        Flag triggers if TTM FCF is negative (sum of last 4 quarters).
        """
        if not cashflow:
            return RedFlagResult(
                flag_number=3,
                flag_name="Negative Free Cash Flow",
                status=FlagStatus.WARNING,
                details="No cash flow data available.",
                threshold="TTM FCF > 0",
                actual_value="No data",
            )

        # Sum TTM (last 4 quarters) OCF and CapEx
        recent = cashflow[:4]

        ttm_ocf = 0.0
        ttm_capex = 0.0
        valid_quarters = 0

        for q in recent:
            ocf = q.get("operating_cash_flow")
            capex = q.get("capital_expenditure")
            if ocf is not None:
                ttm_ocf += float(ocf)
                valid_quarters += 1
            if capex is not None:
                ttm_capex += float(capex)

        ttm_fcf = ttm_ocf - ttm_capex

        actual = (
            f"TTM OCF: ${ttm_ocf:,.0f}, "
            f"TTM CapEx: ${ttm_capex:,.0f}, "
            f"TTM FCF: ${ttm_fcf:,.0f} "
            f"({valid_quarters}/4 quarters)"
        )

        if valid_quarters < 2:
            return RedFlagResult(
                flag_number=3,
                flag_name="Negative Free Cash Flow",
                status=FlagStatus.WARNING,
                details=f"Insufficient quarterly data: {valid_quarters}/4 quarters available.",
                threshold="TTM FCF > 0",
                actual_value=actual,
            )

        if ttm_fcf < 0:
            # Check if it's a single-quarter dip or persistent
            negative_quarters = sum(
                1 for q in recent
                if q.get("free_cash_flow") is not None and float(q.get("free_cash_flow", 0)) < 0
            )
            severity = "persistent" if negative_quarters >= 3 else "recent"
            return RedFlagResult(
                flag_number=3,
                flag_name="Negative Free Cash Flow",
                status=FlagStatus.TRIGGERED,
                details=f"TTM FCF is negative ({severity}: {negative_quarters}/4 quarters negative). "
                        f"Company is burning cash.",
                threshold="TTM FCF > 0",
                actual_value=actual,
            )
        else:
            return RedFlagResult(
                flag_number=3,
                flag_name="Negative Free Cash Flow",
                status=FlagStatus.CLEAR,
                details=f"TTM FCF positive at ${ttm_fcf:,.0f}.",
                threshold="TTM FCF > 0",
                actual_value=actual,
            )


# ------------------------------------------------------------------
# Convenience: compute ICR from income statement data
# ------------------------------------------------------------------

def extract_interest_coverage(income: list[dict[str, Any]]) -> tuple[Optional[float], Optional[float]]:
    """
    Extract EBIT and Interest Expense from income statements.
    Returns (ebit, interest_expense) from the most recent period.
    """
    if not income:
        return None, None

    latest = income[0]
    ebit = latest.get("ebit")
    interest = latest.get("interest_expense")

    # yfinance doesn't always have interest_expense directly;
    # check for it under different names
    if interest is None:
        interest = latest.get("interestExpense") or latest.get("Interest Expense")

    return (
        float(ebit) if ebit is not None else None,
        float(interest) if interest is not None else None,
    )
