# RULES.md — NEXUS Research Constraints

These are the immutable research constraints that govern how NEXUS operates.

---

## V9 Mandatory Framework Gates (PROGRAMMATIC ENFORCEMENT)

### 3 Red Flag Scanners (run on every stock analysis)

| # | Flag | Threshold | Action |
|---|------|-----------|--------|
| RF1 | Revenue & Net Income Decline | Both declining in 2+ of last 3 QoQ | −0.5 score deduction |
| RF2 | Balance Sheet Stress | D/E > 2.0 **AND** ICR < 1.5 | −0.5 score deduction |
| RF3 | Negative Free Cash Flow | TTM FCF (OCF − CapEx) < 0 | −0.5 score deduction |

**Deduction schedule:**
- 0 flags: No deduction
- 1 flag: −0.5 from final score
- 2 flags: −1.0 from final score
- 3 flags: **AUTOMATIC AVOID** — overrides all pillar scores

### 8 Stock Pillars (mandatory evaluation)

| # | Pillar | Weight | Key Metrics |
|---|--------|--------|-------------|
| 1 | Business Quality | 15% | Gross margin, operating margin, ROE, revenue consistency |
| 2 | Management | 15% | Insider ownership, institutional conviction, capital allocation |
| 3 | Financial Strength | 15% | D/E, current ratio, FCF reconciliation (manual OCF−CapEx) |
| 4 | Valuation | 15% | P/E, PEG, P/B, analyst target upside |
| 5 | Circle of Competence | 10% | Sector clarity, business model simplicity |
| 6 | Long-Term Outlook | 10% | Revenue/earnings growth, multi-year trend |
| 7 | Risk Assessment | 10% | Beta, drawdown from 52w high, market cap size |
| 8 | Temperament Test | 10% | 5-question behavioral assessment via objective proxies |

### 7 ETF Pillars (mandatory evaluation)

| # | Pillar | Weight | Key Metrics |
|---|--------|--------|-------------|
| 1 | Expense Ratio | 20% | Annual expense ratio vs category |
| 2 | Tracking Error | 15% | Beta deviation from benchmark |
| 3 | Liquidity | 15% | AUM, average volume |
| 4 | Holdings Quality | 15% | Diversification, top-10 concentration |
| 5 | Tax Efficiency | 15% | Category-based turnover assessment |
| 6 | Methodology | 10% | Index construction transparency |
| 7 | Fit Assessment | 10% | AUM stability, category alignment |

### Verdict Thresholds

- **BUY:** >= 70% AND 0 red flags
- **WATCH:** 50-69% OR 1 red flag triggered (BUY score + 1 flag -> WATCH)
- **AVOID:** < 50% OR 2+ red flags OR 3-flag override

---

## Data Source Protocol

**ABSOLUTE REQUIREMENT:** 100% free, zero paywalled APIs.

| Source | Data | Cost |
|--------|------|------|
| Yahoo Finance (yfinance) | Prices, financials, ratios, earnings, news | Free |
| SEC EDGAR | 10-K, 10-Q, 8-K filings, CIK lookup | Free |
| DuckDuckGo | Web search fallback | Free |
| Tavily | Web search (secondary, 1000 req/month) | Free tier |
| SearXNG | Web search (local fallback) | Free |

**NEVER:** Use paid API endpoints, premium data subscriptions, or paywalled features.

---

## Math & Calculation Rules

1. **Fetch before you write.** Never hallucinate numbers. Every claim must be backed by live data.
2. **All pillars are mandatory.** No shortcuts, no skipped sections.
3. **Math must be shown step-by-step.** No rounding mid-calculation.
4. **Red flags must be checked before forming a verdict.**
5. **Legal and regulatory freshness matters** — stale legal summaries are audit failures.
6. **DCF growth capped at 15%** — sustained higher growth is statistically rare.
7. **Terminal value capped at 50-80% of EV** for mature companies.
8. **EV must resolve within 30% of reported market metrics.**

---

## Output Verification Rules

The validation gate must block report creation if:
- Any validation table contains missing entries
- Any math log contains skipped or incomplete steps
- Any metric has a null/None value where data should exist
- 100% completion is required for PASS

---

## Investment Memo Quality Standards

1. **Variant view is actually variant** — not consensus dressed up
2. **Every thesis bullet is falsifiable** — has a "wrong if" clause with specific observables
3. **Numbers behind every adjective** — no "strong growth" without bps/%
4. **Bear case is steelmanned** — written as if you believe it
5. **Asymmetry >= 2x** — flag in header if not
6. **Probability weights sum to 100%**
7. **Tripwires are observable** — not vague macro statements

---

## Free-Source Protocol

- **No API keys required** for core data pipeline
- yfinance provides fundamentals, balance sheets, cash flow data
- SEC EDGAR provides filing content
- DuckDuckGo provides web search (keyless)
- Local embeddings via sentence-transformers (no API key needed)
- All dependencies must be open-source packages
