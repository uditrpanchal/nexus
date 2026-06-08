"""
Tool registry — mirrors dexter's src/tools/registry.ts

Defines all available tools with their schemas and implementations.
Each tool is a callable that the agent can invoke.

v2: Now includes run_full_analysis for programmatic pipeline execution.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Awaitable

from nexus.data_sources import FreeFinanceAPI
from nexus.orchestrator.execution_loop import AnalysisPipeline


# Type alias for tool functions
ToolFunc = Callable[..., Awaitable[Any]]


class ToolResult:
    """Wrapper for tool execution results."""
    def __init__(self, data: Any, source_url: str = ""):
        self.data = data
        self.source_url = source_url

    def to_dict(self) -> dict:
        return {"data": self.data, "source": self.source_url}


class ToolRegistry:
    """Registry of all available tools for the agent."""

    def __init__(self):
        self.api = FreeFinanceAPI()
        self._tools: dict[str, dict[str, Any]] = {}
        self._functions: dict[str, ToolFunc] = {}
        self._register_all()

    def _register_all(self):
        """Register all available tools."""
        self._register(
            name="get_price_snapshot",
            description="Get current stock price snapshot including price, market cap, volume, 52-week high/low. Use for current price queries.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol (e.g., 'AAPL' for Apple)"},
                },
                "required": ["ticker"],
            },
            func=self._get_price_snapshot,
        )

        self._register(
            name="get_historical_prices",
            description="Get historical price data for a stock over a date range.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "period": {"type": "string", "description": "Period: 1mo, 3mo, 6mo, 1y, 2y, 5y, max. Default: 1y", "default": "1y"},
                    "interval": {"type": "string", "description": "Interval: 1d, 1wk, 1mo. Default: 1d", "default": "1d"},
                },
                "required": ["ticker"],
            },
            func=self._get_historical_prices,
        )

        self._register(
            name="get_income_statements",
            description="Get company income statements (revenue, operating income, net income, EPS). Use for profitability analysis.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "period": {"type": "string", "description": "'annual' or 'quarterly'. Default: annual", "default": "annual"},
                    "limit": {"type": "integer", "description": "Number of periods to return. Default: 4", "default": 4},
                },
                "required": ["ticker"],
            },
            func=self._get_income_statements,
        )

        self._register(
            name="get_balance_sheets",
            description="Get company balance sheets (assets, liabilities, equity, cash, debt). Use for financial position analysis.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "period": {"type": "string", "description": "'annual' or 'quarterly'. Default: annual", "default": "annual"},
                    "limit": {"type": "integer", "description": "Number of periods. Default: 4", "default": 4},
                },
                "required": ["ticker"],
            },
            func=self._get_balance_sheets,
        )

        self._register(
            name="get_cash_flow_statements",
            description="Get company cash flow statements (operating CF, CapEx, free cash flow). Use for cash flow analysis.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "period": {"type": "string", "description": "'annual' or 'quarterly'. Default: annual", "default": "annual"},
                    "limit": {"type": "integer", "description": "Number of periods. Default: 4", "default": 4},
                },
                "required": ["ticker"],
            },
            func=self._get_cash_flow_statements,
        )

        self._register(
            name="get_key_metrics",
            description="Get comprehensive financial metrics snapshot: P/E, P/B, margins, ROE, ROA, debt/equity, growth rates, dividend yield, FCF. Use for quick company overview.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                },
                "required": ["ticker"],
            },
            func=self._get_key_metrics,
        )

        self._register(
            name="get_earnings",
            description="Get earnings history with EPS estimates vs actuals and surprises.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "limit": {"type": "integer", "description": "Number of earnings periods. Default: 8", "default": 8},
                },
                "required": ["ticker"],
            },
            func=self._get_earnings,
        )

        self._register(
            name="get_news",
            description="Get recent company news headlines. Pass ticker for company-specific news, or omit for broad market news.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol. Omit for market-wide news."},
                    "limit": {"type": "integer", "description": "Number of articles. Default: 10", "default": 10},
                },
                "required": [],
            },
            func=self._get_news,
        )

        self._register(
            name="get_company_info",
            description="Get comprehensive company information: name, sector, industry, description, employees, website, etc.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                },
                "required": ["ticker"],
            },
            func=self._get_company_info,
        )

        self._register(
            name="get_insider_trades",
            description="Get recent insider trading activity (purchases/sales by executives and directors).",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "limit": {"type": "integer", "description": "Number of trades. Default: 20", "default": 20},
                },
                "required": ["ticker"],
            },
            func=self._get_insider_trades,
        )

        self._register(
            name="get_institutional_holders",
            description="Get top institutional holders of a stock (who holds this stock).",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "limit": {"type": "integer", "description": "Number of holders. Default: 20", "default": 20},
                },
                "required": ["ticker"],
            },
            func=self._get_institutional_holders,
        )

        self._register(
            name="get_major_holders",
            description="Get major holders breakdown: insider %, institutions %, float held by institutions.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                },
                "required": ["ticker"],
            },
            func=self._get_major_holders,
        )

        self._register(
            name="get_analyst_data",
            description="Get analyst recommendations, price targets, and consensus.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                },
                "required": ["ticker"],
            },
            func=self._get_analyst_data,
        )

        self._register(
            name="get_sec_filings",
            description="Get SEC filing metadata (10-K, 10-Q, 8-K) for a company.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "filing_type": {"type": "string", "description": "Filing type: 10-K, 10-Q, 8-K. Default: 10-K", "default": "10-K"},
                    "limit": {"type": "integer", "description": "Number of filings. Default: 5", "default": 5},
                },
                "required": ["ticker"],
            },
            func=self._get_sec_filings,
        )

        self._register(
            name="get_etf_data",
            description="Get comprehensive ETF data: expense ratio, AUM, holdings, yield, etc.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "ETF ticker symbol (e.g., 'VOO', 'QQQ')"},
                },
                "required": ["ticker"],
            },
            func=self._get_etf_data,
        )

        self._register(
            name="screen_stocks",
            description="Screen S&P 500 stocks by financial criteria. Use for finding stocks matching investment criteria.",
            parameters={
                "type": "object",
                "properties": {
                    "criteria": {
                        "type": "object",
                        "description": "Screening criteria. Example: {'pe_ratio': {'operator': 'lt', 'value': 15}, 'revenue_growth': {'operator': 'gt', 'value': 0.1}}",
                    },
                    "limit": {"type": "integer", "description": "Max results. Default: 25", "default": 25},
                },
                "required": ["criteria"],
            },
            func=self._screen_stocks,
        )

        # --- NEW: Full analysis pipeline tool ---
        self._register(
            name="run_full_analysis",
            description="""Run the complete NEXUS programmatic analysis pipeline on a stock or ETF.
This executes all 6 phases automatically: Data Ingestion, Red Flag Scanner,
8 Pillar Evaluation (or 7 for ETFs), Weighted Scorecard, Validation Gate,
and Report Generation. All data is from FREE sources (Yahoo Finance, SEC EDGAR).
Use this as the PRIMARY tool for any stock/ETF analysis request.
Returns a complete markdown report with scores, red flags, and verdict.""",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock or ETF ticker symbol (e.g., 'AAPL', 'VOO', 'MSFT')"},
                    "asset_type": {"type": "string", "description": "'stock' or 'etf'. Auto-detected if omitted.", "default": "stock"},
                },
                "required": ["ticker"],
            },
            func=self._run_full_analysis,
        )

        # --- NEW: Web search tool (DuckDuckGo free + Tavily/SearXNG fallback) ---
        self._register(
            name="web_search",
            description="Search the web using free providers (DuckDuckGo primary, Tavily/SearXNG fallback). Returns up to 5 results with titles, URLs, and snippets. Use for supplementary research, news, and data not available via financial tools.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (default: 5)", "default": 5},
                },
                "required": ["query"],
            },
            func=self._web_search,
        )

        # --- NEW: SEC Filings Reader ---
        self._register(
            name="read_filings",
            description="Extract structural sections from SEC filings: Item 1 (Business Overview), Item 1A (Risk Factors), Item 7/MD&A. Supports 10-K, 10-Q, 8-K. Provide filing text content to parse.",
            parameters={
                "type": "object",
                "properties": {
                    "filing_text": {"type": "string", "description": "Raw SEC filing HTML/text content"},
                    "filing_type": {"type": "string", "description": "Filing type: 10-K, 10-Q, or 8-K. Default: 10-K", "default": "10-K"},
                },
                "required": ["filing_text"],
            },
            func=self._read_filings,
        )

    def _register(self, name: str, description: str, parameters: dict, func: ToolFunc):
        """Register a tool with its schema and implementation."""
        self._tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        self._functions[name] = func

    def get_schemas(self) -> list[dict]:
        """Get all tool schemas for LLM binding."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolFunc | None:
        """Get tool function by name."""
        return self._functions.get(name)

    def get_compact_descriptions(self) -> str:
        """Get compact tool descriptions for system prompt."""
        lines = []
        for name, schema in self._tools.items():
            desc = schema["function"]["description"]
            lines.append(f"- **{name}**: {desc}")
        return "\n".join(lines)

    # =========================================================================
    # TOOL IMPLEMENTATIONS
    # =========================================================================

    async def _get_price_snapshot(self, ticker: str) -> dict:
        return await asyncio.to_thread(self.api.get_price_snapshot, ticker)

    async def _get_historical_prices(self, ticker: str, period: str = "1y", interval: str = "1d") -> list:
        return await asyncio.to_thread(self.api.get_historical_prices, ticker, period, interval)

    async def _get_income_statements(self, ticker: str, period: str = "annual", limit: int = 4) -> list:
        return await asyncio.to_thread(self.api.get_income_statements, ticker, period, limit)

    async def _get_balance_sheets(self, ticker: str, period: str = "annual", limit: int = 4) -> list:
        return await asyncio.to_thread(self.api.get_balance_sheets, ticker, period, limit)

    async def _get_cash_flow_statements(self, ticker: str, period: str = "annual", limit: int = 4) -> list:
        return await asyncio.to_thread(self.api.get_cash_flow_statements, ticker, period, limit)

    async def _get_key_metrics(self, ticker: str) -> dict:
        return await asyncio.to_thread(self.api.get_key_metrics, ticker)

    async def _get_earnings(self, ticker: str, limit: int = 8) -> list:
        return await asyncio.to_thread(self.api.get_earnings, ticker, limit)

    async def _get_news(self, ticker: str = None, limit: int = 10) -> list:
        return await asyncio.to_thread(self.api.get_news, ticker, limit)

    async def _get_company_info(self, ticker: str) -> dict:
        return await asyncio.to_thread(self.api.get_company_info, ticker)

    async def _get_insider_trades(self, ticker: str, limit: int = 20) -> list:
        return await asyncio.to_thread(self.api.get_insider_trades, ticker, limit)

    async def _get_institutional_holders(self, ticker: str, limit: int = 20) -> list:
        return await asyncio.to_thread(self.api.get_institutional_holders, ticker, limit)

    async def _get_major_holders(self, ticker: str) -> dict:
        return await asyncio.to_thread(self.api.get_major_holders, ticker)

    async def _get_analyst_data(self, ticker: str) -> dict:
        return await asyncio.to_thread(self.api.get_analyst_data, ticker)

    async def _get_sec_filings(self, ticker: str, filing_type: str = "10-K", limit: int = 5) -> list:
        return await asyncio.to_thread(self.api.get_sec_filings_list, ticker, filing_type, limit)

    async def _get_etf_data(self, ticker: str) -> dict:
        return await asyncio.to_thread(self.api.get_etf_data, ticker)

    async def _screen_stocks(self, criteria: dict, limit: int = 25) -> list:
        return await asyncio.to_thread(self.api.screen_stocks, criteria, limit)

    async def _run_full_analysis(self, ticker: str, asset_type: str = "stock") -> str:
        """
        Run the complete programmatic analysis pipeline.
        Returns the full markdown report as a string.
        """
        ticker = ticker.upper()

        # Auto-detect ETF if not explicitly set
        if asset_type == "stock":
            # Quick check: if ticker starts with common ETF patterns or is known ETF
            etf_indicators = ["VOO", "QQQ", "SPY", "IVV", "VTI", "IWM", "DIA",
                            "GLD", "TLT", "LQD", "HYG", "AGG", "BND", "VNQ",
                            "ARKK", "ICLN", "SOXX", "SMH", "XLF", "XLE", "XLK",
                            "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLC", "XLRE"]
            if ticker in etf_indicators:
                asset_type = "etf"

        pipeline = AnalysisPipeline()
        ctx = await pipeline.run(ticker, asset_type)
        report = pipeline.generate_report()

        # Return summary + report
        summary = pipeline.generate_summary()
        return f"{summary}\n\n---\n\n{report}"

    async def _web_search(self, query: str, max_results: int = 5) -> list:
        """Search the web using the free fallback router."""
        try:
            from .web_search import search_web
            return await search_web(query, max_results)
        except ImportError:
            from nexus.tools.web_search import search_web
            return await search_web(query, max_results)

    async def _read_filings(self, filing_text: str, filing_type: str = "10-K") -> dict:
        """Parse SEC filing sections."""
        from .read_filings import parse_filing
        return parse_filing(filing_text, filing_type)
