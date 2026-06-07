"""
NEXUS — Autonomous Financial Research Agent
Built with wisdom from:
  - Dexter (virattt/dexter): Agent architecture, tool design, multi-provider LLM
  - V9 Framework (udit): Value investing pillars, red flag scanner, legal hardening

NO paid API keys required. All data from free sources:
  - yfinance: Real-time prices, financials, ratios, earnings, news
  - SEC EDGAR: 10-K, 10-Q, 8-K filings (via direct HTTP)
  - Web scraping: Supplementary data via httpx + BeautifulSoup
"""

__version__ = "1.0.0"
