"""
Execution Loop — The core multi-agent pipeline that runs a complete analysis.

Architecture:
  1. Data Ingestion Phase — gather all required financial data in parallel
  2. Red Flag Scan Phase — sequential 3-flag validation
  3. Pillar Evaluation Phase — 8 stock pillars or 7 ETF pillars
  4. Scorecard Phase — weighted computation with arithmetic tracking
  5. Validation Gate — verify completeness before report
  6. Report Generation — format final output

All phases are programmatic (no LLM calls) — the LLM agent layer sits
above this for user interaction, but the engine itself is deterministic.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Callable

from ..engine.red_flag_scanner import (
    RedFlagScanner, RedFlagScanResults, extract_interest_coverage,
)
from ..engine.pillar_evaluator import (
    StockPillarEvaluator, StockPillarResults,
    ETFPillarEvaluator, ETFPillarResults,
)
from ..engine.scorecard import (
    Scorecard, ScorecardResult, format_scorecard_table, SCORING_TABLE,
)
from ..engine.validation_gate import (
    ValidationGate, ValidationReport,
)
from ..data_sources import FreeFinanceAPI


class PipelinePhase(str, Enum):
    DATA_INGESTION = "data_ingestion"
    RED_FLAG_SCAN = "red_flag_scan"
    PILLAR_EVALUATION = "pillar_evaluation"
    SCORECARD = "scorecard"
    VALIDATION = "validation"
    REPORT = "report"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class PipelineEvent:
    """Event emitted during pipeline execution."""
    phase: PipelinePhase
    status: str  # "start", "progress", "done", "error"
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AnalysisContext:
    """Holds all data gathered and computed during analysis."""
    ticker: str
    asset_type: str = "stock"  # "stock" or "etf"

    # Raw data
    price_data: Optional[dict] = None
    metrics: Optional[dict] = None
    income_annual: list[dict] = field(default_factory=list)
    income_quarterly: list[dict] = field(default_factory=list)
    balance_annual: list[dict] = field(default_factory=list)
    balance_quarterly: list[dict] = field(default_factory=list)
    cashflow_annual: list[dict] = field(default_factory=list)
    cashflow_quarterly: list[dict] = field(default_factory=list)
    analyst_data: Optional[dict] = None
    insider_data: list[dict] = field(default_factory=list)
    institutional_data: Optional[dict] = None
    earnings_data: list[dict] = field(default_factory=list)
    company_info: Optional[dict] = None
    etf_data: Optional[dict] = None

    # Analysis results
    red_flag_results: Optional[RedFlagScanResults] = None
    stock_pillar_results: Optional[StockPillarResults] = None
    etf_pillar_results: Optional[ETFPillarResults] = None
    scorecard_result: Optional[ScorecardResult] = None
    validation_report: Optional[ValidationReport] = None

    # Timing
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time


class AnalysisPipeline:
    """
    Complete analysis pipeline for a single ticker.

    Runs all phases sequentially with event callbacks.
    All data comes from free sources (yfinance, SEC EDGAR, web).

    Usage:
        pipeline = AnalysisPipeline()
        async for event in pipeline.run("AAPL"):
            print(event.message)
        report = pipeline.generate_report()
    """

    MAX_DATA_INGESTION_TIME = 60  # seconds
    MAX_PIPELINE_TIME = 120  # seconds

    def __init__(self, on_event: Optional[Callable[[PipelineEvent], None]] = None):
        self.api = FreeFinanceAPI()
        self.red_flag_scanner = RedFlagScanner()
        self.stock_evaluator = StockPillarEvaluator()
        self.etf_evaluator = ETFPillarEvaluator()
        self.scorecard = Scorecard()
        self.validation_gate = ValidationGate()
        self._on_event = on_event
        self._ctx: Optional[AnalysisContext] = None

    def _emit(self, phase: PipelinePhase, status: str, message: str, **data):
        event = PipelineEvent(phase=phase, status=status, message=message, data=data)
        if self._on_event:
            self._on_event(event)

    async def run(self, ticker: str, asset_type: str = "stock") -> AnalysisContext:
        """
        Run the complete analysis pipeline.

        Args:
            ticker: Stock or ETF ticker symbol
            asset_type: "stock" or "etf"

        Returns:
            AnalysisContext with all results populated
        """
        self._ctx = AnalysisContext(ticker=ticker.upper(), asset_type=asset_type)

        try:
            # Phase 1: Data Ingestion
            await self._phase_data_ingestion()

            if asset_type == "stock":
                # Phase 2: Red Flag Scan
                self._phase_red_flag_scan()

                # Phase 3: Pillar Evaluation
                self._phase_stock_pillar_evaluation()

                # Phase 4: Scorecard
                self._phase_scorecard_stock()
            else:
                # Phase 3: ETF Pillar Evaluation
                self._phase_etf_pillar_evaluation()

                # Phase 4: ETF Scorecard
                self._phase_scorecard_etf()

            # Phase 5: Validation Gate
            self._phase_validation()

            # Phase 6: Complete
            self._emit(PipelinePhase.COMPLETE, "done",
                       f"Analysis complete in {self._ctx.elapsed:.1f}s")

        except Exception as e:
            self._emit(PipelinePhase.ERROR, "error", f"Pipeline error: {str(e)}")
            raise

        return self._ctx

    # ------------------------------------------------------------------
    # PHASE 1: DATA INGESTION
    # ------------------------------------------------------------------

    async def _phase_data_ingestion(self):
        """Gather all required data from free sources in parallel where possible."""
        self._emit(PipelinePhase.DATA_INGESTION, "start",
                   f"Fetching data for {self._ctx.ticker}...")

        ticker = self._ctx.ticker

        # Fire all independent calls concurrently
        tasks = {}

        # Price data
        tasks["price"] = asyncio.to_thread(self.api.get_price_snapshot, ticker)

        # Key metrics (already fetches statements internally, but we get explicit ones too)
        tasks["metrics"] = asyncio.to_thread(self.api.get_key_metrics, ticker)

        # Financial statements (quarterly for red flags, annual for pillars)
        tasks["income_q"] = asyncio.to_thread(
            self.api.get_income_statements, ticker, "quarterly", 6
        )
        tasks["income_a"] = asyncio.to_thread(
            self.api.get_income_statements, ticker, "annual", 4
        )
        tasks["balance_q"] = asyncio.to_thread(
            self.api.get_balance_sheets, ticker, "quarterly", 6
        )
        tasks["balance_a"] = asyncio.to_thread(
            self.api.get_balance_sheets, ticker, "annual", 4
        )
        tasks["cashflow_q"] = asyncio.to_thread(
            self.api.get_cash_flow_statements, ticker, "quarterly", 6
        )
        tasks["cashflow_a"] = asyncio.to_thread(
            self.api.get_cash_flow_statements, ticker, "annual", 4
        )

        # Supplementary data
        tasks["analyst"] = asyncio.to_thread(self.api.get_analyst_data, ticker)
        tasks["insider"] = asyncio.to_thread(self.api.get_insider_trades, ticker)
        tasks["institutional"] = asyncio.to_thread(self.api.get_major_holders, ticker)
        tasks["earnings"] = asyncio.to_thread(self.api.get_earnings, ticker)
        tasks["company"] = asyncio.to_thread(self.api.get_company_info, ticker)

        if self._ctx.asset_type == "etf":
            tasks["etf"] = asyncio.to_thread(self.api.get_etf_data, ticker)

        # Gather all results
        results = {}
        for name, coro in tasks.items():
            self._emit(PipelinePhase.DATA_INGESTION, "progress",
                       f"Fetching {name}...")
            try:
                results[name] = await asyncio.wait_for(coro, timeout=30)
            except asyncio.TimeoutError:
                self._emit(PipelinePhase.DATA_INGESTION, "error",
                           f"Timeout fetching {name}")
                results[name] = {"error": "timeout"}
            except Exception as e:
                self._emit(PipelinePhase.DATA_INGESTION, "error",
                           f"Error fetching {name}: {str(e)}")
                results[name] = {"error": str(e)}

        # Populate context
        self._ctx.price_data = results.get("price", {})
        self._ctx.metrics = results.get("metrics", {})
        self._ctx.income_quarterly = results.get("income_q", [])
        self._ctx.income_annual = results.get("income_a", [])
        self._ctx.balance_quarterly = results.get("balance_q", [])
        self._ctx.balance_annual = results.get("balance_a", [])
        self._ctx.cashflow_quarterly = results.get("cashflow_q", [])
        self._ctx.cashflow_annual = results.get("cashflow_a", [])
        self._ctx.analyst_data = results.get("analyst", {})
        self._ctx.insider_data = results.get("insider", [])
        self._ctx.institutional_data = results.get("institutional", {})
        self._ctx.earnings_data = results.get("earnings", [])
        self._ctx.company_info = results.get("company", {})
        self._ctx.etf_data = results.get("etf", {})

        # Data quality check
        data_points = sum(1 for v in [
            self._ctx.price_data, self._ctx.metrics,
            self._ctx.income_quarterly, self._ctx.income_annual,
        ] if v and (isinstance(v, dict) and "error" not in v) or
                     (isinstance(v, list) and len(v) > 0))

        self._emit(PipelinePhase.DATA_INGESTION, "done",
                   f"Data ingestion complete: {data_points} data sources loaded")

    # ------------------------------------------------------------------
    # PHASE 2: RED FLAG SCAN
    # ------------------------------------------------------------------

    def _phase_red_flag_scan(self):
        """Run the 3 red flag checks on quarterly data."""
        self._emit(PipelinePhase.RED_FLAG_SCAN, "start",
                   "Running Red Flag Scanner...")

        # Extract EBIT and interest expense for RF2
        ebit, interest_expense = extract_interest_coverage(self._ctx.income_quarterly)

        results = self.red_flag_scanner.scan(
            ticker=self._ctx.ticker,
            income_statements=self._ctx.income_quarterly,
            balance_sheets=self._ctx.balance_quarterly,
            cash_flow_statements=self._ctx.cashflow_quarterly,
            interest_expense=interest_expense,
            ebit=ebit,
        )

        self._ctx.red_flag_results = results

        self._emit(PipelinePhase.RED_FLAG_SCAN, "done",
                   f"Red flags: {results.total_flags_triggered}/3 triggered"
                   + (f" — {results.verdict_override}!" if results.verdict_override else ""))

    # ------------------------------------------------------------------
    # PHASE 3: STOCK PILLAR EVALUATION
    # ------------------------------------------------------------------

    def _phase_stock_pillar_evaluation(self):
        """Evaluate all 8 stock pillars."""
        self._emit(PipelinePhase.PILLAR_EVALUATION, "start",
                   "Evaluating 8 Stock Pillars...")

        results = self.stock_evaluator.evaluate(
            ticker=self._ctx.ticker,
            metrics=self._ctx.metrics or {},
            income=self._ctx.income_annual,
            balance=self._ctx.balance_annual,
            cashflow=self._ctx.cashflow_annual,
            price_data=self._ctx.price_data or {},
            analyst_data=self._ctx.analyst_data or {},
            insider_data=self._ctx.insider_data or [],
            institutional_data=self._ctx.institutional_data or {},
        )

        self._ctx.stock_pillar_results = results

        self._emit(PipelinePhase.PILLAR_EVALUATION, "done",
                   f"Pillar score: {results.total_weighted_score:.2f}/"
                   f"{results.max_possible:.2f} ({results.percentage:.0f}%) — "
                   f"{results.star_rating}")

    # ------------------------------------------------------------------
    # PHASE 3b: ETF PILLAR EVALUATION
    # ------------------------------------------------------------------

    def _phase_etf_pillar_evaluation(self):
        """Evaluate all 7 ETF pillars."""
        self._emit(PipelinePhase.PILLAR_EVALUATION, "start",
                   "Evaluating 7 ETF Pillars...")

        results = self.etf_evaluator.evaluate(
            ticker=self._ctx.ticker,
            etf_data=self._ctx.etf_data or {},
            price_data=self._ctx.price_data or {},
        )

        self._ctx.etf_pillar_results = results

        self._emit(PipelinePhase.PILLAR_EVALUATION, "done",
                   f"ETF Pillar score: {results.total_weighted_score:.2f}/"
                   f"{results.max_possible:.2f} ({results.percentage:.0f}%) — "
                   f"{results.star_rating}")

    # ------------------------------------------------------------------
    # PHASE 4: SCORECARD
    # ------------------------------------------------------------------

    def _phase_scorecard_stock(self):
        """Compute weighted scorecard for stock."""
        self._emit(PipelinePhase.SCORECARD, "start",
                   "Computing weighted scorecard...")

        result = self.scorecard.compute_stock_score(
            ticker=self._ctx.ticker,
            pillars=self._ctx.stock_pillar_results,
            red_flags=self._ctx.red_flag_results,
        )

        self._ctx.scorecard_result = result

        self._emit(PipelinePhase.SCORECARD, "done",
                   f"Scorecard: {result.final_pct:.1f}% | "
                   f"{result.star_rating} | {result.verdict}")

    def _phase_scorecard_etf(self):
        """Compute weighted scorecard for ETF."""
        self._emit(PipelinePhase.SCORECARD, "start",
                   "Computing ETF scorecard...")

        result = self.scorecard.compute_etf_score(
            ticker=self._ctx.ticker,
            pillars=self._ctx.etf_pillar_results,
        )

        self._ctx.scorecard_result = result

        self._emit(PipelinePhase.SCORECARD, "done",
                   f"ETF Scorecard: {result.final_pct:.1f}% | "
                   f"{result.star_rating} | {result.verdict}")

    # ------------------------------------------------------------------
    # PHASE 5: VALIDATION
    # ------------------------------------------------------------------

    def _phase_validation(self):
        """Run validation gate on the complete analysis."""
        self._emit(PipelinePhase.VALIDATION, "start",
                   "Running Validation Gate...")

        if self._ctx.asset_type == "stock":
            report = self.validation_gate.validate_stock(
                ticker=self._ctx.ticker,
                pillars=self._ctx.stock_pillar_results,
                red_flags=self._ctx.red_flag_results,
                scorecard=self._ctx.scorecard_result,
            )
        else:
            report = self.validation_gate.validate_etf(
                ticker=self._ctx.ticker,
                pillars=self._ctx.etf_pillar_results,
                scorecard=self._ctx.scorecard_result,
            )

        self._ctx.validation_report = report

        if report.passed:
            self._emit(PipelinePhase.VALIDATION, "done",
                       f"Validation passed: {report.completion_pct:.0f}% complete, "
                       f"{report.warning_count} warnings")
        else:
            self._emit(PipelinePhase.VALIDATION, "error",
                       f"Validation FAILED: {report.error_count} errors, "
                       f"{report.warning_count} warnings — see report")

    # ------------------------------------------------------------------
    # REPORT GENERATION
    # ------------------------------------------------------------------

    def generate_report(self) -> str:
        """Generate the final markdown analysis report."""
        if not self._ctx:
            return "Error: No analysis context available"

        ctx = self._ctx
        lines = []

        # Header
        company_name = ""
        if ctx.company_info and "error" not in ctx.company_info:
            company_name = ctx.company_info.get("name", "") or ctx.company_info.get("short_name", "")
        sector = ctx.company_info.get("sector", "") if ctx.company_info and "error" not in ctx.company_info else ""

        lines.append(f"# HEON Analysis: {ctx.ticker}")
        if company_name:
            lines.append(f"**{company_name}** | {sector}")
        lines.append(f"*Analysis generated {time.strftime('%Y-%m-%d %H:%M UTC')}*")
        lines.append("")

        # Quick Stats
        if ctx.price_data and "error" not in ctx.price_data:
            p = ctx.price_data
            lines.append("## Quick Stats")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            if p.get("price"):
                lines.append(f"| Price | ${p['price']:,.2f} |")
            if p.get("market_cap"):
                lines.append(f"| Market Cap | ${p['market_cap']:,.0f} |")
            if p.get("52w_high") and p.get("52w_low"):
                lines.append(f"| 52-Week Range | ${p['52w_low']:,.2f} - ${p['52w_high']:,.2f} |")
            if p.get("avg_volume"):
                lines.append(f"| Avg Volume | {p['avg_volume']:,.0f} |")
            lines.append("")

        # Red Flag Scan
        if ctx.red_flag_results:
            lines.append("## Red Flag Scanner")
            lines.append(f"**Flags triggered: {ctx.red_flag_results.total_flags_triggered}/3**")
            if ctx.red_flag_results.verdict_override:
                lines.append(f"**⚠️ VERDICT OVERRIDE: {ctx.red_flag_results.verdict_override}**")
            lines.append("")
            lines.append("| # | Flag | Status | Details |")
            lines.append("|---|------|--------|---------|")
            for rf in ctx.red_flag_results.results:
                icon = "🔴" if rf.status.value == "triggered" else "🟡" if rf.status.value == "warning" else "🟢"
                lines.append(f"| {rf.flag_number} | {rf.flag_name} | {icon} {rf.status.value.upper()} | {rf.actual_value} |")
            lines.append("")

        # Pillar Results
        if ctx.stock_pillar_results:
            lines.append("## 8 Pillar Analysis")
            lines.append(f"**Total: {ctx.stock_pillar_results.total_weighted_score:.2f}/"
                        f"{ctx.stock_pillar_results.max_possible:.2f} "
                        f"({ctx.stock_pillar_results.percentage:.0f}%) — "
                        f"{ctx.stock_pillar_results.star_rating}**")
            lines.append("")
            lines.append("| # | Pillar | Score | Weight | Weighted | Narrative |")
            lines.append("|---|--------|-------|--------|----------|-----------|")
            for p in ctx.stock_pillar_results.pillars:
                lines.append(f"| {p.pillar_number} | {p.pillar_name} | "
                            f"{p.raw_score:.1f}/5 | {p.weight*100:.0f}% | "
                            f"{p.weighted_score:.2f} | {p.narrative[:80]}{'...' if len(p.narrative) > 80 else ''} |")
            lines.append("")

        if ctx.etf_pillar_results:
            lines.append("## 7 ETF Pillar Analysis")
            lines.append(f"**Total: {ctx.etf_pillar_results.total_weighted_score:.2f}/"
                        f"{ctx.etf_pillar_results.max_possible:.2f} "
                        f"({ctx.etf_pillar_results.percentage:.0f}%) — "
                        f"{ctx.etf_pillar_results.star_rating}**")
            lines.append("")
            lines.append("| # | Pillar | Score | Weight | Weighted |")
            lines.append("|---|--------|-------|--------|----------|")
            for p in ctx.etf_pillar_results.pillars:
                lines.append(f"| {p.pillar_number} | {p.pillar_name} | "
                            f"{p.raw_score:.1f}/5 | {p.weight*100:.0f}% | {p.weighted_score:.2f} |")
            lines.append("")

        # Scorecard
        if ctx.scorecard_result:
            lines.append("## Final Scorecard")
            lines.append(format_scorecard_table(ctx.scorecard_result))
            lines.append("")

        # Validation
        if ctx.validation_report:
            lines.append("## Validation Gate")
            lines.append(self.validation_gate.format_report(ctx.validation_report))
            lines.append("")

        # Key Metrics
        if ctx.metrics and "error" not in ctx.metrics:
            m = ctx.metrics
            lines.append("## Key Metrics")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            for key in ["pe_ratio_trailing", "pe_ratio_forward", "price_to_book",
                       "debt_to_equity", "roe", "roa", "gross_margin",
                       "operating_margin", "revenue_growth", "earnings_growth",
                       "dividend_yield", "free_cash_flow"]:
                val = m.get(key)
                if val is not None:
                    label = key.replace("_", " ").title()
                    if "margin" in key or "growth" in key or "yield" in key or key in ("roe", "roa"):
                        lines.append(f"| {label} | {val*100:.1f}% |")
                    elif "ratio" in key or "price" in key:
                        lines.append(f"| {label} | {val:.2f}x |")
                    else:
                        lines.append(f"| {label} | {val:,.0f} |")
            lines.append("")

        # Score weighting reference
        lines.append("---")
        lines.append(SCORING_TABLE)

        # Arithmetic tracking
        if ctx.scorecard_result and ctx.scorecard_result.math_tracking:
            lines.append("## Arithmetic Verification Tracking")
            for i, track in enumerate(ctx.scorecard_result.math_tracking, 1):
                lines.append(f"  [{i}] `{track}`")
            lines.append("")

        # Disclaimer
        lines.append("---")
        lines.append("*This analysis is generated programmatically using free data sources "
                     "(Yahoo Finance, SEC EDGAR). It is not financial advice. "
                     "All calculations are shown for verification. "
                     "Always do your own research before making investment decisions.*")

        return "\n".join(lines)

    def generate_summary(self) -> str:
        """Generate a concise one-line summary."""
        if not self._ctx or not self._ctx.scorecard_result:
            return "Analysis incomplete."

        sc = self._ctx.scorecard_result
        return (
            f"{self._ctx.ticker}: {sc.star_rating} ({sc.final_pct:.0f}%) — "
            f"{sc.verdict}"
            + (f" | {self._ctx.red_flag_results.total_flags_triggered} red flag(s)"
               if self._ctx.red_flag_results else "")
        )
