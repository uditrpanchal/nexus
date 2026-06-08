# nexus

## Overview

**NEXUS** — an autonomous financial research agent that runs entirely on free data sources. It programmatically executes the **V10 Universal Investment Analysis Framework**: a complete analytical lifecycle covering red flag detection, pillar evaluation, weighted scorecard computation, off-balance sheet analysis, legal freshness checks, and output validation — using only zero-cost public data.

Built with architectural patterns from [dexter](https://github.com/virattt/dexter), NEXUS delivers institutional-grade stock and ETF analysis with no paid API keys, no paywalls, and full arithmetic transparency.

**No API keys required. No premium data subscriptions. 100% free data sources.**

## Architecture

nexus is organized as a decoupled, modular pipeline where each phase operates independently with clear input/output contracts:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NEXUS ANALYSIS PIPELINE                        │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────┐    ┌──────────────────┐    ┌───────────────────────┐
│  DATA LAYER  │───▶│  RED FLAG SCAN   │───▶│   PILLAR EVALUATION   │
│              │    │                  │    │                       │
│  yfinance    │    │  RF1: Rev/NI     │    │  8 Stock Pillars      │
│  SEC EDGAR   │    │  RF2: D/E + ICR  │    │  7 ETF Pillars        │
│  WACC Table  │    │  RF3: SBC-adj FCF│    │                       │
│  Web Scrape  │    │  RF4: ROIC<WACC  │    │                       │
└──────────────┘    └──────────────────┘    └───────────┬───────────┘
                                                        │
                                                        ▼
┌──────────────┐    ┌──────────────────┐    ┌───────────────────────┐
│   REPORT     │◀───│   VALIDATION     │◀───│      SCORECARD         │
│              │    │      GATE        │    │                       │
│  Markdown    │    │                  │    │  Weighted computation  │
│  Tables      │    │  100% coverage   │    │  Math tracking        │
│  Verdict     │    │  Consistency     │    │  BUY/WATCH/AVOID      │
└──────────────┘    └──────────────────┘    └───────────────────────┘
```

### Platform Topology

```mermaid
graph TD
    CLI[CLI / User Input] --> AGENT[Agent Orchestration Layer]
    AGENT --> TOOLS[Tool Registry]
    
    TOOLS --> RUN_ANALYSIS[run_full_analysis Tool]
    TOOLS --> PRICE[get_price_snapshot]
    TOOLS --> METRICS[get_key_metrics]
    TOOLS --> STATEMENTS[get_income/balance/cashflow]
    
    RUN_ANALYSIS --> PIPELINE[AnalysisPipeline]
    
    PIPELINE --> DATA[Data Ingestion Phase]
    DATA --> YF[yfinance - Yahoo Finance]
    DATA --> SEC[SEC EDGAR Direct]
    DATA --> WEB[Web Scraping]
    
    DATA --> RF[Red Flag Scanner]
    RF --> RF1[RF1: Revenue & NI Decline]
    RF --> RF2[RF2: Debt/Equity + Interest Coverage]
    RF --> RF3[RF3: SBC-Adjusted FCF]
    RF --> RF4[RF4: ROIC < WACC]
    
    RF --> PILLARS[Pillar Evaluation Engine]
    PILLARS --> STOCK[8 Stock Pillars]
    PILLARS --> ETF[7 ETF Pillars]
    
    STOCK --> SC[Scorecard Module]
    ETF --> SC
    SC --> VG[Validation Gate]
    VG --> REPORT[Report Generator]
    REPORT --> OUTPUT[Markdown Output + Verdict]
    
    AGENT --> LLM[Multi-Provider LLM]
    LLM --> OPENAI[OpenAI]
    LLM --> ANTHROPIC[Anthropic]
    LLM --> OPENROUTER[OpenRouter]
    LLM --> OLLAMA[Ollama Local]
```

### Module Directory Structure

```
src/nexus/
├── __init__.py              # Package metadata
├── __main__.py              # Entry point
├── cli.py                   # Rich terminal interface (Click + Rich)
├── agent.py                 # Agent core — iterative tool-calling loop
├── llm.py                   # Multi-provider LLM abstraction
├── data_sources.py          # Free data layer (yfinance, SEC, web)
├── cache.py                 # TTL file-based cache
├── formatters.py            # Number formatting utilities
│
├── engine/                  # ★ Core Analysis Engine (NEW)
│   ├── __init__.py
│   ├── red_flag_scanner.py  # Automated 4-flag V10 risk detection
│   ├── pillar_evaluator.py  # 8 Stock + 7 ETF pillar evaluation
│   ├── scorecard.py         # Weighted scoring tables + math tracking
│   └── validation_gate.py   # Pre-report output verification
│
├── orchestrator/            # ★ Multi-Agent Pipeline (NEW)
│   ├── __init__.py
│   └── execution_loop.py    # Complete 6-phase analysis pipeline
│
└── tools/
    ├── __init__.py           # Tool registry with run_full_analysis
    └── formatting.py         # Display formatting utilities

tests/
└── test_engine.py            # Comprehensive test suite (29 tests)
```

## Core Components

### 1. Free Financial Data Layer

All data comes from zero-cost sources — no premium or paywalled API integrations:

| Source | Data | Method |
|--------|------|--------|
| **Yahoo Finance** (yfinance) | Prices, financials, ratios, earnings, news, insider trades, analyst targets, ETF bid/ask | Python library |
| **SEC EDGAR** | 10-K, 10-Q, 8-K filings, CIK lookup, off-balance sheet footnotes, legal proceedings | Direct HTTP + iXBRL parsing |
| **Sector WACC Table** | WACC estimation by sector with company-specific adjustments | Local `.heon/sector-wacc.md` lookup |
| **DuckDuckGo** (keyless) | Web search for supplementary research | Free API |
| **Web Scraping** | Supplementary data (FinanceCharts, Macrotrends) | httpx + BeautifulSoup |

Data is cached with TTL-based file storage to minimize API calls.

### 2. Automated Red Flag Scanner (V10)

Four sequential checks run on every stock analysis — including **Capital Destruction (RF4)** and **SBC-adjusted FCF (RF3)**:

| Flag | Description | Threshold | Penalty |
|------|-------------|-----------|---------|
| **RF1** | Revenue & Net Income Decline | 3+ consecutive dual-declines **OR** 2+ earnings misses | Counted |
| **RF2** | Balance Sheet Stress | D/E > 2.0 **AND** ICR < 1.5 simultaneously | Counted |
| **RF3** | Poor Cash Flow Quality | OCF negative 2+ quarters **OR** Adjusted FCF (OCF − CapEx − SBC) negative TTM | Counted |
| **RF4** | Capital Destruction (NEW) | ROIC < WACC — negative Economic Spread | Counted |

**V10 Penalty Schedule:**
- 0 flags: No deduction
- 1 flag: **No penalty** (note in verdict)
- 2 flags: **−1.0** from final score + downgrade rating tier
- 3 flags: **−2.0** from final score + downgrade 2 tiers
- 4 flags: **Automatic AVOID** — overrides all pillar scores

### 3. Pillar Evaluation Engine

#### 8 Stock Pillars (V10 Weights)

| # | Pillar | Weight | Key Metrics |
|---|--------|--------|-------------|
| 1 | Business Quality | **20%** | Moat type, competitive position, gross/operating margins, revenue consistency |
| 2 | Management Integrity | 15% | Insider ownership, capital allocation track record, insider trading patterns |
| 3 | Financial Strength | **20%** | SBC-adjusted FCF, **Economic Spread (ROIC − WACC)**, D/E, SBC drag % |
| 4 | Valuation & MoS | **20%** | P/E, P/FCF, EV/EBITDA, P/B vs historical/peers, **Margin of Safety calculation** |
| 5 | Circle of Competence | 10% | Business understandability, **IN / EDGE / OUTSIDE declaration** |
| 6 | Long-Term Outlook | 10% | Revenue/earnings growth, secular tailwinds, **10-year projection** |
| 7 | Risk Assessment | **5%** | Beta, **off-balance sheet commitment ratio**, drawdown, **legal/regulatory freshness** |
| 8 | Temperament Test | **0%** | **Qualitative gate** — 5-question proxy assessment; **FAIL overrides to AVOID** |

#### 7 ETF Pillars (V10)

| # | Pillar | Weight | Key Metrics |
|---|--------|--------|-------------|
| 1 | Index Quality & Construction | **20%** | Exact index, selection/weighting method, rebalance cost |
| 2 | Cost Efficiency & Frictional Drag | **25%** | Expense ratio, **bid-ask spread (bps)**, total cost of ownership vs peers |
| 3 | Tracking Quality & Counterparty Risk | **15%** | Tracking difference, replication method, **synthetic swap check** |
| 4 | Liquidity & Fund Size | **15%** | AUM, average volume, closure risk assessment |
| 5 | Tax Efficiency | **10%** | 5-year cap gains history, **optimal tax wrapper recommendation** |
| 6 | Diversification & Exposure Quality | **10%** | Holdings count, top-10 concentration, sector/geo allocation |
| 7 | Strategy Fit & Portfolio Role | **5%** | ETF type classification, suitability assessment |

### 4. Scorecard & Arithmetic Module

Every pillar score has a **math tracking string** that documents the exact computation path:

```
PILLAR_SCORE = SUM(P1=0.675, P2=0.600, P3=0.525, ...) = 3.450 / 5.000 = 69.00%
RED_FLAG_DEDUCTION: 0 flag(s) → +0.0 points
FINAL_SCORE = 69.00% + (0.0 * 10) = 69.00%
VERDICT: WATCH | RATING: ★★★ | SCORE: 69.00%
```

**V10 Verdict thresholds:**
- **BUY:** ≥ 70% **and** 0 red flags **and** Temperament PASS
- **WATCH:** 50–69% **or** 1 red flag (BUY score + 1 flag → WATCH)
- **AVOID:** < 50% **or** 2+ red flags **or** 4-flag override **or** Temperament FAIL

### 5. Validation Gate

Before any report is generated, the validation gate auto-verifies:
- All pillars present with valid scores (1.0–5.0)
- All **4** red flags checked with valid status
- Weighted score arithmetic is internally consistent
- Scorecard math tracking strings present
- No null/None values in critical paths
- 100% completion required for PASS

### 6. Multi-Agent Execution Loop

Inspired by dexter's agent.ts architecture:
- **6-phase pipeline:** Data Ingestion → Red Flag Scan → Pillar Evaluation → Scorecard → Validation → Report
- **Concurrent data fetching:** All independent data calls fire in parallel via asyncio
- **Micro-compaction support:** Context management for long-running agent sessions
- **Multi-provider LLM:** OpenAI, Anthropic, OpenRouter, Ollama (local)
- **Typed event system:** Real-time progress events for CLI streaming

## Prerequisites

- Python 3.11+
- `uv` package manager (recommended) or `pip`
- LLM API key for the agent layer (at least one of):
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `OPENROUTER_API_KEY`
  - Or use local Ollama (no key needed)

## Installation

```bash
git clone https://github.com/uditrpanchal/nexus.git
cd nexus
chmod +x setup.sh && ./setup.sh
# Or manually:
uv sync
```

## Usage

### Command Line

```bash
# Interactive mode
uv run nexus

# Direct analysis
uv run nexus "Analyze AAPL"

# ETF analysis
uv run nexus "Analyze VOO"

# With specific model/provider
uv run nexus --model openrouter/anthropic/claude-sonnet-4 --provider openrouter "Analyze MSFT"
```

### Programmatic API

```python
import asyncio
from nexus.orchestrator.execution_loop import AnalysisPipeline

async def analyze(ticker):
    pipeline = AnalysisPipeline()
    ctx = await pipeline.run(ticker, "stock")
    report = pipeline.generate_report()
    print(report)
    print(pipeline.generate_summary())

asyncio.run(analyze("AAPL"))
```

## Configuration

```bash
# Required: at least one LLM API key
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export OPENROUTER_API_KEY=sk-or-...
# Or use local Ollama
export NEXUS_PROVIDER=ollama
export NEXUS_MODEL=llama3.1

# Optional
export NEXUS_MAX_ITERATIONS=20
```

## Running Tests

```bash
uv run python -m pytest tests/ -v

# With coverage (if installed)
uv run python -m pytest tests/ -v --cov=nexus.engine --cov=nexus.orchestrator
```

## Design Philosophy

1. **Zero-cost data:** No premium API keys. yfinance + SEC EDGAR + sector WACC table + web scraping.
2. **Deterministic engine:** The analysis pipeline is fully programmatic — no LLM calls in the engine layer. The LLM agent sits above for user interaction.
3. **V10 institutional adjustments:** SBC-adjusted FCF, true ROIC calculation, Economic Spread (ROIC − WACC), off-balance sheet commitment ratio, legal/regulatory freshness checks.
4. **Math transparency:** Every score computation has a verifiable arithmetic tracking string.
5. **Gate before output:** The validation gate must pass at 100% before any report is generated.
6. **Dexter-inspired architecture:** Concurrent tool execution, micro-compaction, scratchpad tracking, multi-provider LLM support.
7. **Decoupled modules:** Each phase (data, flags, pillars, scorecard, validation) operates independently with clear contracts.

## License

MIT

---

*nexus is not financial advice. All data comes from free public sources. Always do your own research before making investment decisions.*
