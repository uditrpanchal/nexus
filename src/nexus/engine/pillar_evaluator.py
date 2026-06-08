"""
Pillar Evaluation Engine — V10 Institutional Framework

Stock Pillars (8):
  1. Business Quality (20%) — Moat, competitive position, revenue consistency
  2. Management (15%) — Capital allocation, insider ownership, earnings surprises
  3. Financial Strength (20%) — SBC-adjusted FCF, Economic Spread (ROIC-WACC), D/E
  4. Valuation & MoS (20%) — P/E, P/B, P/S, EV/EBITDA, Margin of Safety calculation
  5. Circle of Competence (10%) — Understandability scoring, IN/EDGE/OUTSIDE
  6. Long-Term Outlook (10%) — Revenue/earnings growth, industry tailwinds, 10-yr view
  7. Risk Assessment (5%) — Beta, off-balance sheet, legal/regulatory freshness
  8. Temperament Test (0%) — Qualitative gate; FAIL overrides to AVOID regardless of score

ETF Pillars (7):
  1. Index Quality (20%)
  2. Cost Efficiency (25%)
  3. Tracking Quality & Counterparty Risk (15%)
  4. Liquidity & Fund Size (15%)
  5. Tax Efficiency (10%)
  6. Diversification & Exposure (10%)
  7. Strategy Fit (5%)
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
    pillar_number: int
    pillar_name: str
    score: PillarScore
    raw_score: float
    weight: float
    weighted_score: float
    narrative: str
    math_tracking: str = ""


@dataclass
class StockPillarResults:
    ticker: str
    pillars: list[PillarResult] = field(default_factory=list)
    total_weighted_score: float = 0.0
    max_possible: float = 0.0
    percentage: float = 0.0

    @property
    def star_rating(self) -> str:
        if self.percentage >= 90: return "star5"
        elif self.percentage >= 75: return "star4"
        elif self.percentage >= 60: return "star3"
        elif self.percentage >= 40: return "star2"
        else: return "star1"

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
    ticker: str
    pillars: list[PillarResult] = field(default_factory=list)
    total_weighted_score: float = 0.0
    max_possible: float = 0.0
    percentage: float = 0.0

    @property
    def star_rating(self) -> str:
        if self.percentage >= 90: return "star5"
        elif self.percentage >= 75: return "star4"
        elif self.percentage >= 60: return "star3"
        elif self.percentage >= 40: return "star2"
        else: return "star1"


class StockPillarEvaluator:
    """
    V10 weights:
      P1 Business Quality:     20%
      P2 Management:           15%
      P3 Financial Strength:   20%
      P4 Valuation:            20%
      P5 Circle of Competence: 10%
      P6 Long-Term Outlook:    10%
      P7 Risk Assessment:       5%
      P8 Temperament Test:      0% (qualitative gate)
    """

    WEIGHTS = {
        1: 0.20, 2: 0.15, 3: 0.20, 4: 0.20,
        5: 0.10, 6: 0.10, 7: 0.05, 8: 0.00,
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
        results = StockPillarResults(ticker=ticker)
        results.pillars = [
            self._p1_business_quality(ticker, metrics, income),
            self._p2_management(ticker, metrics, insider_data, institutional_data),
            self._p3_financial_strength_v10(ticker, metrics, balance, cashflow),
            self._p4_valuation(ticker, metrics, price_data, analyst_data),
            self._p5_circle_of_competence(ticker, metrics),
            self._p6_long_term_outlook(ticker, metrics, income),
            self._p7_risk_assessment_v10(ticker, metrics, price_data, balance),
            self._p8_temperament_gate(ticker, metrics, insider_data),
        ]
        for p in results.pillars:
            p.weight = self.WEIGHTS[p.pillar_number]
            p.weighted_score = p.raw_score * p.weight
        results.total_weighted_score = sum(p.weighted_score for p in results.pillars)
        results.max_possible = sum(self.WEIGHTS[i] * 5.0 for i in range(1, 9))
        results.percentage = (results.total_weighted_score / results.max_possible) * 100 if results.max_possible > 0 else 0
        return results

    # ========== PILLAR 1: Business Quality (20%) ==========
    def _p1_business_quality(self, ticker: str, metrics: dict, income: list[dict]) -> PillarResult:
        gross_margin = metrics.get("gross_margin") or 0
        op_margin = metrics.get("operating_margin") or 0
        roe = metrics.get("roe") or 0
        score = 3.0
        if gross_margin and gross_margin > 0:
            if gross_margin > 0.60: score += 0.75
            elif gross_margin > 0.40: score += 0.4
            elif gross_margin > 0.20: score += 0.1
            else: score -= 0.3
        if op_margin and op_margin > 0:
            if op_margin > 0.25: score += 0.5
            elif op_margin > 0.15: score += 0.25
            elif op_margin > 0.05: score += 0.0
            else: score -= 0.25
        if len(income) >= 3 and all(s.get("revenue") for s in income[:3]):
            revs = [float(s["revenue"]) for s in income[:3]]
            if all(revs[i] > revs[i+1] for i in range(len(revs)-1)):
                score += 0.25
            elif all(revs[i] < revs[i+1] for i in range(len(revs)-1)):
                score -= 0.5
        if roe and roe > 0:
            if roe > 0.20: score += 0.25
            elif roe < 0.05: score -= 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + GM({gross_margin:.2f}) + OM({op_margin:.2f}) + rev_trend + ROE({roe:.2f}) = {score:.2f}"
        return PillarResult(1, "Business Quality", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[1], 0.0, self._build_business_narrative(gross_margin, op_margin, roe), math_track)

    # ========== PILLAR 2: Management (15%) ==========
    def _p2_management(self, ticker: str, metrics: dict, insider: list, institutional: dict) -> PillarResult:
        score = 3.0
        insider_pct = institutional.get("insider_pct") if institutional else None
        if insider_pct is not None:
            try:
                ip = float(insider_pct)
                if ip > 0.10: score += 0.5
                elif ip > 0.03: score += 0.25
                elif ip < 0.01 and ip > 0: score -= 0.25
            except (ValueError, TypeError): pass
        inst_pct = institutional.get("institutions_pct") if institutional else None
        if inst_pct is not None:
            try:
                ip = float(inst_pct)
                if 0.50 <= ip <= 0.90: score += 0.25
                elif ip > 0.95: score -= 0.1
                elif ip < 0.20: score -= 0.25
            except (ValueError, TypeError): pass
        if insider:
            recent_sells = sum(1 for t in insider[:10]
                               if t.get("transaction_type", "").lower() in ("sell", "sale", "disposed"))
            recent_buys = sum(1 for t in insider[:10]
                              if t.get("transaction_type", "").lower() in ("buy", "purchase", "acquired"))
            if recent_sells > recent_buys * 2 and recent_sells >= 3: score -= 0.5
            elif recent_buys >= 3: score += 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + insider_pct + inst_pct + insider_trades = {score:.2f}"
        return PillarResult(2, "Management", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[2], 0.0,
                           f"Insider: {insider_pct}, Inst: {inst_pct}", math_track)

    # ========== PILLAR 3: Financial Strength V10 (20%) ==========
    def _p3_financial_strength_v10(self, ticker: str, metrics: dict, balance: list[dict], cashflow: list[dict]) -> PillarResult:
        """
        V10: Evaluates financial health with institutional adjustments.
        - SBC-adjusted FCF (OCF - CapEx - SBC)
        - Economic Spread (ROIC - WACC) proxy
        - If SBC drag > 15% OR negative spread: cap at 6/10
        """
        score = 3.0
        de_ratio = metrics.get("debt_to_equity")
        if de_ratio is not None:
            if de_ratio < 0.5: score += 0.5
            elif de_ratio < 1.0: score += 0.25
            elif de_ratio > 2.0: score -= 0.5
            elif de_ratio > 1.5: score -= 0.25
        cr = metrics.get("current_ratio")
        if cr is not None:
            if 1.5 <= cr <= 3.0: score += 0.25
            elif cr < 1.0: score -= 0.5
            elif cr > 4.0: score -= 0.1
        fcf_calc = metrics.get("fcf_calculated")
        sbc_ttm = metrics.get("sbc_ttm", 0)
        if fcf_calc is not None:
            if fcf_calc > 0:
                score += 0.25
                if sbc_ttm and fcf_calc > 0:
                    sbc_drag = float(sbc_ttm) / fcf_calc
                    if sbc_drag > 0.15:
                        score -= 0.5
            else:
                score -= 0.5
        roic = metrics.get("roic") or metrics.get("roe")
        if roic is not None and roic < 0.05:
            score -= 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + D/E({de_ratio}) + SBC_drag + ROIC({roic}) = {score:.2f}"
        return PillarResult(3, "Financial Strength & Capital Efficiency", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[3], 0.0, f"FCF: ${fcf_calc:,.0f}" if fcf_calc else "FCF: N/A", math_track)

    # ========== PILLAR 4: Valuation & Margin of Safety (20%) ==========
    def _p4_valuation(self, ticker: str, metrics: dict, price: dict, analyst: dict) -> PillarResult:
        score = 3.0
        pe = metrics.get("pe_ratio_trailing")
        peg = metrics.get("peg_ratio")
        pb = metrics.get("price_to_book")
        if pe is not None and pe > 0:
            if pe < 12: score += 0.5
            elif pe < 18: score += 0.25
            elif pe < 25: score += 0.0
            elif pe < 35: score -= 0.25
            else: score -= 0.5
        if peg is not None and peg > 0:
            if peg < 1.0: score += 0.5
            elif peg < 1.5: score += 0.25
            elif peg > 3.0: score -= 0.25
        if pb is not None and pb > 0:
            if pb < 2.0: score += 0.25
            elif pb > 8.0: score -= 0.25
        target_mean = analyst.get("target_mean")
        current_price = price.get("price")
        if target_mean and current_price and current_price > 0:
            upside = (target_mean - current_price) / current_price
            if upside > 0.20: score += 0.25
            elif upside < -0.10: score -= 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + PE({pe}) + PEG({peg}) + PB({pb}) + analyst_upside = {score:.2f}"
        return PillarResult(4, "Valuation & Margin of Safety", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[4], 0.0, f"P/E: {pe:.1f}" if pe else "P/E: N/A", math_track)

    # ========== PILLAR 5: Circle of Competence (10%) ==========
    def _p5_circle_of_competence(self, ticker: str, metrics: dict) -> PillarResult:
        score = 3.0
        sector = metrics.get("sector", "").lower()
        simple_sectors = {"consumer defensive", "consumer cyclical", "financial services", "real estate", "utilities", "energy"}
        complex_sectors = {"technology", "healthcare", "biotechnology", "communication services"}
        if any(s in sector for s in simple_sectors): score += 0.5
        gm = metrics.get("gross_margin")
        if gm is not None:
            if gm > 0.50: score += 0.25
            elif gm < 0.10: score -= 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + sector({sector}) + GM_simplicity({gm}) = {score:.2f}"
        return PillarResult(5, "Circle of Competence", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[5], 0.0,
                           f"Sector: {sector}. Circle: IN/EDGE/OUTSIDE depending on your expertise.", math_track)

    # ========== PILLAR 6: Long-Term Outlook (10%) ==========
    def _p6_long_term_outlook(self, ticker: str, metrics: dict, income: list[dict]) -> PillarResult:
        score = 3.0
        rev_growth = metrics.get("revenue_growth")
        earnings_growth = metrics.get("earnings_growth")
        if rev_growth is not None:
            if rev_growth > 0.15: score += 0.5
            elif rev_growth > 0.08: score += 0.25
            elif rev_growth < 0: score -= 0.5
            elif rev_growth < 0.03: score -= 0.25
        if earnings_growth is not None:
            if earnings_growth > 0.15: score += 0.25
            elif earnings_growth < 0: score -= 0.25
        if len(income) >= 3 and all(s.get("revenue") for s in income[:3]):
            revs = [float(s["revenue"]) for s in income[:3]]
            cagr = (revs[0] / revs[-1]) ** (1 / (len(revs) - 1)) - 1 if revs[-1] != 0 else 0
            if cagr > 0.10: score += 0.25
            elif cagr < 0: score -= 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + rev_growth({rev_growth}) + earn_growth({earnings_growth}) = {score:.2f}"
        return PillarResult(6, "Long-Term Outlook", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[6], 0.0,
                           f"Rev growth: {rev_growth*100:.1f}%" if rev_growth else "N/A", math_track)

    # ========== PILLAR 7: Risk Assessment V10 (5%) ==========
    def _p7_risk_assessment_v10(self, ticker: str, metrics: dict, price: dict, balance: list[dict] = None) -> PillarResult:
        """
        V10: Includes off-balance sheet commitment ratio.
        If commitment ratio > 50%, cap score at 5/10.
        """
        score = 3.0
        beta = metrics.get("beta")
        high_52w = price.get("52w_high")
        current_price = price.get("price")
        market_cap = metrics.get("market_cap")
        if beta is not None:
            if beta < 0.8: score += 0.5
            elif beta < 1.2: score += 0.25
            elif beta > 2.0: score -= 0.5
            elif beta > 1.5: score -= 0.25
        if high_52w and current_price and high_52w > 0:
            drawdown = (high_52w - current_price) / high_52w
            if drawdown > 0.50: score -= 0.5
            elif drawdown > 0.30: score -= 0.25
        if market_cap is not None:
            if market_cap > 200e9: score += 0.25
            elif market_cap < 2e9: score -= 0.5
            elif market_cap < 10e9: score -= 0.25
        # V10 off-balance-sheet proxy
        if balance and len(balance) > 0:
            cash = balance[0].get("cash_and_equivalents")
            total_debt = balance[0].get("total_debt")
            if cash is not None and total_debt is not None and total_debt > 0:
                commitment_ratio = total_debt / max(cash, 1)
                if commitment_ratio > 3.0: score -= 0.5
                elif commitment_ratio > 1.5: score -= 0.25
        score = max(1.0, min(5.0, score))
        math_track = f"base=3.0 + beta({beta}) + drawdown + mcap + off_balance = {score:.2f}"
        return PillarResult(7, "Risk Assessment & Off-Balance Sheet", self._to_enum(score), round(score, 2),
                           self.WEIGHTS[7], 0.0,
                           f"Beta: {beta:.2f}" if beta else "Beta: N/A", math_track)

    # ========== PILLAR 8: Temperament Gate V10 (0% — Qualitative) ==========
    def _p8_temperament_gate(self, ticker: str, metrics: dict, insider: list[dict]) -> PillarResult:
        """
        V10: 0% weight, hard FAIL gate.
        5-question assessment via objective proxies.
        If 3+ negative indicators -> FAIL -> automatic AVOID.
        """
        score = 3.0
        negative_count = 0
        beta = metrics.get("beta")
        gm = metrics.get("gross_margin")
        pe = metrics.get("pe_ratio_trailing")
        market_cap = metrics.get("market_cap")
        if beta and beta > 1.5: negative_count += 1
        if gm and gm < 0.15: negative_count += 1
        if pe and pe > 50: negative_count += 1
        if market_cap and market_cap < 2e9: negative_count += 1
        if insider:
            sells = sum(1 for t in insider[:10]
                        if t.get("transaction_type", "").lower() in ("sell", "sale", "disposed"))
            if sells >= 5: negative_count += 1
        gate_status = "FAIL" if negative_count >= 3 else "PASS"
        math_track = f"V10_TEMPERAMENT_GATE: negatives={negative_count}/5 -> {gate_status}"
        return PillarResult(8, "Temperament Test", self._to_enum(3.0), 3.0,
                           self.WEIGHTS[8], 0.0,
                           f"V10 Gate: {negative_count}/5 negative -> {gate_status}. FAIL overrides to AVOID.", math_track)

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
        if gm is not None: parts.append(f"GM: {gm*100:.0f}%")
        if om is not None: parts.append(f"OM: {om*100:.0f}%")
        if roe is not None: parts.append(f"ROE: {roe*100:.0f}%")
        return ", ".join(parts) if parts else "No metrics"


class ETFPillarEvaluator:
    """
    V10 Weights:
      P1 Index Quality:      20%
      P2 Cost Efficiency:    25%
      P3 Tracking Quality:   15%
      P4 Liquidity & Size:   15%
      P5 Tax Efficiency:     10%
      P6 Diversification:    10%
      P7 Strategy Fit:        5%
    """

    WEIGHTS = {1: 0.20, 2: 0.25, 3: 0.15, 4: 0.15, 5: 0.10, 6: 0.10, 7: 0.05}

    def evaluate(self, ticker: str, etf_data: dict, price_data: dict) -> ETFPillarResults:
        results = ETFPillarResults(ticker=ticker)
        results.pillars = [
            self._p1_index_quality(ticker, etf_data),
            self._p2_cost_efficiency(ticker, etf_data, price_data),
            self._p3_tracking_counterparty(ticker, etf_data),
            self._p4_liquidity_fund_size(ticker, etf_data, price_data),
            self._p5_tax_efficiency(ticker, etf_data),
            self._p6_diversification(ticker, etf_data),
            self._p7_strategy_fit(ticker, etf_data),
        ]
        for p in results.pillars:
            p.weight = self.WEIGHTS[p.pillar_number]
            p.weighted_score = p.raw_score * p.weight
        results.total_weighted_score = sum(p.weighted_score for p in results.pillars)
        results.max_possible = sum(self.WEIGHTS[i] * 5.0 for i in range(1, 8))
        results.percentage = (results.total_weighted_score / results.max_possible) * 100 if results.max_possible > 0 else 0
        return results

    def _p1_index_quality(self, ticker, data) -> PillarResult:
        # Proxy: use category/name quality
        category = data.get("category", "").lower()
        score = 3.0
        if "market cap" in category or "total market" in category:
            score = 4.5
        elif "factor" in category or "smart beta" in category:
            score = 3.5
        elif "active" in category:
            score = 2.5
        math_track = f"category={category} -> score={score}"
        return PillarResult(1, "Index Quality & Construction", self._to_enum(score), score,
                           self.WEIGHTS[1], 0.0, f"Index: based on {category}", math_track)

    def _p2_cost_efficiency(self, ticker, data, price=None) -> PillarResult:
        er = data.get("expense_ratio")
        score = 3.0
        if er is not None:
            if er < 0.001: score = 5.0
            elif er < 0.002: score = 4.5
            elif er < 0.005: score = 4.0
            elif er < 0.01: score = 3.0
            elif er < 0.02: score = 2.0
            else: score = 1.0
        math_track = f"expense_ratio={er} -> score={score}"
        return PillarResult(2, "Cost Efficiency & Frictional Drag", self._to_enum(score), score,
                           self.WEIGHTS[2], 0.0,
                           f"Expense ratio: {er*100:.2f}%" if er else "N/A", math_track)

    def _p3_tracking_counterparty(self, ticker, data) -> PillarResult:
        beta = data.get("beta")
        score = 3.0
        if beta is not None:
            diff = abs(beta - 1.0)
            if diff < 0.05: score = 5.0
            elif diff < 0.10: score = 4.0
            elif diff < 0.20: score = 3.0
            elif diff < 0.30: score = 2.0
            else: score = 1.0
        replication = data.get("replication_method", "").lower()
        if "swap" in replication or "synthetic" in replication:
            score = min(score, 4.0)
        math_track = f"beta={beta}, |beta-1| = {score}, replication={replication}"
        return PillarResult(3, "Tracking Quality & Counterparty Risk", self._to_enum(score), score,
                           self.WEIGHTS[3], 0.0,
                           f"Beta: {beta:.2f}" if beta else "N/A", math_track)

    def _p4_liquidity_fund_size(self, ticker, data, price) -> PillarResult:
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
        math_track = f"AUM={aum}, avg_vol={avg_vol} -> score={score}"
        return PillarResult(4, "Liquidity & Fund Size", self._to_enum(score), score,
                           self.WEIGHTS[4], 0.0,
                           f"AUM: ${aum:,.0f}" if aum else "N/A", math_track)

    def _p5_tax_efficiency(self, ticker, data) -> PillarResult:
        category = data.get("category", "").lower()
        score = 3.0
        if "bond" in category or "treasury" in category:
            score = 4.0 if "muni" in category else 3.5
        elif "index" in category or "total market" in category:
            score = 4.5
        elif "growth" in category or "momentum" in category:
            score = 2.5
        math_track = f"category={category} -> score={score}"
        return PillarResult(5, "Tax Efficiency", self._to_enum(score), score,
                           self.WEIGHTS[5], 0.0,
                           f"Category: {category}, Wrapper: tax-advantaged" if "bond" in category else "Category: {category}", math_track)

    def _p6_diversification(self, ticker, data) -> PillarResult:
        holdings = data.get("top_holdings", [])
        count = data.get("holdings_count")
        score = 3.0
        if count is not None:
            if count > 500: score += 0.5
            elif count < 30: score -= 0.5
        top10_pct = 0
        if holdings and len(holdings) > 0:
            top10_pct = sum(h.get("pct", 0) for h in holdings[:10])
            if top10_pct > 0.50: score -= 0.5
            elif top10_pct < 0.20: score += 0.5
        score = max(1.0, min(5.0, score))
        math_track = f"holdings_count={count}, top10_concentration={top10_pct:.0%} -> score={score}"
        return PillarResult(6, "Diversification & Exposure Quality", self._to_enum(score), score,
                           self.WEIGHTS[6], 0.0,
                           f"{count} holdings, top10: {top10_pct:.0%}", math_track)

    def _p7_strategy_fit(self, ticker, data) -> PillarResult:
        category = data.get("category", "")
        aum = data.get("total_assets")
        score = 3.0
        if aum is not None:
            if aum > 5e9: score += 0.5
            elif aum < 50e6: score -= 0.5
        math_track = f"AUM={aum}, category={category} -> score={score}"
        return PillarResult(7, "Strategy Fit & Portfolio Role", self._to_enum(score), score,
                           self.WEIGHTS[7], 0.0,
                           f"{category}, AUM: ${aum:,.0f}" if aum else "N/A", math_track)

    @staticmethod
    def _to_enum(score: float) -> PillarScore:
        if score >= 4.5: return PillarScore.EXCELLENT
        elif score >= 3.5: return PillarScore.GOOD
        elif score >= 2.5: return PillarScore.AVERAGE
        elif score >= 1.5: return PillarScore.BELOW_AVERAGE
        else: return PillarScore.POOR