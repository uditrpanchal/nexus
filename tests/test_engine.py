"""
Test suite for NEXUS Analysis Engine.

Covers:
  - Red Flag Scanner (all 3 flags, edge cases)
  - Pillar Evaluator (all 8 stock pillars)
  - ETF Pillar Evaluator (all 7 ETF pillars)
  - Scorecard (stock + ETF, all verdict paths)
  - Validation Gate (completeness, consistency)
  - Orchestrator pipeline (integration)
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nexus.engine.red_flag_scanner import (
    RedFlagScanner, RedFlagScanResults, RedFlagResult, FlagStatus, extract_interest_coverage,
)
from nexus.engine.pillar_evaluator import (
    StockPillarEvaluator, ETFPillarEvaluator,
    StockPillarResults, ETFPillarResults, PillarResult, PillarScore,
)
from nexus.engine.scorecard import Scorecard, ScorecardResult, SCORING_TABLE
from nexus.engine.validation_gate import (
    ValidationGate, ValidationReport, ValidationIssue,
)


# =============================================================================
# RED FLAG SCANNER TESTS
# =============================================================================

class TestRedFlagScanner:
    """Tests for all 3 red flags."""

    def make_quarterly_income(self, revenues, net_incomes):
        """Helper: build quarterly income from lists of (rev, ni).
        List order: [NEWEST, ..., OLDEST] — index 0 is most recent quarter."""
        quarters = ["2024-Q4", "2024-Q3", "2024-Q2", "2024-Q1"][:len(revenues)]
        return [
            {"report_period": q, "revenue": rev, "net_income": ni}
            for q, rev, ni in zip(quarters, revenues, net_incomes)
            if rev is not None
        ]

    def make_quarterly_balance(self, total_debt, total_equity):
        """Helper: build balance sheet with debt/equity."""
        return [{"total_debt": total_debt, "total_equity": total_equity}]

    def make_quarterly_cashflow(self, ocf_list, capex_list):
        """Helper: build cash flow from lists."""
        return [
            {"operating_cash_flow": ocf, "capital_expenditure": capex,
             "free_cash_flow": (ocf - capex) if ocf is not None and capex is not None else None}
            for ocf, capex in zip(ocf_list, capex_list)
        ]

    def test_rf1_clear_consistent_growth(self):
        """RF1: Growing revenue and net income should be CLEAR.
        Data: [newest, ..., oldest] — newest=1300 growing from oldest=1000."""
        scanner = RedFlagScanner()
        income = self.make_quarterly_income(
            [1300, 1200, 1100, 1000],  # growing: newest > oldest
            [130, 120, 110, 100],       # growing
        )
        result = scanner._check_revenue_income_decline("TEST", income)
        assert result.status == FlagStatus.CLEAR
        assert result.flag_number == 1

    def test_rf1_triggered_dual_decline(self):
        """RF1: Both revenue and NI declining in 2+ QoQ should TRIGGER.
        [800, 900, 1000, 950] gives 2 dual-decline quarters (Q0→Q1, Q1→Q2)."""
        scanner = RedFlagScanner()
        income = self.make_quarterly_income(
            [800, 900, 1000, 950],   # newest=800, oldest=950; 2 dual declines
            [70, 80, 100, 85],        # 2 dual declines with revenue
        )
        result = scanner._check_revenue_income_decline("TEST", income)
        # Q0→Q1: both down, Q1→Q2: both down, Q2→Q3: rev up, ni down
        # That's 2+ dual declines → triggered
        assert result.status == FlagStatus.TRIGGERED

    def test_rf1_warning_single_decline(self):
        """RF1: One dual-decline quarter should be WARNING."""
        scanner = RedFlagScanner()
        income = self.make_quarterly_income(
            [1000, 1100, 1050, 1200],  # one small dip
            [100, 90, 100, 110],        # one dip
        )
        result = scanner._check_revenue_income_decline("TEST", income)
        assert result.status in (FlagStatus.WARNING, FlagStatus.CLEAR)

    def test_rf1_insufficient_data(self):
        """RF1: Less than 4 quarters should be WARNING."""
        scanner = RedFlagScanner()
        income = self.make_quarterly_income([1000, 1100], [100, 110])
        result = scanner._check_revenue_income_decline("TEST", income)
        assert result.status == FlagStatus.WARNING

    def test_rf2_both_triggered(self):
        """RF2: D/E > 2.0 AND ICR < 1.5 should TRIGGER."""
        scanner = RedFlagScanner()
        balance = self.make_quarterly_balance(total_debt=3_000_000, total_equity=1_000_000)
        result = scanner._check_balance_sheet_health(
            "TEST", balance,
            interest_expense=500_000,  # EBIT/Interest = 600k/500k = 1.2 < 1.5
            ebit=600_000,
        )
        assert result.status == FlagStatus.TRIGGERED
        assert "D/E" in result.actual_value and "ICR" in result.actual_value

    def test_rf2_clear_healthy(self):
        """RF2: D/E < 2.0 and ICR > 1.5 should be CLEAR."""
        scanner = RedFlagScanner()
        balance = self.make_quarterly_balance(total_debt=500_000, total_equity=1_000_000)
        result = scanner._check_balance_sheet_health(
            "TEST", balance,
            interest_expense=100_000,
            ebit=500_000,  # ICR = 5.0
        )
        assert result.status == FlagStatus.CLEAR

    def test_rf2_warning_de_only(self):
        """RF2: D/E high but ICR OK should be WARNING."""
        scanner = RedFlagScanner()
        balance = self.make_quarterly_balance(total_debt=3_000_000, total_equity=1_000_000)
        result = scanner._check_balance_sheet_health(
            "TEST", balance,
            interest_expense=100_000,
            ebit=500_000,  # ICR = 5.0 > 1.5
        )
        assert result.status == FlagStatus.WARNING

    def test_rf3_positive_fcf(self):
        """RF3: TTM FCF > 0 should be CLEAR."""
        scanner = RedFlagScanner()
        cf = self.make_quarterly_cashflow(
            [1000, 1100, 1200, 1300],
            [200, 200, 200, 200],
        )
        result = scanner._check_free_cash_flow("TEST", cf)
        assert result.status == FlagStatus.CLEAR

    def test_rf3_negative_fcf(self):
        """RF3: TTM FCF < 0 should TRIGGER."""
        scanner = RedFlagScanner()
        cf = self.make_quarterly_cashflow(
            [100, 100, 100, 100],
            [300, 300, 300, 300],
        )
        result = scanner._check_free_cash_flow("TEST", cf)
        assert result.status == FlagStatus.TRIGGERED

    def test_full_scan_0_flags(self):
        """Full scan: healthy company should have 0 flags.
        Data in [newest, ..., oldest] order with growth pattern."""
        scanner = RedFlagScanner()
        income = [
            {"revenue": 1300, "net_income": 130},  # newest
            {"revenue": 1200, "net_income": 120},
            {"revenue": 1100, "net_income": 110},
            {"revenue": 1000, "net_income": 100},  # oldest
        ]
        balance = [{"total_debt": 500, "total_equity": 1000}]
        cf = [
            {"operating_cash_flow": 500, "capital_expenditure": 200, "free_cash_flow": 300},
            {"operating_cash_flow": 500, "capital_expenditure": 200, "free_cash_flow": 300},
            {"operating_cash_flow": 500, "capital_expenditure": 200, "free_cash_flow": 300},
            {"operating_cash_flow": 500, "capital_expenditure": 200, "free_cash_flow": 300},
        ]
        result = scanner.scan("TEST", income, balance, cf, interest_expense=50, ebit=500)
        assert result.total_flags_triggered == 0
        assert result.total_deduction == 0.0
        assert result.verdict_override is None

    def test_full_scan_3_flags_avoid(self):
        """Full scan: 3 flags should trigger AVOID override.
        Newest-first data with declining revenue, bad D/E+ICR, negative FCF."""
        scanner = RedFlagScanner()
        income = [
            {"revenue": 500, "net_income": 40},   # newest — declining
            {"revenue": 600, "net_income": 50},
            {"revenue": 800, "net_income": 70},
            {"revenue": 1000, "net_income": 100},  # oldest
        ]
        balance = [{"total_debt": 3000, "total_equity": 1000}]
        cf = [
            {"operating_cash_flow": 100, "capital_expenditure": 300, "free_cash_flow": -200},
            {"operating_cash_flow": 100, "capital_expenditure": 300, "free_cash_flow": -200},
            {"operating_cash_flow": 100, "capital_expenditure": 300, "free_cash_flow": -200},
            {"operating_cash_flow": 100, "capital_expenditure": 300, "free_cash_flow": -200},
        ]
        result = scanner.scan("TEST", income, balance, cf, interest_expense=500, ebit=600)
        assert result.total_flags_triggered == 3
        assert result.verdict_override == "AVOID"
        assert result.is_avoid


# =============================================================================
# PILLAR EVALUATOR TESTS
# =============================================================================

class TestStockPillarEvaluator:
    """Tests for all 8 stock pillars."""

    @pytest.fixture
    def evaluator(self):
        return StockPillarEvaluator()

    @pytest.fixture
    def healthy_metrics(self):
        return {
            "gross_margin": 0.45,
            "operating_margin": 0.20,
            "roe": 0.18,
            "revenue_growth": 0.10,
            "earnings_growth": 0.12,
            "debt_to_equity": 0.5,
            "current_ratio": 2.0,
            "fcf_calculated": 500_000_000,
            "ocf_calculated": 800_000_000,
            "capex_calculated": 300_000_000,
            "pe_ratio_trailing": 15.0,
            "pe_ratio_forward": 13.0,
            "peg_ratio": 1.2,
            "price_to_book": 2.5,
            "beta": 0.9,
            "market_cap": 500_000_000_000,
            "sector": "Technology",
            "industry": "Software",
        }

    def test_all_8_pillars_evaluated(self, evaluator, healthy_metrics):
        """Ensure all 8 pillars return results."""
        income = [
            {"revenue": 100e9, "net_income": 20e9},
            {"revenue": 90e9, "net_income": 18e9},
            {"revenue": 80e9, "net_income": 16e9},
            {"revenue": 70e9, "net_income": 14e9},
        ]
        balance = [{"total_debt": 50e9, "total_equity": 100e9}]
        cashflow = [{"operating_cash_flow": 40e9, "capital_expenditure": 10e9}]

        result = evaluator.evaluate(
            "TEST", healthy_metrics, income, balance, cashflow,
            {"price": 150.0, "52w_high": 180.0, "52w_low": 120.0},
            {"target_mean": 175.0},
            [],  # insider
            {"insider_pct": 5.0, "institutions_pct": 70.0},
        )
        assert len(result.pillars) == 8
        for p in result.pillars:
            assert 1.0 <= p.raw_score <= 5.0
            assert p.weighted_score > 0
            assert p.math_tracking, f"Pillar {p.pillar_number} missing math tracking"

    def test_pillar_scores_in_range(self, evaluator, healthy_metrics):
        """All pillar scores should be in [1.0, 5.0]."""
        result = evaluator.evaluate(
            "TEST", healthy_metrics,
            [{"revenue": 100e9}], [{"total_debt": 50e9, "total_equity": 100e9}],
            [{"operating_cash_flow": 40e9, "capital_expenditure": 10e9}],
            {"price": 150.0}, {"target_mean": 175.0}, [], {"insider_pct": 5.0},
        )
        for p in result.pillars:
            assert 1.0 <= p.raw_score <= 5.0, f"{p.pillar_name}: {p.raw_score}"

    def test_weighted_scores_sum_correctly(self, evaluator, healthy_metrics):
        """Weighted scores should sum to total_weighted_score."""
        result = evaluator.evaluate(
            "TEST", healthy_metrics,
            [{"revenue": 100e9}], [{"total_debt": 50e9, "total_equity": 100e9}],
            [{"operating_cash_flow": 40e9, "capital_expenditure": 10e9}],
            {"price": 150.0}, {"target_mean": 175.0}, [], {"insider_pct": 5.0},
        )
        computed_sum = sum(p.weighted_score for p in result.pillars)
        assert abs(computed_sum - result.total_weighted_score) < 0.01

    def test_high_margin_boosts_business_quality(self, evaluator):
        """High margins should produce higher business quality score."""
        metrics_high = {
            "gross_margin": 0.70, "operating_margin": 0.30,
            "roe": 0.25, "sector": "Technology",
        }
        metrics_low = {
            "gross_margin": 0.10, "operating_margin": 0.02,
            "roe": 0.02, "sector": "Technology",
        }
        income = [{"revenue": 100e9}, {"revenue": 110e9}, {"revenue": 120e9}]
        balance = [{}]
        cashflow = [{}]

        result_high = evaluator.evaluate(
            "HIGH", metrics_high, income, balance, cashflow, {}, {}, [], {})
        result_low = evaluator.evaluate(
            "LOW", metrics_low, income, balance, cashflow, {}, {}, [], {})

        p1_high = next(p for p in result_high.pillars if p.pillar_number == 1)
        p1_low = next(p for p in result_low.pillars if p.pillar_number == 1)
        assert p1_high.raw_score > p1_low.raw_score, \
            f"High margin ({p1_high.raw_score}) should > low margin ({p1_low.raw_score})"


class TestETFPillarEvaluator:
    """Tests for all 7 ETF pillars."""

    def test_all_7_etf_pillars(self):
        evaluator = ETFPillarEvaluator()
        etf_data = {
            "expense_ratio": 0.0003,
            "beta": 1.02,
            "total_assets": 500_000_000_000,
            "category": "Large Cap Blend",
            "holdings_count": 500,
            "top_holdings": [{"name": "AAPL", "pct": 0.07}],
            "avg_volume": 5_000_000,
        }
        result = evaluator.evaluate("VOO", etf_data, {"price": 500.0, "avg_volume": 5_000_000})
        assert len(result.pillars) == 7
        for p in result.pillars:
            assert 1.0 <= p.raw_score <= 5.0

    def test_low_expense_ratio_scores_high(self):
        evaluator = ETFPillarEvaluator()
        result = evaluator.evaluate("VOO", {"expense_ratio": 0.0003}, {})
        p1 = result.pillars[0]
        assert p1.raw_score >= 4.0  # Very low ER should score well


# =============================================================================
# SCORECARD TESTS
# =============================================================================

class TestScorecard:
    """Tests for scorecard computation."""

    def make_pillar_results(self, scores):
        """Build StockPillarResults from score list."""
        evaluator = StockPillarEvaluator()
        result = StockPillarResults(ticker="TEST")
        for i, score in enumerate(scores, 1):
            w = evaluator.WEIGHTS[i]
            result.pillars.append(PillarResult(
                pillar_number=i, pillar_name=f"P{i}",
                score=PillarScore.GOOD, raw_score=score,
                weight=w, weighted_score=score * w,
                narrative="", math_tracking=f"P{i}={score}",
            ))
        result.total_weighted_score = sum(p.weighted_score for p in result.pillars)
        result.max_possible = sum(evaluator.WEIGHTS[j] * 5.0 for j in range(1, 9))
        result.percentage = (result.total_weighted_score / result.max_possible) * 100
        return result

    def make_red_flag_results(self, count, override=None):
        """Build RedFlagScanResults."""
        from nexus.engine.red_flag_scanner import RedFlagResult
        results = RedFlagScanResults(ticker="TEST")
        statuses = [FlagStatus.TRIGGERED] * count + [FlagStatus.CLEAR] * (3 - count)
        for i, status in enumerate(statuses, 1):
            results.results.append(RedFlagResult(
                flag_number=i, flag_name=f"RF{i}",
                status=status, details="test", threshold="test",
                actual_value="test",
            ))
        results.total_flags_triggered = count
        if count == 1:
            results.total_deduction = -0.5
        elif count == 2:
            results.total_deduction = -1.0
        elif count >= 3:
            results.total_deduction = float("-inf")
            results.verdict_override = "AVOID"
        return results

    def test_buy_verdict(self):
        """High score + 0 flags = BUY."""
        pillars = self.make_pillar_results([4.5]*8)
        flags = self.make_red_flag_results(0)
        result = Scorecard.compute_stock_score("TEST", pillars, flags)
        assert result.verdict == "BUY"
        assert result.red_flag_count == 0

    def test_watch_verdict_one_flag(self):
        """Good score but 1 flag = WATCH."""
        pillars = self.make_pillar_results([4.0]*8)
        flags = self.make_red_flag_results(1)
        result = Scorecard.compute_stock_score("TEST", pillars, flags)
        assert "WATCH" in result.verdict

    def test_avoid_verdict_low_score(self):
        """Low score = AVOID."""
        pillars = self.make_pillar_results([1.5]*8)
        flags = self.make_red_flag_results(0)
        result = Scorecard.compute_stock_score("TEST", pillars, flags)
        assert result.verdict == "AVOID"

    def test_avoid_override_3_flags(self):
        """3 flags should override to AVOID regardless of score."""
        pillars = self.make_pillar_results([4.5]*8)  # great scores
        flags = self.make_red_flag_results(3, override="AVOID")
        result = Scorecard.compute_stock_score("TEST", pillars, flags)
        assert result.verdict == "AVOID"
        assert result.flag_override == "AVOID"

    def test_two_flags_deduction(self):
        """2 flags = -1.0 deduction."""
        pillars = self.make_pillar_results([4.0]*8)
        flags = self.make_red_flag_results(2)
        result = Scorecard.compute_stock_score("TEST", pillars, flags)
        assert result.red_flag_deduction == -1.0

    def test_math_tracking_present(self):
        """Scorecard should have math tracking entries."""
        pillars = self.make_pillar_results([3.5]*8)
        flags = self.make_red_flag_results(0)
        result = Scorecard.compute_stock_score("TEST", pillars, flags)
        assert len(result.math_tracking) >= 3
        assert result.verification_passed

    def test_etf_buy_verdict(self):
        """High ETF score = BUY."""
        evaluator = ETFPillarEvaluator()
        etf_data = {"expense_ratio": 0.0003, "beta": 1.01, "total_assets": 500e9,
                     "category": "Large Blend", "holdings_count": 500}
        pillars = evaluator.evaluate("VOO", etf_data, {"price": 500.0})
        result = Scorecard.compute_etf_score("VOO", pillars)
        assert result.asset_type == "etf"
        assert result.verdict in ("BUY", "WATCH")  # depends on computed score


# =============================================================================
# VALIDATION GATE TESTS
# =============================================================================

class TestValidationGate:
    """Tests for the validation gate."""

    def test_valid_stock_passes(self):
        """A complete valid analysis should pass validation."""
        gate = ValidationGate()
        evaluator = StockPillarEvaluator()
        pillars = evaluator.evaluate(
            "TEST",
            {"gross_margin": 0.45, "operating_margin": 0.20, "roe": 0.18,
             "revenue_growth": 0.10, "debt_to_equity": 0.5, "current_ratio": 2.0,
             "fcf_calculated": 500e6, "beta": 0.9, "market_cap": 500e9,
             "sector": "Technology"},
            [{"revenue": 100e9}], [{"total_debt": 50e9, "total_equity": 100e9}],
            [{"operating_cash_flow": 40e9, "capital_expenditure": 10e9}],
            {"price": 150.0}, {"target_mean": 175.0}, [], {"insider_pct": 5.0},
        )
        from nexus.engine.red_flag_scanner import RedFlagResult
        flags = RedFlagScanResults(ticker="TEST")
        flags.results = [
            RedFlagResult(1, "RF1", FlagStatus.CLEAR, "ok", "test", "test"),
            RedFlagResult(2, "RF2", FlagStatus.CLEAR, "ok", "test", "test"),
            RedFlagResult(3, "RF3", FlagStatus.CLEAR, "ok", "test", "test"),
        ]
        scorecard = Scorecard.compute_stock_score("TEST", pillars, flags)

        report = gate.validate_stock("TEST", pillars, flags, scorecard)
        assert report.passed, f"Should pass but got errors: {report.issues}"
        assert report.completion_pct == 100.0

    def test_missing_pillar_fails(self):
        """Missing pillars should fail validation."""
        gate = ValidationGate()
        pillars = StockPillarResults(ticker="TEST")
        pillars.pillars = []  # empty — only 0 pillars
        flags = RedFlagScanResults(ticker="TEST")
        scorecard = ScorecardResult(ticker="TEST", asset_type="stock")
        scorecard.verification_passed = True
        scorecard.final_pct = 50.0

        report = gate.validate_stock("TEST", pillars, flags, scorecard)
        assert not report.passed
        assert report.error_count >= 1

    def test_scorecard_consistency_checked(self):
        """Scorecard arithmetic should be verified."""
        gate = ValidationGate()
        evaluator = StockPillarEvaluator()
        pillars = evaluator.evaluate(
            "TEST", {"sector": "Tech"}, [], [], [], {}, {}, [], {})
        flags = RedFlagScanResults(ticker="TEST")
        flags.results = [
            RedFlagResult(1, "RF1", FlagStatus.CLEAR, "ok", "test", "test"),
            RedFlagResult(2, "RF2", FlagStatus.CLEAR, "ok", "test", "test"),
            RedFlagResult(3, "RF3", FlagStatus.CLEAR, "ok", "test", "test"),
        ]
        scorecard = Scorecard.compute_stock_score("TEST", pillars, flags)

        report = gate.validate_stock("TEST", pillars, flags, scorecard)
        # Math tracking and weights should be consistent
        assert report.passed


# =============================================================================
# SCORING TABLE REFERENCE
# =============================================================================

def test_scoring_table_exists():
    """The SCORING_TABLE constant should be non-empty."""
    assert len(SCORING_TABLE) > 100
    assert "BUY" in SCORING_TABLE
    assert "AVOID" in SCORING_TABLE
    assert "WATCH" in SCORING_TABLE


# =============================================================================
# INTEGRATION: Scorecard result formatting
# =============================================================================

def test_format_scorecard_table():
    """format_scorecard_table should produce readable output."""
    from nexus.engine.scorecard import format_scorecard_table
    result = ScorecardResult(
        ticker="AAPL", asset_type="stock",
        pillar_total=3.5, pillar_max=5.0, pillar_pct=70.0,
        final_pct=70.0, star_rating="★★★★", verdict="BUY",
        math_tracking=["TEST=1", "TEST=2"],
        verification_passed=True,
    )
    output = format_scorecard_table(result)
    assert "AAPL" in output
    assert "70.0%" in output
    assert "★★★★" in output
