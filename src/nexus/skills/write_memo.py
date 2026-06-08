"""
Buyside Investment Memo Generator for NEXUS.

Produces publication-grade, self-contained HTML investment memos with:
  - Variant View: precise deviations from market consensus
  - Falsifiable Thesis Statements: each bullet has a "wrong if" clause
  - Macro Returns Matrix: Bear/Base/Bull with probability-weighted returns
  - Structural Risk Assayer: asymmetry profiles, steelmanned bear, catalyst tables
  - Capital Management Framework: sizing, entries, stop-loss bounds

Output: self-contained HTML file at .heon/memos/
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
import os
import time
MEMOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ))),
    ".heon", "memos"
)


@dataclass
class MemoScenario:
    """A single scenario in the returns matrix."""
    name: str  # "Bear", "Base", "Bull"
    probability: float  # 0.0 - 1.0
    revenue_growth: float
    ebit_margin: float
    exit_multiple: float
    price_target: float
    return_pct: float


@dataclass
class MemoThesis:
    """A single falsifiable thesis bullet."""
    claim: str
    evidence: str
    wrong_if: str  # observable falsifier


@dataclass
class InvestmentMemo:
    """Complete investment memo data."""
    ticker: str
    direction: str  # "LONG" or "SHORT"
    horizon: str  # "12mo", "6mo", etc.
    conviction: str  # "high", "medium", "low"
    variant_view: str
    thesis_bullets: list[MemoThesis] = field(default_factory=list)
    business_snapshot: str = ""
    whats_priced_in: str = ""
    scenarios: list[MemoScenario] = field(default_factory=list)
    bull_narrative: str = ""
    base_narrative: str = ""
    bear_narrative: str = ""
    catalysts: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    position_management: str = ""
    monitoring_kpis: list[str] = field(default_factory=list)
    analyst: str = ""
    date: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))


class MemoGenerator:
    """
    Generates buyside-quality investment memos as self-contained HTML.
    """

    def __init__(self, memo_dir: str = MEMOS_DIR):
        self.memo_dir = Path(memo_dir)
        self.memo_dir.mkdir(parents=True, exist_ok=True)

    def compute_scenario_returns(self, memo: InvestmentMemo) -> dict:
        """
        Compute probability-weighted returns and asymmetry ratio.
        Returns {prob_weighted_return, upside_downside_ratio, max_return, min_return}
        """
        if not memo.scenarios:
            return {"prob_weighted_return": 0, "upside_downside_ratio": 0}

        weighted = sum(s.probability * s.return_pct for s in memo.scenarios)

        returns = [s.return_pct for s in memo.scenarios]
        max_ret = max(returns)
        min_ret = min(returns)

        ratio = abs(max_ret / min_ret) if min_ret != 0 else float("inf")

        return {
            "prob_weighted_return": round(weighted, 1),
            "upside_downside_ratio": round(ratio, 2),
            "max_return": max_ret,
            "min_return": min_ret,
        }

    def validate(self, memo: InvestmentMemo) -> list[str]:
        """Validate memo completeness and quality. Returns list of issues."""
        issues = []

        # Variant view check
        if not memo.variant_view or len(memo.variant_view) < 50:
            issues.append("Variant view too short or missing")

        # Thesis falsifiability
        for i, t in enumerate(memo.thesis_bullets):
            if not t.wrong_if or len(t.wrong_if) < 20:
                issues.append(f"Thesis bullet {i+1} missing 'wrong if' clause")
            if not t.evidence:
                issues.append(f"Thesis bullet {i+1} missing evidence")

        # Scenario probabilities sum to 100%
        if memo.scenarios:
            prob_sum = sum(s.probability for s in memo.scenarios)
            if abs(prob_sum - 1.0) > 0.01:
                issues.append(
                    f"Scenario probabilities sum to {prob_sum:.0%}, not 100%"
                )

        # Bear case quality
        if not memo.bear_narrative or len(memo.bear_narrative) < 100:
            issues.append("Bear narrative too short — must be steelmanned")
        elif len(memo.bear_narrative) < len(memo.bull_narrative or "") * 0.7:
            issues.append("Bear narrative reads weaker than bull — rewrite required")

        # Risk tripwires
        for i, risk in enumerate(memo.risks):
            tripwire = risk.get("tripwire", "")
            if not tripwire or len(tripwire) < 15:
                issues.append(f"Risk '{risk.get('risk', '?')}' missing observable tripwire")

        # Catalyst dates
        for i, cat in enumerate(memo.catalysts):
            if not cat.get("date") or cat.get("date") == "TBD":
                issues.append(f"Catalyst '{cat.get('event', '?')}' missing date")

        return issues

    def render_html(self, memo: InvestmentMemo) -> str:
        """Render memo as self-contained HTML."""
        scenarios = memo.scenarios
        returns = self.compute_scenario_returns(memo)

        # Build scenario table rows
        scenario_rows = ""
        if scenarios:
            # Header
            cols = [s.name for s in scenarios]
            headers = "".join(f"<th>{c}</th>" for c in ["Metric"] + cols)
            scenario_rows += f"<tr>{headers}</tr>"

            # Probability
            probs = "".join(f"<td>{s.probability:.0%}</td>" for s in scenarios)
            scenario_rows += f"<tr><td>Probability</td>{probs}</tr>"

            # Revenue growth
            revs = "".join(
                f"<td>{s.revenue_growth:+.1%}</td>" if s.revenue_growth else "<td>—</td>"
                for s in scenarios
            )
            scenario_rows += f"<tr><td>Revenue Growth</td>{revs}</tr>"

            # EBIT margin
            margins = "".join(
                f"<td>{s.ebit_margin:.1%}</td>" if s.ebit_margin else "<td>—</td>"
                for s in scenarios
            )
            scenario_rows += f"<tr><td>EBIT Margin</td>{margins}</tr>"

            # Exit multiple
            exits = "".join(
                f"<td>{s.exit_multiple:.1f}x</td>" if s.exit_multiple else "<td>—</td>"
                for s in scenarios
            )
            scenario_rows += f"<tr><td>Exit Multiple</td>{exits}</tr>"

            # Price target
            pts = "".join(
                f"<td>${s.price_target:.2f}</td>" if s.price_target else "<td>—</td>"
                for s in scenarios
            )
            scenario_rows += f"<tr><td>Price Target</td>{pts}</tr>"

            # Return
            rets = "".join(
                '<td class="{}">{:+.1%}</td>'.format(
                    "pos" if s.return_pct > 0 else "neg",
                    s.return_pct,
                )
                for s in scenarios
            )
            scenario_rows += f"<tr><td>Return</td>{rets}</tr>"

        # Build thesis bullets HTML
        thesis_html = ""
        for t in memo.thesis_bullets:
            thesis_html += f"""
            <div class="thesis-item">
                <strong>{t.claim}</strong> — {t.evidence}
                <br><em class="wrong-if">Wrong if {t.wrong_if}</em>
            </div>"""

        # Build catalysts table
        cat_rows = ""
        for c in memo.catalysts:
            cat_rows += (
                f"<tr><td>{c.get('event', '')}</td>"
                f"<td>{c.get('date', '')}</td>"
                f"<td>{c.get('impact', '')}</td></tr>"
            )

        # Build risks table
        risk_rows = ""
        for r in memo.risks:
            risk_rows += (
                "<tr><td>{risk}</td>"
                "<td>{mitigant}</td>"
                '<td class="tripwire">{tripwire}</td></tr>'
            ).format(
                risk=r.get("risk", ""),
                mitigant=r.get("mitigant", ""),
                tripwire=r.get("tripwire", ""),
            )

        # Build KPIs
        kpis_html = "".join(f"<li>{k}</li>" for k in memo.monitoring_kpis)

        asy_str = f"{returns['upside_downside_ratio']:.1f}x"
        asy_class = "asy-good" if returns["upside_downside_ratio"] >= 2.0 else "asy-weak"
        if returns["upside_downside_ratio"] == float("inf"):
            asy_str = "N/A (no downside)"
            asy_class = "asy-good"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{memo.ticker} · {memo.direction} · Investment Memo</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 40px 20px; color: #1a1a1a; line-height: 1.6; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  h2 {{ font-size: 18px; margin-top: 32px; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }}
  .header-meta {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 8px; }}
  .tag-long {{ background: #e8f5e9; color: #2e7d32; }}
  .tag-short {{ background: #fce4ec; color: #c62828; }}
  .conviction-high {{ background: #e8f5e9; }}
  .conviction-medium {{ background: #fff3e0; }}
  .conviction-low {{ background: #f5f5f5; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  .pos {{ color: #2e7d32; font-weight: 600; }}
  .neg {{ color: #c62828; font-weight: 600; }}
  .tripwire {{ color: #e65100; font-weight: 500; }}
  .wrong-if {{ color: #666; font-size: 13px; }}
  .thesis-item {{ margin-bottom: 12px; padding-left: 12px; border-left: 3px solid #1976d2; }}
  .variant-view {{ background: #e3f2fd; padding: 16px; border-radius: 8px; margin: 16px 0; font-size: 15px; }}
  .asymmetry {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 13px; }}
  .asy-good {{ background: #e8f5e9; color: #2e7d32; }}
  .asy-weak {{ background: #fff3e0; color: #e65100; }}
  .section-label {{ font-size: 12px; color: #999; text-transform: uppercase; letter-spacing: 1px; margin-top: 24px; }}
  .kpi-list {{ list-style-type: none; padding: 0; }}
  .kpi-list li {{ padding: 4px 0; }}
  .kpi-list li::before {{ content: '▸ '; color: #1976d2; }}
  .footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid #e0e0e0; font-size: 12px; color: #999; }}
</style>
</head>
<body>

<h1>{memo.ticker} · {memo.direction}</h1>
<div class="header-meta">
  <span class="tag tag-{memo.direction.lower()}">{memo.direction}</span>
  <span>Horizon: {memo.horizon}</span> · 
  <span>Conviction: <span class="conviction-{memo.conviction}">{memo.conviction}</span></span> · 
  <span>Asymmetry: <span class="asymmetry {asy_class}">{asy_str}</span></span> · 
  <span>Prob-Weighted Return: {returns['prob_weighted_return']:+.1f}%</span>
  <br>{memo.date} · {memo.analyst or 'NEXUS Research'}
</div>

<div class="variant-view">
  <strong>Variant View:</strong> {memo.variant_view}
</div>

<h2>Thesis</h2>
{thesis_html}

<h2>Business Snapshot</h2>
<p>{memo.business_snapshot}</p>

<h2>What's Priced In</h2>
<p>{memo.whats_priced_in}</p>

<h2>Scenario Analysis</h2>
<table>
  {scenario_rows}
</table>

<div class="section-label">Bull Case</div>
<p>{memo.bull_narrative}</p>

<div class="section-label">Base Case</div>
<p>{memo.base_narrative}</p>

<div class="section-label">Bear Case (Steelmanned)</div>
<p>{memo.bear_narrative}</p>

<h2>Catalysts</h2>
<table>
  <tr><th>Event</th><th>Date / Quarter</th><th>Expected Impact</th></tr>
  {cat_rows}
</table>

<h2>Risks & Tripwires</h2>
<table>
  <tr><th>Risk</th><th>Mitigant</th><th>Tripwire</th></tr>
  {risk_rows}
</table>

<h2>Position Management</h2>
<p>{memo.position_management}</p>

<h2>Monitoring KPIs</h2>
<ul class="kpi-list">
  {kpis_html}
</ul>

<div class="footer">
  NEXUS Research · Not financial advice · Data from free public sources
</div>

</body>
</html>"""
        return html

    def save_memo(self, memo: InvestmentMemo) -> str:
        """
        Render and save the memo to .heon/memos/.

        Returns the file path.
        """
        html = self.render_html(memo)
        filename = f"{memo.ticker}_{memo.direction}_{memo.date}.html"
        filepath = self.memo_dir / filename
        filepath.write_text(html, encoding="utf-8")
        return str(filepath)

    def generate_header_summary(self, memo: InvestmentMemo, filepath: str) -> str:
        """Generate the one-line chat header summary."""
        returns = self.compute_scenario_returns(memo)
        pwr = returns["prob_weighted_return"]
        asy = f"{returns['upside_downside_ratio']:.1f}x"

        return (
            f"{memo.ticker} · {memo.direction} · "
            f"Prob-Weighted Return {pwr:+.1f}% · "
            f"Asymmetry {asy} · "
            f"{memo.conviction.title()} Conviction\n\n"
            f"Memo saved to {filepath}\n"
            f"Open with: open {filepath}"
        )
