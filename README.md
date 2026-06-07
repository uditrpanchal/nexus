#heon

## Overview

heon is an autonomous financial research agent — inspired by [dexter](https://github.com/virattt/dexter) and built for deep, systematic stock analysis using **100% free data sources**. No Financial Datasets API key required.

**The name:**heon (헌) — Korean for "investigation / examination." A researcher who digs until they find the truth.

## Features

- **Live market data** via Yahoo Finance (yfinance)
- **Financial statements** via Yahoo Finance + SEC EDGAR direct filings
- **Stock screening** using yfinance screener criteria
- **DCF valuation skill** with automatic data gathering and sensitivity analysis
- **SEC filing reader** — 10-K, 10-Q, 8-K item extraction
- **News sentiment** via web search
- **Value investing framework** based on Ronald Chan + Richard A. Ferri methodologies
- **Red Flag Scanner** — automatic risk detection (declining revenue, high debt, poor cash flow)
- **WhatsApp gateway** support (optional)

## Prerequisites

- Python 3.11+
- `uv` package manager (recommended) or `pip`
- OpenAI / Anthropic / Google / Ollama API key (for the LLM agent)

## Installation

```bash
git clone https://github.com/yourusername/heon.git
cd heon
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp env.example .env
# Edit .env and add your LLM API key
```

## Usage

```bash
# Interactive mode
uv run heon

# Direct query
uv run heon "Analyze MSFT intrinsic value"

# With WhatsApp gateway
uv run heon --gateway whatsapp
```

## Environment Variables

```bash
# LLM (at least one required)
OPENAI_API_KEY=your-key
ANTHROPATHIC_API_KEY=your-key
GOOGLE_API_KEY=your-key
OPENROUTER_API_KEY=your-key

# Optional: web search (free tier available)
SERPER_API_KEY=your-key
```
