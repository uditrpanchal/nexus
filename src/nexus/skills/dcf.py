"""
Quantitative Discounted Cash Flow (DCF) Engine for NEXUS.

Implements:
  - Multi-stage cash flow projections (5-year explicit + terminal)
  - Pluggable sector-specific WACC adjustments from sector-wacc.md
  - Long-term growth rate decay curves (competitive fade dynamics)
  - Gordon Growth Model terminal value
  - 3x3 sensitivity matrix: WACC (±1%) vs terminal growth (±0.5%)
  - Hard validation filters:
    * EV within 30% of reported market metrics
    * Terminal value capped at 50-80% of total EV
    * Growth assumptions clamped at 15% max
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ==========================================================================
# Sector WACC defaults (mirrors sector-wacc.md)
# ==========================================================================
SECTOR_WACC = {
    "Communication Services": (0.08, 0.10),
    "Consumer Discretionary": (0.08, 0.10),
    "Consumer Staples": (0.07, 0.08),
    "Energy": (0.09, 0.11),
    "Financials": (0.08, 0.10),
    "Health Care": (0.08, 0.10),
    "Industrials": (0.08, 0.09),
    "Information Technology": (0.08, 0.12),
    "Materials": (0.08, 0.10),
    "Real Estate": (0.07, 0.09),
    "Utilities": (0.06, 0.07),
    "Technology": (0.08, 0.12),  # alias
    "Healthcare": (0.08, 0.10),  # alias
}

# WACC adjustment factors
WACC_ADJUSTMENTS = {
    "high_debt": 0.015,        # D/E > 1.5
    "small_cap": 0.015,        # market cap < $2B
    "emerging_markets": 0.02,
    "concentrated_customers": 0.0075,
    "regulatory_risk": 0.01,
    "market_leader": -0.0075,  # scale advantage
    "recurring_revenue": -0.0075,
    "investment_grade": -0.005,
}

# Validation constants
MAX_GROWTH_RATE = 0.15           # 15% cap on growth assumptions
TERMINAL_VALUE_MIN_PCT = 0.50    # TV should be at least 50% of EV
TERMINAL_VALUE_MAX_PCT = 0.80    # TV should be at most 80% of EV
EV_TOLERANCE = 0.30              # EV within 30% of reported
DEFAULT_TERMINAL_GROWTH = 0.025  # 2.5% GDP proxy
DEFAULT_RISK_FREE = 0.04         # 4%
DEFAULT_ERP = 0.055              # 5.5% equity risk premium


@dataclass
class DCFInputs:
    """Inputs for a DCF valuation."""
    ticker: str
    base_fcf: float                # Most recent free cash flow
    fcf_growth_rate: float         # Projected 5-year growth rate
    wacc: float                    # Discount rate
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH
    shares_outstanding: int = 1
    net_debt: float = 0.0          # Total debt - cash
    sector: str = "Technology"
    market_cap: Optional[float] = None
    reported_ev: Optional[float] = None
    # Growth decay factors (competitive fade)
    growth_decay: list[float] = field(default_factory=lambda: [1.0, 0.95, 0.90, 0.85, 0.80])


@dataclass
class DCFProjection:
    """One year's DCF projection."""
    year: int
    fcf: float
    growth_rate: float
    discount_factor: float
    present_value: float


@dataclass
class DCFResult:
    """Complete DCF valuation result."""
    ticker: str
    enterprise_value: float
    equity_value: float
    fair_value_per_share: float
    current_price: Optional[float] = None
    upside_pct: Optional[float] = None
    terminal_value: float = 0.0
    terminal_value_pct: float = 0.0
    projections: list[DCFProjection] = field(default_factory=list)
    sensitivity_matrix: list[list[dict]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validations_passed: bool = False
    math_tracking: list[str] = field(default_factory=list)


class DCFEngine:
    """
    Multi-stage DCF valuation engine.
    """

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # WACC Estimation
    # ------------------------------------------------------------------

    def estimate_wacc(
        self,
        sector: str,
        debt_to_equity: Optional[float] = None,
        market_cap: Optional[float] = None,
        adjustments: Optional[list[str]] = None,
    ) -> float:
        """
        Estimate WACC for a company based on sector and adjustments.

        Uses the sector WACC table and applies adjustment factors.
        """
        # Get sector base range
        base_range = SECTOR_WACC.get(sector, (0.08, 0.10))
        wacc = (base_range[0] + base_range[1]) / 2  # midpoint

        # Apply adjustments
        if adjustments:
            for adj in adjustments:
                factor = WACC_ADJUSTMENTS.get(adj, 0)
                wacc += factor

        # Reasonableness check: WACC should be 6-15%
        wacc = max(0.06, min(0.15, wacc))

        return round(wacc, 4)

    # ------------------------------------------------------------------
    # DCF Computation
    # ------------------------------------------------------------------

    def compute(
        self,
        inputs: DCFInputs,
        current_price: Optional[float] = None,
    ) -> DCFResult:
        """
        Run full DCF valuation.

        Returns DCFResult with enterprise value, per-share fair value,
        sensitivity matrix, and validation results.
        """
        result = DCFResult(
            ticker=inputs.ticker,
            enterprise_value=0.0,
            equity_value=0.0,
            fair_value_per_share=0.0,
            current_price=current_price,
        )
        tracking = []

        # ---- Step 1: Validate inputs ----
        if inputs.base_fcf <= 0:
            result.warnings.append("Base FCF is negative or zero — DCF may be unreliable")
            return result

        growth_rate = min(inputs.fcf_growth_rate, MAX_GROWTH_RATE)
        if inputs.fcf_growth_rate > MAX_GROWTH_RATE:
            result.warnings.append(
                f"Growth rate {inputs.fcf_growth_rate:.1%} clamped to {MAX_GROWTH_RATE:.0%} max"
            )
        tracking.append(f"Growth rate: {growth_rate:.2%} (capped at {MAX_GROWTH_RATE:.0%})")

        wacc = max(0.05, min(0.20, inputs.wacc))
        tracking.append(f"WACC: {wacc:.2%}")

        # ---- Step 2: Project 5-year cash flows ----
        projections = []
        total_pv = 0.0
        prev_fcf = inputs.base_fcf

        for year in range(1, 6):
            # Apply growth with competitive fade
            decay = inputs.growth_decay[year - 1]
            yr_growth = growth_rate * decay
            fcf = prev_fcf * (1 + yr_growth)

            # Discount
            discount_factor = 1.0 / ((1 + wacc) ** year)
            pv = fcf * discount_factor

            projections.append(DCFProjection(
                year=year,
                fcf=round(fcf, 2),
                growth_rate=round(yr_growth, 4),
                discount_factor=round(discount_factor, 4),
                present_value=round(pv, 2),
            ))

            total_pv += pv
            prev_fcf = fcf

            tracking.append(
                f"Year {year}: FCF={fcf:,.0f} (growth={yr_growth:.2%}), "
                f"DF={discount_factor:.3f}, PV={pv:,.0f}"
            )

        result.projections = projections

        # ---- Step 3: Terminal Value (Gordon Growth Model) ----
        final_fcf = projections[-1].fcf
        terminal_growth = min(inputs.terminal_growth, 0.04)  # cap at 4%
        terminal_value = final_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
        terminal_pv = terminal_value / ((1 + wacc) ** 5)

        tracking.append(
            f"Terminal Value: TV = {final_fcf:,.0f} * (1 + {terminal_growth:.1%}) "
            f"/ ({wacc:.2%} - {terminal_growth:.1%}) = {terminal_value:,.0f}"
        )
        tracking.append(f"Terminal PV: {terminal_pv:,.0f}")

        result.terminal_value = round(terminal_value, 2)

        # ---- Step 4: Enterprise Value ----
        enterprise_value = total_pv + terminal_pv
        result.enterprise_value = round(enterprise_value, 2)
        terminal_value_pct = terminal_pv / enterprise_value if enterprise_value > 0 else 0
        result.terminal_value_pct = round(terminal_value_pct, 4)
        tracking.append(f"Enterprise Value: {enterprise_value:,.0f}")
        tracking.append(f"Terminal Value % of EV: {terminal_value_pct:.1%}")

        # ---- Step 5: Equity Value per Share ----
        equity_value = enterprise_value - inputs.net_debt
        result.equity_value = round(equity_value, 2)
        fair_value = equity_value / inputs.shares_outstanding if inputs.shares_outstanding > 0 else 0
        result.fair_value_per_share = round(fair_value, 2)
        tracking.append(
            f"Equity Value: EV({enterprise_value:,.0f}) - NetDebt({inputs.net_debt:,.0f}) = {equity_value:,.0f}"
        )
        tracking.append(
            f"Fair Value/Share: {equity_value:,.0f} / {inputs.shares_outstanding:,} shares = ${fair_value:.2f}"
        )

        # ---- Step 6: Upside ----
        if current_price and current_price > 0:
            upside = (fair_value - current_price) / current_price
            result.upside_pct = round(upside * 100, 2)
            tracking.append(
                f"Upside: (${fair_value:.2f} - ${current_price:.2f}) / ${current_price:.2f} = {upside:.1%}"
            )

        # ---- Step 7: Sensitivity Matrix (3x3) ----
        wacc_variations = [wacc - 0.01, wacc, wacc + 0.01]
        tg_variations = [0.020, 0.025, 0.030]
        matrix = []
        for w in wacc_variations:
            row = []
            for tg in tg_variations:
                w_clamped = max(0.04, min(0.20, w))
                tg_clamped = min(tg, w_clamped - 0.005)

                # Re-run with these params
                pv_sum = 0.0
                pfcf = inputs.base_fcf
                for yr in range(1, 6):
                    decay = inputs.growth_decay[yr - 1]
                    yr_g = min(growth_rate * decay, 0.20)
                    pfcf = pfcf * (1 + yr_g)
                    pv_sum += pfcf / ((1 + w_clamped) ** yr)

                tv = pfcf * (1 + tg_clamped) / max(w_clamped - tg_clamped, 0.001)
                tv_pv = tv / ((1 + w_clamped) ** 5)
                ev = pv_sum + tv_pv
                eq = ev - inputs.net_debt
                fv = eq / max(inputs.shares_outstanding, 1)

                row.append({
                    "wacc": round(w_clamped, 3),
                    "terminal_growth": round(tg_clamped, 3),
                    "fair_value": round(fv, 2),
                    "enterprise_value": round(ev, 2),
                })
            matrix.append(row)
        result.sensitivity_matrix = matrix

        # ---- Step 8: Validation ----
        self._validate(result, inputs, tracking)

        result.math_tracking = tracking
        return result

    def _validate(self, result: DCFResult, inputs: DCFInputs, tracking: list[str]):
        """Run validation checks on the DCF result."""
        warnings = result.warnings
        passed = True

        # Check 1: EV within 30% of reported
        if inputs.reported_ev and inputs.reported_ev > 0:
            ev_diff = abs(result.enterprise_value - inputs.reported_ev) / inputs.reported_ev
            if ev_diff > EV_TOLERANCE:
                warnings.append(
                    f"Calculated EV ({result.enterprise_value:,.0f}) differs "
                    f"from reported EV ({inputs.reported_ev:,.0f}) by {ev_diff:.0%} "
                    f"(tolerance: {EV_TOLERANCE:.0%})"
                )
                passed = False
            else:
                tracking.append(
                    f"Validation PASS: EV within {EV_TOLERANCE:.0%} of reported "
                    f"(diff={ev_diff:.1%})"
                )

        # Check 2: Terminal value 50-80% of EV
        if result.terminal_value_pct < TERMINAL_VALUE_MIN_PCT:
            warnings.append(
                f"Terminal value is only {result.terminal_value_pct:.1%} of EV "
                f"(should be {TERMINAL_VALUE_MIN_PCT:.0%}-{TERMINAL_VALUE_MAX_PCT:.0%})"
            )
            passed = False
        elif result.terminal_value_pct > TERMINAL_VALUE_MAX_PCT:
            warnings.append(
                f"Terminal value is {result.terminal_value_pct:.1%} of EV "
                f"(should be {TERMINAL_VALUE_MIN_PCT:.0%}-{TERMINAL_VALUE_MAX_PCT:.0%})"
            )
            passed = False
        else:
            tracking.append(
                f"Validation PASS: Terminal value {result.terminal_value_pct:.1%} "
                f"within [{TERMINAL_VALUE_MIN_PCT:.0%}-{TERMINAL_VALUE_MAX_PCT:.0%}]"
            )

        # Check 3: Growth rate capped
        if inputs.fcf_growth_rate > MAX_GROWTH_RATE:
            tracking.append(
                f"Validation NOTE: Growth capped from {inputs.fcf_growth_rate:.1%} "
                f"to {MAX_GROWTH_RATE:.0%}"
            )

        result.validations_passed = passed
        result.warnings = warnings

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------

    def format_report(self, result: DCFResult) -> str:
        """Format DCF result as a markdown report."""
        lines = []
        lines.append(f"# DCF Valuation: {result.ticker}")
        lines.append("")

        if result.warnings:
            lines.append("## Warnings")
            for w in result.warnings:
                lines.append(f"- Warning: {w}")
            lines.append("")

        # Summary
        lines.append("## Valuation Summary")
        lines.append(f"- **Enterprise Value:** ${result.enterprise_value:,.0f}")
        lines.append(f"- **Equity Value:** ${result.equity_value:,.0f}")
        lines.append(f"- **Fair Value per Share:** ${result.fair_value_per_share:.2f}")
        if result.current_price and result.upside_pct is not None:
            direction = "upside" if result.upside_pct > 0 else "downside"
            lines.append(f"- **Current Price:** ${result.current_price:.2f}")
            lines.append(f"- **{direction.title()}:** {result.upside_pct:+.1f}%")
        lines.append(f"- **Terminal Value % of EV:** {result.terminal_value_pct:.1%}")
        lines.append("")

        # Projections Table
        lines.append("## Projected Free Cash Flows")
        lines.append("| Year | FCF | Growth Rate | Discount Factor | Present Value |")
        lines.append("|------|-----|-------------|-----------------|---------------|")
        for p in result.projections:
            lines.append(
                f"| {p.year} | ${p.fcf:,.0f} | {p.growth_rate:.1%} | "
                f"{p.discount_factor:.3f} | ${p.present_value:,.0f} |"
            )
        lines.append(f"| **TV** | ${result.terminal_value:,.0f} | — | — | — |")
        lines.append(f"| **Total** | — | — | — | **${result.enterprise_value:,.0f}** |")
        lines.append("")

        # Sensitivity Matrix
        lines.append("## Sensitivity Matrix (3x3)")
        lines.append("Fair value per share varying WACC and Terminal Growth:")
        lines.append("")
        # Header
        header = "| WACC \\ TG |"
        for tg_val in [0.020, 0.025, 0.030]:
            header += f" {tg_val:.1%} |"
        lines.append(header)
        lines.append("|" + "---|" * 4)

        for row in result.sensitivity_matrix:
            wacc_str = f"| {row[0]['wacc']:.1%} |"
            for cell in row:
                wacc_str += f" ${cell['fair_value']:.2f} |"
            lines.append(wacc_str)
        lines.append("")

        # Math tracking
        lines.append("## Arithmetic Tracking")
        for i, t in enumerate(result.math_tracking, 1):
            lines.append(f"{i}. {t}")

        return "\n".join(lines)


def compute_dcf(
    ticker: str,
    base_fcf: float,
    fcf_growth_rate: float,
    sector: str = "Technology",
    current_price: Optional[float] = None,
    shares_outstanding: int = 1,
    net_debt: float = 0.0,
    reported_ev: Optional[float] = None,
) -> DCFResult:
    """
    Convenience function for quick DCF computation.
    """
    engine = DCFEngine()
    wacc = engine.estimate_wacc(sector)

    inputs = DCFInputs(
        ticker=ticker,
        base_fcf=base_fcf,
        fcf_growth_rate=fcf_growth_rate,
        wacc=wacc,
        shares_outstanding=shares_outstanding,
        net_debt=net_debt,
        sector=sector,
        reported_ev=reported_ev,
    )

    return engine.compute(inputs, current_price)
