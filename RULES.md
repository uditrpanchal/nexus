# RULES.md — NEXUS V10 Institutional Framework

Immutable research constraints for NEXUS operations. Based on the V10 Universal Investment Analysis Framework.

---

## THE 6 LAWS — BREAKING ANY ONE IS A PROCESS FAILURE

**LAW 1 — FETCH BEFORE YOU WRITE.** Do not write a single word of analysis until ALL required data is fetched via live search. Use only free, unpaywalled sources (yfinance, SEC EDGAR, DuckDuckGo). Avoid all paywalled sources.

**LAW 2 — ALL PILLARS ARE MANDATORY.** Stocks require exactly 8 sequential pillars. ETFs require exactly 7 sequential pillars. Missing even ONE pillar = incomplete output.

**LAW 3 — EVERY SECTION IN THE OUTPUT FORMAT IS REQUIRED.** Each must appear explicitly. No combining headers, summarizing, or skipping.

**LAW 4 — STRICT MATHEMATICAL COMPUTE.** All calculations must be shown step-by-step in code blocks. No rounding mid-calculation. No LaTeX inside code blocks.

**LAW 5 — SEPARATION OF PILLARS, SEQUENTIAL NUMBERING, AND FLOOR LENGTHS.** Every pillar begins with its absolute sequential index block.

**LAW 6 — LEGAL & ANTITRUST RISK FRESHNESS CHECK.** Verify active court status or regulatory milestones dated within the last 90 days. Stale legal summaries = system-wide audit failure.

---

## 4 Red Flag Scanners (V10 — run on every stock analysis)

| # | Flag | Trigger Condition | Penalty |
|---|------|-------------------|---------|
| RF1 | Declining Revenue/Earnings | 3+ consecutive quarters dual-decline OR 2+ earnings misses | Counted in penalty |
| RF2 | High Debt Levels | D/E > 2.0 AND ICR < 1.5 | Counted in penalty |
| RF3 | Poor Cash Flow Quality | OCF negative 2+ quarters OR Adjusted FCF (OCF-CapEx-SBC) negative TTM | Counted in penalty |
| RF4 | Capital Destruction (NEW) | ROIC < WACC (negative Economic Spread) | Counted in penalty |

**Penalty Schedule:**
- 0 flags: No deduction
- 1 flag: No penalty (note in verdict)
- 2 flags: -1.0 from final weighted score + MULTI-RED-FLAG WARNING + downgrade rating
- 3 flags: -2.0 from final weighted score + downgrade 2 tiers
- 4 flags: **AUTOMATIC AVOID** — overrides all pillar scores

---

## 8 Stock Pillars (V10 Weights)

| # | Pillar | Weight | Key Metrics |
|---|--------|--------|-------------|
| 1 | Business Quality | 20% | Moat type, competitive position, revenue consistency |
| 2 | Management Integrity | 15% | CEO tenure, insider ownership, capital allocation track record |
| 3 | Financial Strength | 20% | SBC-adjusted FCF, Economic Spread (ROIC-WACC), D/E, SBC drag % |
| 4 | Valuation & Margin of Safety | 20% | P/E, P/FCF, EV/EBITDA, P/B vs historical/peers, MoS calculation |
| 5 | Circle of Competence | 10% | Business understandability, IN/EDGE/OUTSIDE declaration |
| 6 | Long-Term Outlook | 10% | Secular tailwinds, 10-year outlook, market share trend |
| 7 | Risk Assessment | 5% | Legal/regulatory freshness, off-balance sheet commitments ratio |
| 8 | Temperament Test | 0% | Qualitative gate — FAIL overrides to AVOID regardless of score |

---

## 7 ETF Pillars (V10 with Structural Risk)

| # | Pillar | Weight | Key Checks |
|---|--------|--------|------------|
| 1 | Index Quality & Construction | 20% | Exact index, selection+weighting method, rebalance cost |
| 2 | Cost Efficiency & Frictional Drag | 25% | Expense ratio, bid-ask spread, total cost of ownership vs peers |
| 3 | Tracking Quality & Counterparty Risk | 15% | Tracking difference, replication method, synthetic swap check |
| 4 | Liquidity & Fund Size | 15% | AUM, volume, issuer, closure risk |
| 5 | Tax Efficiency | 10% | 5-year cap gains history, optimal tax wrapper recommendation |
| 6 | Diversification & Exposure Quality | 10% | Holdings count, top-10 concentration, sector/geo allocation |
| 7 | Strategy Fit & Portfolio Role | 5% | ETF type classification, suitability assessment |

---

## Verdict Thresholds

- **BUY:** >= 70% AND 0 red flags AND Temperament PASS
- **WATCH:** 50-69% OR 1 red flag (BUY score + 1 flag = WATCH)
- **AVOID:** < 50% OR 2+ red flags OR 4-flag override OR Temperament FAIL

---

## Data Source Protocol

**ABSOLUTE REQUIREMENT:** 100% free, zero paywalled APIs.

| Source | Data | Cost |
|--------|------|------|
| Yahoo Finance (yfinance) | Prices, financials, ratios, earnings, news | Free |
| SEC EDGAR | 10-K, 10-Q, 8-K filings, CIK lookup | Free |
| DuckDuckGo | Web search | Free |
| Tavily | Web search (1000 req/month) | Free tier |
| SearXNG | Web search (local) | Free |

---

## Institutional Adjustment Rules (V10)

1. **SBC Cash Drag:** If SBC_Cash_Drag_Percentage > 15% or Economic Spread (ROIC-WACC) < 0, Pillar 3 (Financial Strength) is capped at 6/10.
2. **Off-Balance Sheet Commitments:** If Commitment Ratio (purchase obligations / cash) > 50%, Pillar 7 (Risk Assessment) is capped at 5/10.
3. **ETF Counterparty Risk:** If synthetic Total Return Swaps used with unrated counterparties OR tracking error > 1% above expense ratio, cap Pillar 3 at 4/10.
4. **Temperament Gate:** If 3+ negative indicators, FAIL overrides to AVOID.
5. **Legal Freshness:** Legal/regulatory status must be verified within last 90 days.

---

## Math & Calculation Rules

1. **Fetch before you write.** Never hallucinate numbers.
2. **All pillars are mandatory.** No shortcuts, no skipped sections.
3. **Math must be shown step-by-step.** No rounding mid-calculation.
4. **Red flags must be checked before forming a verdict.**
5. **Legal freshness matters** — stale legal summaries are audit failures.
6. **DCF growth capped at 15%.**
7. **Terminal value capped at 50-80% of EV.**
8. **EV must resolve within 30% of reported market metrics.**

---

## Output Verification Rules

The validation gate must block report creation if:
- Any validation table contains missing entries
- Any math log contains skipped or incomplete steps
- Any metric has a null/None value where data should exist
- 100% completion required for PASS