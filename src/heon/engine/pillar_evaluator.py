"""
Pillar Evaluation Engine — Programmatic evaluation of all 8 Stock Pillars
and 7 ETF Pillars per the Universal Investment Analysis Framework.

Stock Pillars (8):
  1. Business Quality — Moat, competitive position, revenue consistency
  2. Management — Capital allocation, insider ownership, earnings surprises
  3. Financial Strength — D/E, current ratio, FCF, manual FCF reconciliation
  4. Valuation — P/E, P/B, P/S, EV/EBITDA vs industry, DCF-based margin of safety
  5. Circle of Competence — Understandability scoring
  6. Long-Term Outlook — Revenue/earnings growth, industry tailwinds
  7. Risk Assessment — Beta, concentration, regulatory, macro risks
  8. Temperament Test — 5-question behavioral assessment

ETF Pillars (7):
  1. Expense Ratio — Cost efficiency vs category
  2. Tracking Error — Deviation from benchmark
  3. Liquidity — AUM, avg volume, bid-ask spread
  4. Holdings Quality — Top holdings concentration & quality
  5. Tax Efficiency — Turnover ratio, capital gains distribution
  6. Methodology — Index construction rules
  7. Fit Assessment — Alignment with investment goals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PillarScore(str, Enum):
    EXCELLENT = "5"
    GOOD = "4"
    AVERAGE = "3"
    BELOW_AVERAGE = "2"
    POOR = "1"


@dataclass
class PillarResult:
    """Result for a single pillar evaluation."""
    pillar_number: int
    pillar_name: str
    score: PillarScore
    raw_score: float  # 1.0 - 5.0
    weight: float  # weight in final calculation
    weighted_score: float  # raw_score * weight
    narrative: str
    math_tracking: str = ""  # Arithmetic verification string


@dataclass
class StockPillarResults:
    """Aggregate results for all 8 stock pillars."""
    ticker: str
    pillars: list[PillarResult] = field(default_factory=list)
    total_weighted_score: float = 0.0
    max_possible: float = 0.0
    percentage: float = 0.0

    @property
    def star_rating(self) -> str:
        """Convert to 5-star rating."""
        if self.percentage >= 90:
            return "★★★★★"
        elif self.percentage >= 75:
            return "★★★★"
        elif self.percentage >= 60:
            return "★★★"
        elif self.percentage >= 40:
            return "★★"
        else:
            return "★"

    @property
    def summary(self) -> str:
        lines = [f"Pillar Analysis: {self.ticker}"]
        lines.append(f"  Total: {self.total_weighted_score:.2f}/{self.max_possible:.2f} "
                     f"({self.percentage:.0f}%) — {self.star_rating}")
        for p in self.pillars:
            lines.append(f"  P{p.pillar_number} {p.pillar_name}: {p.raw_score:.1f}/5 "
                         f"(w={p.weight:.2f}) = {p.weighted_score:.2f}")
        return "\n".join(lines)


@dataclass
class ETFPillarResults:
    """Aggregate results for all 7 ETF pillars."""
    ticker: str
    pillars: list[PillarResult] = field(default_factory=list)
    total_weighted_score: float = 0.0
    max_possible: float = 0.0
    percentage: float = 0.0

    @property
    def star_rating(self) -> str:
        if self.percentage >= 90:
            return "★★★★★"
        elif self.percentage >= 75:
            return "★★★★"
        elif self.percentage >= 60:
            return "★★★"
        elif self.percentage >= 40:
            return "★★"
        else:
            return "★"


class StockPillarEvaluator:
    """
    Evaluate all 8 stock pillars using data from FreeFinanceAPI.

    Weights per the Universal Investment Analysis Framework:
      P1 Business Quality:     15%
      P2 Management:           15%
      P3 Financial Strength:    15%
      P4 Valuation:             15%
      P5 Circle of Competence:  10%
      P6 Long-Term Outlook:     10%
      P7 Risk Assessment:       10%
      P8 Temperament Test:      10%
    """

    WEIGHTS = {
        1: 0.15,  # Business Quality
        2: 0.15,  # Management
        3: 0.15,  # Financial Strength
        4: 0.15,  # Valuation
        5: 0.10,  # Circle of Competence
        6: 0.10,  # Long-Term Outlook
        7: 0.10,  # Risk Assessment
        8: 0.10,  # Temperament Test
    }

    def evaluate(
        self,
        ticker: str,
        metrics: dict[str, Any],
        income: list[dict[str, Any]],
        balance: list[dict[str, Any]],
        cashflow: list[dict[str, Any]],
        price_data: dict[str, Any],
        analyst_data: dict[str, Any],
        insider_data: list[dict[str, Any]],
        institutional_data: dict[str, Any],
    ) -> StockPillarResults:
        """
        Run complete 8-pillar evaluation.

        Args:
            ticker: Stock ticker
            metrics: From get_key_metrics()
            income: Income statements (annual, 4 periods)
            balance: Balance sheets (annual, 4 periods)
            cashflow: Cash flow statements (annual, 4 periods)
            price_data: From get_price_snapshot()
            analyst_data: From get_analyst_data()
            insider_data: From get_insider_trades()
            institutional_data: From get_major_holders()
        """
        results = StockPillarResults(ticker=ticker)
        results.pillars = [
            self._p1_business_quality(ticker, metrics, income),
            self._p2_management(ticker, metrics, insider_data, institutional_data),
            self._p3_financial_strength(ticker, metrics, balance, cashflow),
            self._p4_valuation(ticker, metrics, price_data, analyst_data),
            self._p5_circle_of_competence(ticker, metrics),
            self._p6_long_term_outlook(ticker, metrics, income),
            self._p7_risk_assessment(ticker, metrics, price_data),
            self._p8_temperament_test(ticker, metrics, insider_data),
        ]

        for p in results.pillars:
            p.weight = self.WEIGHTS[p.pillar_number]
            p.weighted_score = p.raw_score * p.weight

        results.total_weighted_score = sum(p.weighted_score for p in results.pillars)
        results.max_possible = sum(self.WEIGHTS[i] * 5.0 for i in range(1, 9))
        results.percentage = (results.total_weighted_score / results.max_possible) * 100

        return results

    # ------------------------------------------------------------------
    # PILLAR 1: BUSINESS QUALITY (15%)
    # ------------------------------------------------------------------

    def _p1_business_quality(
        self, ticker: str, metrics: dict, income: list[dict]
    ) -> PillarResult:
        """
        Evaluate moat strength via:
        - Gross margin trend (consistency of pricing power)
        - Revenue growth consistency (std dev of YoY growth)
        - Operating margin level
        - ROIC proxy (ROE as fallback)
        """
        gross_margin = metrics.get("gross_margin") or 0
        op_margin = metrics.get("operating_margin") or 0
        roe = metrics.get("roe") or 0

        score = 3.0  # baseline

        # Gross margin quality
        if gross_margin and gross_margin > 0:
            if gross_margin > 0.60:
                score += 0.75
            elif gross_margin > 0.40:
                score += 0.4
            elif gross_margin > 0.20:
                score += 0.1
            else:
                score -= 0.3

        # Operating margin
        if op_margin and op_margin > 0:
            if op_margin > 0.25:
                score += 0.5
            elif op_margin > 0.15:
                score += 0.25
            elif op_margin > 0.05:
                score += 0.0
            else:
                score -= 0.25

        # Revenue growth consistency (check income statements)
        if len(income) >= 3 and all(s.get("revenue") for s in income[:3]):
            revs = [float(s["revenue"]) for s in income[:3]]
            if all(revs[i] > revs[i+1] for i in range(len(revs)-1)):
                # Consistent growth
                score += 0.25
            elif all(revs[i] < revs[i+1] for i in range(len(revs)-1)):
                # Consistent decline
                score -= 0.5

        # ROE as quality proxy
        if roe and roe > 0:
            if roe > 0.20:
                score += 0.25
            elif roe < 0.05:
                score -= 0.25

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + GM({gross_margin:.2f}) + OM({op_margin:.2f}) + rev_trend + ROE({roe:.2f}) = {score:.2f}"

        narrative = self._build_business_narrative(gross_margin, op_margin, roe)
        return PillarResult(
            pillar_number=1, pillar_name="Business Quality",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[1], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 2: MANAGEMENT (15%)
    # ------------------------------------------------------------------

    def _p2_management(
        self, ticker: str, metrics: dict, insider: list, institutional: dict
    ) -> PillarResult:
        """
        Evaluate management quality:
        - Insider ownership (significant skin in the game)
        - Institutional ownership (smart money conviction)
        - Consistent earnings surprises
        - Capital allocation (buybacks vs dilution via shares outstanding trend)
        """
        score = 3.0

        # Insider ownership
        insider_pct = institutional.get("insider_pct") if institutional else None
        if insider_pct is not None:
            try:
                ip = float(insider_pct)
                if ip > 0.10:
                    score += 0.5  # strong insider alignment
                elif ip > 0.03:
                    score += 0.25
                elif ip < 0.01 and ip > 0:
                    score -= 0.25
            except (ValueError, TypeError):
                pass

        # Institutional ownership
        inst_pct = institutional.get("institutions_pct") if institutional else None
        if inst_pct is not None:
            try:
                ip = float(inst_pct)
                if 0.50 <= ip <= 0.90:
                    score += 0.25  # healthy institutional interest
                elif ip > 0.95:
                    score -= 0.1  # potentially over-owned
                elif ip < 0.20:
                    score -= 0.25
            except (ValueError, TypeError):
                pass

        # Check for significant insider selling
        if insider:
            recent_sells = sum(
                1 for t in insider[:10]
                if t.get("transaction_type", "").lower() in ("sell", "sale", "disposed")
            )
            recent_buys = sum(
                1 for t in insider[:10]
                if t.get("transaction_type", "").lower() in ("buy", "purchase", "acquired")
            )
            if recent_sells > recent_buys * 2 and recent_sells >= 3:
                score -= 0.5
            elif recent_buys >= 3:
                score += 0.25

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + insider_pct + inst_pct + insider_trades = {score:.2f}"

        narrative = f"Insider ownership: {insider_pct}, Institutional: {inst_pct}. "
        narrative += "Recent insider activity factored into score."
        return PillarResult(
            pillar_number=2, pillar_name="Management",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[2], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 3: FINANCIAL STRENGTH (15%)
    # ------------------------------------------------------------------

    def _p3_financial_strength(
        self, ticker: str, metrics: dict, balance: list[dict], cashflow: list[dict]
    ) -> PillarResult:
        """
        Evaluate financial health:
        - Debt-to-Equity ratio
        - Current ratio (liquidity)
        - Free Cash Flow (manual reconciliation: OCF - CapEx from statements)
        - FCF / Net Income ratio (quality of earnings)
        - Interest coverage
        """
        score = 3.0

        # D/E ratio
        de_ratio = metrics.get("debt_to_equity")
        if de_ratio is not None:
            if de_ratio < 0.5:
                score += 0.5
            elif de_ratio < 1.0:
                score += 0.25
            elif de_ratio > 2.0:
                score -= 0.5
            elif de_ratio > 1.5:
                score -= 0.25

        # Current ratio
        cr = metrics.get("current_ratio")
        if cr is not None:
            if 1.5 <= cr <= 3.0:
                score += 0.25
            elif cr < 1.0:
                score -= 0.5
            elif cr > 4.0:
                score -= 0.1  # too much idle cash

        # FCF reconciliation from cash flow statements
        fcf_calc = metrics.get("fcf_calculated")
        ocf_calc = metrics.get("ocf_calculated")
        capex_calc = metrics.get("capex_calculated")

        if fcf_calc is not None:
            if fcf_calc > 0:
                score += 0.25
                # Check FCF quality vs net income
                ni = metrics.get("calculated_profit_margin")
                if ni is not None and ocf_calc is not None:
                    fcf_yield = fcf_calc / metrics.get("market_cap", 1) if metrics.get("market_cap") else 0
                    if fcf_yield and fcf_yield > 0.05:
                        score += 0.25
            else:
                score -= 0.5

        score = max(1.0, min(5.0, score))

        # Build math tracking string with FCF reconciliation
        math_track = (
            f"base=3.0 + D/E({de_ratio}) + CR({cr}) + FCF_recon: "
            f"OCF({ocf_calc:,.0f}) - CapEx({capex_calc:,.0f}) "
            f"= FCF({fcf_calc:,.0f}) = {score:.2f}" if ocf_calc else f"base=3.0 = {score:.2f}"
        )

        narrative = (
            f"D/E: {de_ratio:.2f}" if de_ratio else "D/E: N/A"
        ) + f", CR: {cr:.2f}" if cr else ", CR: N/A"
        narrative += f", FCF: ${fcf_calc:,.0f}" if fcf_calc else ", FCF: N/A"

        return PillarResult(
            pillar_number=3, pillar_name="Financial Strength",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[3], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 4: VALUATION (15%)
    # ------------------------------------------------------------------

    def _p4_valuation(
        self, ticker: str, metrics: dict, price: dict, analyst: dict
    ) -> PillarResult:
        """
        Evaluate valuation:
        - P/E ratio vs historical range
        - P/B, P/S, EV/EBITDA
        - Analyst consensus target upside/downside
        - PEG ratio
        """
        score = 3.0

        pe = metrics.get("pe_ratio_trailing")
        peg = metrics.get("peg_ratio")
        pb = metrics.get("price_to_book")

        # P/E scoring
        if pe is not None and pe > 0:
            if pe < 12:
                score += 0.5
            elif pe < 18:
                score += 0.25
            elif pe < 25:
                score += 0.0
            elif pe < 35:
                score -= 0.25
            else:
                score -= 0.5

        # PEG ratio
        if peg is not None and peg > 0:
            if peg < 1.0:
                score += 0.5
            elif peg < 1.5:
                score += 0.25
            elif peg > 3.0:
                score -= 0.25

        # Price to Book
        if pb is not None and pb > 0:
            if pb < 2.0:
                score += 0.25
            elif pb > 8.0:
                score -= 0.25

        # Analyst target upside
        target_mean = analyst.get("target_mean")
        current_price = price.get("price")
        if target_mean and current_price and current_price > 0:
            upside = (target_mean - current_price) / current_price
            if upside > 0.20:
                score += 0.25
            elif upside < -0.10:
                score -= 0.25

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + PE({pe}) + PEG({peg}) + PB({pb}) + analyst_upside = {score:.2f}"

        narrative = f"P/E: {pe:.1f}" if pe else "P/E: N/A"
        narrative += f", PEG: {peg:.2f}" if peg else ""
        narrative += f", P/B: {pb:.2f}" if pb else ""
        if target_mean and current_price:
            upside = (target_mean - current_price) / current_price * 100
            narrative += f", Target upside: {upside:.0f}%"

        return PillarResult(
            pillar_number=4, pillar_name="Valuation",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[4], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 5: CIRCLE OF COMPETENCE (10%)
    # ------------------------------------------------------------------

    def _p5_circle_of_competence(self, ticker: str, metrics: dict) -> PillarResult:
        """
        Evaluate understandability of the business:
        - Sector clarity (some sectors are more complex than others)
        - Business model simplicity (based on gross margin stability as proxy)
        - Revenue concentration risk
        """
        score = 3.0
        sector = metrics.get("sector", "").lower()
        industry = metrics.get("industry", "").lower()

        # Sector-based scoring (simpler = higher)
        simple_sectors = {
            "consumer defensive", "consumer cyclical", "financial services",
            "real estate", "utilities", "energy",
        }
        complex_sectors = {
            "technology", "healthcare", "biotechnology", "communication services",
        }

        if any(s in sector for s in simple_sectors):
            score += 0.5
        elif any(s in sector for s in complex_sectors):
            score -= 0.0  # neutral — you CAN understand tech if you have domain expertise

        # Gross margin stability as proxy for business simplicity
        gm = metrics.get("gross_margin")
        if gm is not None:
            if gm > 0.50:
                score += 0.25  # high margin = likely strong moat/easy to understand
            elif gm < 0.10:
                score -= 0.25  # razor thin margins = complex competitive dynamics

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + sector({sector}) + GM_simplicity({gm}) = {score:.2f}"

        narrative = f"Sector: {sector}, Industry: {industry}. "
        narrative += "Circle of competence depends on your individual expertise."
        return PillarResult(
            pillar_number=5, pillar_name="Circle of Competence",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[5], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 6: LONG-TERM OUTLOOK (10%)
    # ------------------------------------------------------------------

    def _p6_long_term_outlook(
        self, ticker: str, metrics: dict, income: list[dict]
    ) -> PillarResult:
        """
        Evaluate long-term growth prospects:
        - Revenue growth rate
        - Earnings growth rate
        - Multi-year revenue trend
        - Industry tailwind assessment
        """
        score = 3.0

        rev_growth = metrics.get("revenue_growth")
        earnings_growth = metrics.get("earnings_growth")

        if rev_growth is not None:
            if rev_growth > 0.15:
                score += 0.5
            elif rev_growth > 0.08:
                score += 0.25
            elif rev_growth < 0:
                score -= 0.5
            elif rev_growth < 0.03:
                score -= 0.25

        if earnings_growth is not None:
            if earnings_growth > 0.15:
                score += 0.25
            elif earnings_growth < 0:
                score -= 0.25

        # Multi-year trend from income statements
        if len(income) >= 3 and all(s.get("revenue") for s in income[:3]):
            revs = [float(s["revenue"]) for s in income[:3]]
            cagr = (revs[0] / revs[-1]) ** (1 / (len(revs) - 1)) - 1 if revs[-1] != 0 else 0
            if cagr > 0.10:
                score += 0.25
            elif cagr < 0:
                score -= 0.25

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + rev_growth({rev_growth}) + earn_growth({earnings_growth}) = {score:.2f}"

        narrative = f"Rev growth: {rev_growth*100:.1f}%" if rev_growth else "Rev growth: N/A"
        narrative += f", Earnings growth: {earnings_growth*100:.1f}%" if earnings_growth else ""
        return PillarResult(
            pillar_number=6, pillar_name="Long-Term Outlook",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[6], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 7: RISK ASSESSMENT (10%)
    # ------------------------------------------------------------------

    def _p7_risk_assessment(
        self, ticker: str, metrics: dict, price: dict
    ) -> PillarResult:
        """
        Evaluate risk factors:
        - Beta (market sensitivity)
        - 52-week proximity (how close to highs/lows)
        - Concentration risk (single product/revenue stream proxy)
        - Market cap (small caps = more volatile)
        """
        score = 3.0

        beta = metrics.get("beta")
        high_52w = price.get("52w_high")
        current_price = price.get("price")
        market_cap = metrics.get("market_cap")

        # Beta
        if beta is not None:
            if beta < 0.8:
                score += 0.5
            elif beta < 1.2:
                score += 0.25
            elif beta > 2.0:
                score -= 0.5
            elif beta > 1.5:
                score -= 0.25

        # Distance from 52-week high (drawdown risk indicator)
        if high_52w and current_price and high_52w > 0:
            drawdown = (high_52w - current_price) / high_52w
            if drawdown > 0.30:
                score -= 0.25  # deeply off highs — may indicate problems
            elif drawdown > 0.50:
                score -= 0.5

        # Market cap (small caps riskier)
        if market_cap is not None:
            if market_cap > 200e9:
                score += 0.25  # mega-cap stability
            elif market_cap < 2e9:
                score -= 0.5  # micro-cap risk
            elif market_cap < 10e9:
                score -= 0.25  # small-cap risk

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + beta({beta}) + drawdown + mcap_size = {score:.2f}"

        narrative = f"Beta: {beta:.2f}" if beta else "Beta: N/A"
        narrative += f", Market cap: ${market_cap:,.0f}" if market_cap else ""
        if current_price and high_52w:
            pct = (current_price / high_52w) * 100
            narrative += f", {pct:.0f}% of 52w high"

        return PillarResult(
            pillar_number=7, pillar_name="Risk Assessment",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[7], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # PILLAR 8: TEMPERAMENT TEST (10%)
    # ------------------------------------------------------------------

    def _p8_temperament_test(
        self, ticker: str, metrics: dict, insider: list[dict]
    ) -> PillarResult:
        """
        5-question behavioral assessment of the investment thesis:
        1. Can you hold through a 50% drawdown without panic selling?
        2. Do you understand the business well enough to explain it in 2 minutes?
        3. Are you buying because of price action (FOMO) or because of value?
        4. Does this fit your portfolio size / diversification needs?
        5. Do you have an exit strategy if the thesis breaks?

        Score is based on OBJECTIVE indicators that inform these questions:
        - Beta/volatility (Q1 proxy)
        - Business complexity/moat (Q2 proxy)
        - Valuation vs intrinsic value (Q3 proxy)
        - Market cap & concentration (Q4 proxy)
        - Risk management indicators (Q5 proxy)
        """
        score = 3.0

        # Q1: Can you hold through 50% drawdown?
        beta = metrics.get("beta")
        if beta is not None:
            if beta < 1.0:
                score += 0.4  # lower beta = easier to hold
            elif beta > 2.0:
                score -= 0.4

        # Q2: Can you explain the business in 2 minutes?
        gm = metrics.get("gross_margin")
        if gm is not None and gm > 0.50:
            score += 0.3  # high margins = likely simple, defensible business
        elif gm is not None and gm < 0.15:
            score -= 0.2

        # Q3: FOMO vs value?
        pe = metrics.get("pe_ratio_trailing")
        if pe is not None and pe > 50:
            score -= 0.3  # very high P/E = likely momentum-driven
        elif pe is not None and pe < 12:
            score += 0.3  # low P/E = value orientation

        # Q4: Portfolio fit?
        market_cap = metrics.get("market_cap")
        if market_cap is not None:
            if market_cap > 100e9:
                score += 0.2  # large cap = easier to fit in portfolio
            elif market_cap < 2e9:
                score -= 0.2  # micro cap requires careful sizing

        # Q5: Exit strategy?
        # Proxy: insider selling = potential exit signal already flashing
        if insider:
            sells = sum(
                1 for t in insider[:10]
                if t.get("transaction_type", "").lower() in ("sell", "sale", "disposed")
            )
            if sells >= 5:
                score -= 0.3

        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + Q1(beta={beta}) + Q2(GM={gm}) + Q3(PE={pe}) + Q4(mcap) + Q5(insider) = {score:.2f}"

        narrative = (
            "Temperament Test — 5 questions assessed via objective proxies. "
            "Final score reflects the behavioral suitability of this investment."
        )
        return PillarResult(
            pillar_number=8, pillar_name="Temperament Test",
            score=self._to_enum(score), raw_score=round(score, 2),
            weight=self.WEIGHTS[8], weighted_score=0.0,
            narrative=narrative, math_tracking=math_track,
        )

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _to_enum(score: float) -> PillarScore:
        if score >= 4.5: return PillarScore.EXCELLENT
        elif score >= 3.5: return PillarScore.GOOD
        elif score >= 2.5: return PillarScore.AVERAGE
        elif score >= 1.5: return PillarScore.BELOW_AVERAGE
        else: return PillarScore.POOR

    @staticmethod
    def _build_business_narrative(gm, om, roe) -> str:
        parts = []
        if gm is not None:
            parts.append(f"Gross margin: {gm*100:.0f}%")
        if om is not None:
            parts.append(f"Operating margin: {om*100:.0f}%")
        if roe is not None:
            parts.append(f"ROE: {roe*100:.0f}%")
        return ", ".join(parts) if parts else "No metrics available"


class ETFPillarEvaluator:
    """
    Evaluate all 7 ETF pillars.

    Weights:
      P1 Expense Ratio:      20%
      P2 Tracking Error:     15%
      P3 Liquidity:          15%
      P4 Holdings Quality:   15%
      P5 Tax Efficiency:     15%
      P6 Methodology:        10%
      P7 Fit Assessment:     10%
    """

    WEIGHTS = {
        1: 0.20,
        2: 0.15,
        3: 0.15,
        4: 0.15,
        5: 0.15,
        6: 0.10,
        7: 0.10,
    }

    def evaluate(
        self,
        ticker: str,
        etf_data: dict[str, Any],
        price_data: dict[str, Any],
    ) -> ETFPillarResults:
        results = ETFPillarResults(ticker=ticker)
        results.pillars = [
            self._p1_expense_ratio(ticker, etf_data),
            self._p2_tracking_error(ticker, etf_data),
            self._p3_liquidity(ticker, etf_data, price_data),
            self._p4_holdings_quality(ticker, etf_data),
            self._p5_tax_efficiency(ticker, etf_data),
            self._p6_methodology(ticker, etf_data),
            self._p7_fit_assessment(ticker, etf_data),
        ]

        for p in results.pillars:
            p.weight = self.WEIGHTS[p.pillar_number]
            p.weighted_score = p.raw_score * p.weight

        results.total_weighted_score = sum(p.weighted_score for p in results.pillars)
        results.max_possible = sum(self.WEIGHTS[i] * 5.0 for i in range(1, 8))
        results.percentage = (results.total_weighted_score / results.max_possible) * 100

        return results

    def _p1_expense_ratio(self, ticker, data) -> PillarResult:
        er = data.get("expense_ratio")
        score = 3.0
        if er is not None:
            if er < 0.001: score = 5.0
            elif er < 0.002: score = 4.5
            elif er < 0.005: score = 4.0
            elif er < 0.01: score = 3.0
            elif er < 0.02: score = 2.0
            else: score = 1.0
        math_track = f"expense_ratio={er} → score={score}"
        return PillarResult(1, "Expense Ratio", self._to_enum(score), score,
                           self.WEIGHTS[1], 0.0,
                           f"Expense ratio: {er*100:.2f}%" if er else "N/A",
                           math_track)

    def _p2_tracking_error(self, ticker, data) -> PillarResult:
        beta = data.get("beta")
        score = 3.0
        if beta is not None:
            diff = abs(beta - 1.0)
            if diff < 0.05: score = 5.0
            elif diff < 0.10: score = 4.0
            elif diff < 0.20: score = 3.0
            elif diff < 0.30: score = 2.0
            else: score = 1.0
        math_track = f"beta={beta}, |beta-1| → score={score}"
        return PillarResult(2, "Tracking Error", self._to_enum(score), score,
                           self.WEIGHTS[2], 0.0,
                           f"Beta: {beta:.2f}" if beta else "N/A", math_track)

    def _p3_liquidity(self, ticker, data, price) -> PillarResult:
        aum = data.get("total_assets")
        avg_vol = price.get("avg_volume") or data.get("avg_volume")
        score = 3.0
        if aum is not None:
            if aum > 10e9: score += 1.0
            elif aum > 1e9: score += 0.5
            elif aum < 100e6: score -= 0.5
        if avg_vol is not None:
            if avg_vol > 10e6: score += 0.5
            elif avg_vol < 100e3: score -= 0.5
        score = max(1.0, min(5.0, score))
        math_track = f"AUM={aum}, avg_vol={avg_vol} → score={score}"
        return PillarResult(3, "Liquidity", self._to_enum(score), score,
                           self.WEIGHTS[3], 0.0,
                           f"AUM: ${aum:,.0f}" if aum else "N/A", math_track)

    def _p4_holdings_quality(self, ticker, data) -> PillarResult:
        holdings = data.get("top_holdings", [])
        count = data.get("holdings_count")
        score = 3.0
        if count is not None:
            if count > 500: score += 0.5  # well-diversified
            elif count < 30: score -= 0.5  # concentrated
        if holdings and len(holdings) > 0 and len(holdings) <= 10:
            top10_pct = sum(h.get("pct", 0) for h in holdings[:10])
            if top10_pct > 0.50: score -= 0.5
            elif top10_pct < 0.20: score += 0.5
        score = max(1.0, min(5.0, score))
        math_track = f"holdings_count={count}, top10_conc → score={score}"
        return PillarResult(4, "Holdings Quality", self._to_enum(score), score,
                           self.WEIGHTS[4], 0.0,
                           f"{count} holdings" if count else "N/A", math_track)

    def _p5_tax_efficiency(self, ticker, data) -> PillarResult:
        # Turnover ratio proxy — lower = more tax-efficient
        # yfinance may not expose directly, use category as heuristic
        category = data.get("category", "").lower()
        score = 3.0
        if "bond" in category or "treasury" in category:
            score = 4.0 if "muni" in category else 3.5  # bonds less tax-efficient unless muni
        elif "index" in category or "total market" in category:
            score = 4.5  # broad market index = low turnover
        elif "growth" in category or "momentum" in category:
            score = 2.5  # higher turnover
        math_track = f"category={category} → score={score}"
        return PillarResult(5, "Tax Efficiency", self._to_enum(score), score,
                           self.WEIGHTS[5], 0.0,
                           f"Category: {category}", math_track)

    def _p6_methodology(self, ticker, data) -> PillarResult:
        category = data.get("category", "").lower()
        score = 3.0
        if "market cap" in category or "total market" in category:
            score = 4.5  # transparent, rules-based
        elif "factor" in category or "smart beta" in category:
            score = 3.5  # slightly more complex
        elif "active" in category:
            score = 2.5  # manager-dependent
        math_track = f"category={category} → score={score}"
        return PillarResult(6, "Methodology", self._to_enum(score), score,
                           self.WEIGHTS[6], 0.0,
                           f"Category: {category}", math_track)

    def _p7_fit_assessment(self, ticker, data) -> PillarResult:
        # Generic fit — user-specific in practice
        category = data.get("category", "")
        aum = data.get("total_assets")
        score = 3.0
        if aum is not None:
            if aum > 5e9: score += 0.5
            elif aum < 50e6: score -= 0.5
        math_track = f"AUM={aum}, category={category} → score={score}"
        return PillarResult(7, "Fit Assessment", self._to_enum(score), score,
                           self.WEIGHTS[7], 0.0,
                           f"{category}, AUM: ${aum:,.0f}" if aum else "N/A", math_track)

    @staticmethod
    def _to_enum(score: float) -> PillarScore:
        if score >= 4.5: return PillarScore.EXCELLENT
        elif score >= 3.5: return PillarScore.GOOD
        elif score >= 2.5: return PillarScore.AVERAGE
        elif score >= 1.5: return PillarScore.BELOW_AVERAGE
        else: return PillarScore.POOR
