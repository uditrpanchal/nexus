"""
Free data source layer — replaces Financial Datasets API entirely.

Data sources (ALL FREE, NO API KEYS):
  1. yfinance (Yahoo Finance): Prices, financials, ratios, earnings, news, insider trades
  2. SEC EDGAR direct HTTP: 10-K, 10-Q, 8-K filing content
  3. Web scraping: Supplementary data from FinanceCharts, Macrotrends, StockAnalysis

This module provides a unified interface that mirrors the dexter finance tool API
but uses only free, unpaywalled sources.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

from .cache import Cache
from .formatters import fmt_num, fmt_pct, fmt_price, fmt_date


class FreeFinanceAPI:
    """Unified free financial data API — replaces Financial Datasets API."""

    def __init__(self, cache_ttl: int = 300):
        self.cache = Cache(default_ttl=cache_ttl)
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "HeonAgent/1.0 (Financial Research)"
            }
        )
        self._sync_client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "HeonAgent/1.0 (Financial Research)"
            }
        )

    # =========================================================================
    # PRICE DATA
    # =========================================================================

    def get_price_snapshot(self, ticker: str) -> dict[str, Any]:
        """Get current price snapshot — replaces /prices/snapshot/"""
        cache_key = f"price_snapshot:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            info = t.info
            hist = t.history(period="5d")

            if hist.empty and not info.get("regularMarketPrice") and not info.get("currentPrice"):
                return {"error": f"No price data found for {ticker}"}

            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            if current_price is None and not hist.empty:
                current_price = float(hist["Close"].iloc[-1])

            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            if prev_close is None and len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])

            high_52w = info.get("fiftyTwoWeekHigh")
            low_52w = info.get("fiftyTwoWeekLow")
            if not hist.empty:
                high_52w = high_52w or float(hist["High"].max())
                low_52w = low_52w or float(hist["Low"].min())

            result = {
                "ticker": ticker.upper(),
                "price": current_price,
                "open": info.get("open") or info.get("regularMarketOpen"),
                "high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                "low": info.get("dayLow") or info.get("regularMarketDayLow"),
                "prev_close": prev_close,
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "avg_volume": info.get("averageVolume"),
                "market_cap": info.get("marketCap"),
                "52w_high": high_52w,
                "52w_low": low_52w,
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange"),
                "source": "Yahoo Finance (yfinance)",
            }
            self.cache.set(cache_key, result, ttl=60)  # 1 min for prices
            return result
        except Exception as e:
            return {"error": f"Failed to fetch price for {ticker}: {str(e)}"}

    def get_historical_prices(
        self, ticker: str, period: str = "1y", interval: str = "1d"
    ) -> list[dict[str, Any]]:
        """Get historical prices — replaces /prices/"""
        cache_key = f"prices:{ticker.upper()}:{period}:{interval}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, interval=interval)

            if hist.empty:
                return []

            result = []
            for date, row in hist.iterrows():
                result.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 2) if not (row["Open"] != row["Open"]) else None,
                    "high": round(float(row["High"]), 2) if not (row["High"] != row["High"]) else None,
                    "low": round(float(row["Low"]), 2) if not (row["Low"] != row["Low"]) else None,
                    "close": round(float(row["Close"]), 2) if not (row["Close"] != row["Close"]) else None,
                    "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                })

            self.cache.set(cache_key, result, ttl=3600)  # 1 hour for historical
            return result
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # FINANCIAL STATEMENTS
    # =========================================================================

    def get_income_statements(
        self, ticker: str, period: str = "annual", limit: int = 4
    ) -> list[dict[str, Any]]:
        """Get income statements — replaces /financials/income-statements/"""
        cache_key = f"income:{ticker.upper()}:{period}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            if period == "quarterly":
                statements = t.quarterly_income_stmt
            else:
                statements = t.income_stmt

            if statements is None or statements.empty:
                return []

            result = []
            cols = statements.columns[:limit]
            for col in cols:
                row = statements[col]
                period_date = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                result.append({
                    "report_period": period_date,
                    "period": "Q" + str(col.quarter) + " " + str(col.year) if hasattr(col, "quarter") and period == "quarterly" else str(col.year if hasattr(col, "year") else col_date_to_year(col)),
                    "revenue": self._safe_float(row.get("Total Revenue")),
                    "operating_income": self._safe_float(row.get("Operating Income")),
                    "net_income": self._safe_float(row.get("Net Income")),
                    "gross_profit": self._safe_float(row.get("Gross Profit")),
                    "ebitda": self._safe_float(row.get("EBITDA")),
                    "ebit": self._safe_float(row.get("EBIT")),
                    "operating_expense": self._safe_float(row.get("Operating Expense")),
                    "pretax_income": self._safe_float(row.get("Pretax Income")),
                    "tax_provision": self._safe_float(row.get("Tax Provision")),
                    "basic_eps": self._safe_float(row.get("Basic EPS")),
                    "diluted_eps": self._safe_float(row.get("Diluted EPS")),
                    "research_development": self._safe_float(row.get("Research And Development")),
                    "selling_general_admin": self._safe_float(row.get("Selling General And Administration")),
                })

            self.cache.set(cache_key, result, ttl=86400)  # 24 hours
            return result
        except Exception as e:
            return [{"error": str(e)}]

    def get_balance_sheets(
        self, ticker: str, period: str = "annual", limit: int = 4
    ) -> list[dict[str, Any]]:
        """Get balance sheets — replaces /financials/balance-sheets/"""
        cache_key = f"balance:{ticker.upper()}:{period}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            if period == "quarterly":
                statements = t.quarterly_balance_sheet
            else:
                statements = t.balance_sheet

            if statements is None or statements.empty:
                return []

            result = []
            cols = statements.columns[:limit]
            for col in cols:
                row = statements[col]
                period_date = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                result.append({
                    "report_period": period_date,
                    "period": "Q" + str(col.quarter) + " " + str(col.year) if hasattr(col, "quarter") and period == "quarterly" else str(col.year if hasattr(col, "year") else ""),
                    "total_assets": self._safe_float(row.get("Total Assets")),
                    "total_liabilities": self._safe_float(row.get("Total Liabilities Net Minority Interest")),
                    "total_equity": self._safe_float(row.get("Stockholders Equity")),
                    "cash_and_equivalents": (
                        self._safe_float(row.get("Cash And Cash Equivalents"))
                        or self._safe_float(row.get("Cash Cash Equivalents And Short Term Investments"))
                    ),
                    "total_debt": (
                        self._safe_float(row.get("Total Debt"))
                        or (
                            self._safe_float(row.get("Long Term Debt"))
                            + self._safe_float(row.get("Current Debt"))
                        )
                    ),
                    "net_debt": self._safe_float(row.get("Net Debt")),
                    "current_assets": self._safe_float(row.get("Current Assets")),
                    "current_liabilities": self._safe_float(row.get("Current Liabilities")),
                    "inventory": self._safe_float(row.get("Inventory")),
                    "retained_earnings": self._safe_float(row.get("Retained Earnings")),
                    "goodwill": self._safe_float(row.get("Goodwill")),
                    "intangible_assets": self._safe_float(row.get("Intangible Assets")),
                    "shares_outstanding": self._safe_float(row.get("Ordinary Shares Number")),
                })

            self.cache.set(cache_key, result, ttl=86400)
            return result
        except Exception as e:
            return [{"error": str(e)}]

    def get_cash_flow_statements(
        self, ticker: str, period: str = "annual", limit: int = 4
    ) -> list[dict[str, Any]]:
        """Get cash flow statements — replaces /financials/cash-flow-statements/"""
        cache_key = f"cashflow:{ticker.upper()}:{period}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            if period == "quarterly":
                statements = t.quarterly_cashflow
            else:
                statements = t.cashflow

            if statements is None or statements.empty:
                return []

            result = []
            cols = statements.columns[:limit]
            for col in cols:
                row = statements[col]
                period_date = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                op_cf = self._safe_float(row.get("Operating Cash Flow")) or self._safe_float(row.get("Cash Flow From Continuing Operating Activities"))
                capex = abs(self._safe_float(row.get("Capital Expenditure") or row.get("Capital Expenditures") or 0))
                result.append({
                    "report_period": period_date,
                    "period": "Q" + str(col.quarter) + " " + str(col.year) if hasattr(col, "quarter") and period == "quarterly" else str(col.year if hasattr(col, "year") else ""),
                    "operating_cash_flow": op_cf,
                    "capital_expenditure": capex,
                    "free_cash_flow": op_cf - capex if op_cf is not None else None,
                    "investing_cash_flow": self._safe_float(row.get("Investing Cash Flow")),
                    "financing_cash_flow": self._safe_float(row.get("Financing Cash Flow")),
                    "dividends_paid": abs(self._safe_float(row.get("Cash Dividends Paid") or 0)),
                    "stock_based_compensation": self._safe_float(row.get("Stock Based Compensation")),
                    "change_in_working_capital": self._safe_float(row.get("Change In Working Capital")),
                    "depreciation_amortization": self._safe_float(row.get("Depreciation Amortization Depletion") or row.get("Depreciation And Amortization")),
                    "share_repurchases": abs(self._safe_float(row.get("Repurchase Of Capital Stock") or 0)),
                })

            self.cache.set(cache_key, result, ttl=86400)
            return result
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # KEY METRICS / RATIOS SNAPSHOT
    # =========================================================================

    def get_key_metrics(self, ticker: str) -> dict[str, Any]:
        """Get comprehensive metrics snapshot — replaces /financial-metrics/snapshot/"""
        cache_key = f"metrics:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            info = t.info

            # Get statements for calculated metrics
            income = self.get_income_statements(ticker, "annual", 1)
            balance = self.get_balance_sheets(ticker, "annual", 1)
            cashflow = self.get_cash_flow_statements(ticker, "annual", 1)

            revenue = income[0].get("revenue") if income and "error" not in income[0] else None
            net_income = income[0].get("net_income") if income and "error" not in income[0] else None
            total_equity = balance[0].get("total_equity") if balance and "error" not in balance[0] else None
            total_assets = balance[0].get("total_assets") if balance and "error" not in balance[0] else None
            op_cf = cashflow[0].get("operating_cash_flow") if cashflow and "error" not in cashflow[0] else None
            capex = cashflow[0].get("capital_expenditure") if cashflow and "error" not in cashflow[0] else None
            total_debt = balance[0].get("total_debt") if balance and "error" not in balance[0] else None
            shares_outstanding = info.get("sharesOutstanding")

            # Calculate derived metrics
            profit_margin = net_income / revenue if revenue and net_income and revenue != 0 else None
            roe = net_income / total_equity if net_income and total_equity and total_equity != 0 else None
            roa = net_income / total_assets if net_income and total_assets and total_assets != 0 else None
            debt_to_equity = total_debt / total_equity if total_debt and total_equity and total_equity != 0 else None
            current_assets = balance[0].get("current_assets") if balance and "error" not in balance[0] else None
            current_liabilities = balance[0].get("current_liabilities") if balance and "error" not in balance[0] else None
            current_ratio = current_assets / current_liabilities if current_assets and current_liabilities and current_liabilities != 0 else None

            result = {
                "ticker": ticker.upper(),
                # Valuation
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "pe_ratio_trailing": info.get("trailingPE"),
                "pe_ratio_forward": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "ev_to_ebitda": info.get("enterpriseToEbitda"),
                "ev_to_revenue": info.get("enterpriseToRevenue"),
                # Per-share
                "eps_trailing": info.get("trailingEps"),
                "eps_forward": info.get("forwardEps"),
                "book_value_per_share": info.get("bookValue"),
                "free_cash_flow_per_share": (
                    (op_cf - capex) / shares_outstanding
                    if op_cf and capex and shares_outstanding and shares_outstanding != 0
                    else None
                ),
                # Profitability
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "net_margin": info.get("profitMargins"),
                "calculated_profit_margin": profit_margin,
                "roe": info.get("returnOnEquity") or roe,
                "roa": info.get("returnOnAssets") or roa,
                "roic": info.get("returnOnEquity"),  # yfinance doesn't have ROIC; ROE as proxy
                # Leverage
                "debt_to_equity": info.get("debtToEquity") or debt_to_equity,
                "current_ratio": current_ratio,
                "quick_ratio": info.get("quickRatio"),
                # Growth
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "eps_growth": info.get("earningsGrowth"),
                # Dividends
                "dividend_yield": info.get("dividendYield"),
                "dividend_rate": info.get("dividendRate"),
                "payout_ratio": info.get("payoutRatio"),
                "ex_dividend_date": str(info.get("exDividendDate")) if info.get("exDividendDate") else None,
                # Cash Flow
                "operating_cash_flow": info.get("operatingCashflow"),
                "free_cash_flow": info.get("freeCashflow"),
                "ocf_calculated": op_cf,
                "capex_calculated": capex,
                "fcf_calculated": (op_cf - capex) if op_cf is not None else None,
                # Shares
                "shares_outstanding": shares_outstanding,
                "shares_float": info.get("floatShares"),
                # Company info
                "company_name": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "employees": info.get("fullTimeEmployees"),
                "website": info.get("website"),
                "country": info.get("country"),
                "exchange": info.get("exchange"),
                "source": "Yahoo Finance (yfinance)",
            }

            self.cache.set(cache_key, result, ttl=300)  # 5 min
            return result
        except Exception as e:
            return {"error": f"Failed to fetch metrics for {ticker}: {str(e)}"}

    # =========================================================================
    # EARNINGS
    # =========================================================================

    def get_earnings(self, ticker: str, limit: int = 8) -> list[dict[str, Any]]:
        """Get earnings history — replaces /earnings"""
        cache_key = f"earnings:{ticker.upper()}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            # yfinance earnings history
            earnings_dates = t.earnings_dates
            if earnings_dates is None or earnings_dates.empty:
                return []

            result = []
            for date, row in earnings_dates.head(limit).iterrows():
                result.append({
                    "report_period": date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
                    "eps_estimate": row.get("EPS Estimate"),
                    "eps_reported": row.get("Reported EPS"),
                    "eps_surprise": (
                        (row["Reported EPS"] - row["EPS Estimate"]) / abs(row["EPS Estimate"])
                        if row.get("EPS Estimate") and row.get("Reported EPS") and row["EPS Estimate"] != 0
                        else None
                    ),
                    "eps_surprise_abs": (
                        row["Reported EPS"] - row["EPS Estimate"]
                        if row.get("EPS Estimate") and row.get("Reported EPS")
                        else None
                    ),
                })

            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return [{"error": str(e)}]

    def get_earnings_history(self, ticker: str) -> list[dict[str, Any]]:
        """Get earnings history from yfinance."""
        cache_key = f"earnings_hist:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            hist = t.earnings_history
            if hist is None or hist.empty:
                return []

            result = []
            for date, row in hist.iterrows():
                result.append({
                    "date": str(date),
                    "eps_estimate": row.get("epsEstimate"),
                    "eps_actual": row.get("epsActual"),
                    "eps_difference": row.get("epsDifference"),
                    "eps_surprise_pct": row.get("surprisePercent"),
                    "quarter": row.get("quarter"),
                    "year": row.get("year"),
                })

            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # NEWS
    # =========================================================================

    def get_news(self, ticker: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get company news — replaces /news"""
        cache_key = f"news:{ticker.upper() if ticker else 'market'}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            if ticker:
                t = yf.Ticker(ticker)
                news = t.news
            else:
                # Use Yahoo Finance market news
                import requests
                headers = {"User-Agent": "Mozilla/5.0"}
                url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.ok:
                    soup = BeautifulSoup(resp.text, "xml")
                    news = []
                    for item in soup.find_all("item")[:limit]:
                        news.append({
                            "title": item.title.text if item.title else "",
                            "link": item.link.text if item.link else "",
                            "pub_date": item.pubDate.text if item.pubDate else "",
                            "source": item.source.text if item.source else "Yahoo Finance",
                            "summary": "",
                            "thumbnail": None,
                        })
                    self.cache.set(cache_key, news, ttl=900)  # 15 min for news
                    return news
                news = []

            if not news:
                return []

            result = []
            for article in news[:limit]:
                result.append({
                    "title": article.get("title", ""),
                    "link": article.get("url") or article.get("link", ""),
                    "publisher": article.get("publisher", ""),
                    "published": article.get("published", ""),
                    "summary": article.get("summary", ""),
                    "thumbnail": article.get("thumbnail", {}).get("resolutions", [{}])[0].get("url") if article.get("thumbnail") else None,
                    "source": article.get("publisher", "Yahoo Finance"),
                })

            self.cache.set(cache_key, result, ttl=900)  # 15 min
            return result
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # COMPANY INFO / FACTS
    # =========================================================================

    def get_company_info(self, ticker: str) -> dict[str, Any]:
        """Get comprehensive company info."""
        cache_key = f"info:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            info = t.info

            result = {
                "ticker": ticker.upper(),
                "name": info.get("longName"),
                "short_name": info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "exchange": info.get("exchange"),
                "currency": info.get("currency"),
                "country": info.get("country"),
                "state": info.get("state"),
                "city": info.get("city"),
                "website": info.get("website"),
                "employees": info.get("fullTimeEmployees"),
                "description": info.get("longBusinessSummary"),
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "beta": info.get("beta"),
                "dividend_yield": info.get("dividendYield"),
                "dividend_rate": info.get("dividendRate"),
                "payout_ratio": info.get("payoutRatio"),
                "ex_dividend_date": info.get("exDividendDate"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "float_shares": info.get("floatShares"),
                "avg_volume": info.get("averageVolume"),
                "volume": info.get("volume"),
                "pe_trailing": info.get("trailingPE"),
                "pe_forward": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "50d_avg": info.get("fiftyDayAverage"),
                "200d_avg": info.get("twoHundredDayAverage"),
                "source": "Yahoo Finance (yfinance)",
            }
            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # INSIDER TRADES (from SEC Form 4 via OpenInsider scraping)
    # =========================================================================

    def get_insider_trades(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get insider trades — replaces /insider-trades/ using OpenInsider."""
        cache_key = f"insider:{ticker.upper()}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Try yfinance first
            t = yf.Ticker(ticker)
            insider = t.insider_transactions
            if insider is not None and not insider.empty:
                result = []
                for _, row in insider.head(limit).iterrows():
                    result.append({
                        "date": str(row.name) if hasattr(row.name, "strftime") else str(row.get("Date", "")),
                        "insider": row.get("Insider", ""),
                        "relation": row.get("Relation", ""),
                        "transaction_type": row.get("Transaction", ""),
                        "shares": row.get("Shares", 0),
                        "price_per_share": row.get("Value", 0) / row.get("Shares", 1) if row.get("Shares") else None,
                        "value": row.get("Value", 0),
                        "shares_after": row.get("SharesAfter", None),
                        "source": "Yahoo Finance",
                    })
                if result:
                    self.cache.set(cache_key, result, ttl=3600)
                    return result

            # Fallback: scrape OpenInsider
            url = f"http://openinsider.com/screener?s={ticker}&o=&pl=&ph=&ll=&lh=&fd=730&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&xs=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfl1=&nocaps&sortcol=0&cnt={limit}&page=1"
            resp = self._sync_client.get("http://openinsider.com", headers={"User-Agent": "Mozilla/5.0"})
            return []  # OpenInsider scraping is complex; return yfinance data for now
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # INSTITUTIONAL HOLDINGS (from SEC 13F via SEC EDGAR)
    # =========================================================================

    def get_institutional_holders(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get institutional holders — replaces /institutional-holdings/"""
        cache_key = f"institutional:{ticker.upper()}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            inst = t.institutional_holders
            if inst is not None and not inst.empty:
                result = []
                for _, row in inst.head(limit).iterrows():
                    result.append({
                        "holder": row.get("Holder", ""),
                        "shares": row.get("Shares", 0),
                        "date_reported": str(row.get("DateReport", "")),
                        "pct_out": row.get("pctOut", 0),
                        "value": row.get("Value", 0),
                    })
                self.cache.set(cache_key, result, ttl=86400)
                return result
            return []
        except Exception as e:
            return [{"error": str(e)}]

    def get_major_holders(self, ticker: str) -> dict[str, Any]:
        """Get major holders breakdown."""
        cache_key = f"holders:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            holders = t.major_holders
            result = {
                "insider_pct": None,
                "institutions_pct": None,
                "institutions_float_pct": None,
                "num_institutions": None,
            }
            if holders is not None and not holders.empty:
                for _, row in holders.iterrows():
                    if "Insiders" in str(row.get(1, "")):
                        result["insider_pct"] = row.get(0)
                    elif "Institutions" in str(row.get(1, "")):
                        result["institutions_pct"] = row.get(0)
                    elif "Float" in str(row.get(1, "")):
                        result["institutions_float_pct"] = row.get(0)

            inst_holders = self.get_institutional_holders(ticker, 5)
            result["top_institutions"] = inst_holders
            result["source"] = "Yahoo Finance"
            self.cache.set(cache_key, result, ttl=86400)
            return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # ANALYST DATA
    # =========================================================================

    def get_analyst_data(self, ticker: str) -> dict[str, Any]:
        """Get analyst recommendations and price targets."""
        cache_key = f"analyst:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            info = t.info

            recommendations = t.recommendations
            rec_summary = None
            if recommendations is not None and not recommendations.empty:
                # Get recent recommendations
                rec_counts = {}
                for _, row in recommendations.tail(20).iterrows():
                    grade = row.get("To Grade", "Unknown")
                    rec_counts[grade] = rec_counts.get(grade, 0) + 1
                rec_summary = rec_counts

            result = {
                "ticker": ticker.upper(),
                "target_high": info.get("targetHighPrice"),
                "target_low": info.get("targetLowPrice"),
                "target_mean": info.get("targetMeanPrice"),
                "target_median": info.get("targetMedianPrice"),
                "recommendation": info.get("recommendationKey"),
                "num_analysts": info.get("numberOfAnalystOpinions"),
                "recommendation_summary": rec_summary,
                "source": "Yahoo Finance",
            }
            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # SEC FILINGS (direct from SEC EDGAR — no API key needed)
    # =========================================================================

    def get_sec_filings_list(
        self, ticker: str, filing_type: str = "10-K", limit: int = 5
    ) -> list[dict[str, Any]]:
        """Get SEC filing metadata — replaces /filings/"""
        cache_key = f"filings:{ticker.upper()}:{filing_type}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # SEC EDGAR full-text search API (free, no key)
            cik = self._get_cik(ticker)
            if not cik:
                return [{"error": f"CIK not found for {ticker}"}]

            url = f"https://efts.sec.gov/LATEST/search-index?q=form-type%3A(%22{filing_type}%22)+AND+company%3A(%22{ticker}%22)&dateRange=custom&startdt=2020-01-01&enddt={datetime.now().strftime('%Y-%m-%d')}&page={1}"

            headers = {
                "User-Agent": "HeonAgent/1.0 (Research)",
                "Accept-Encoding": "gzip, deflate",
                "Host": "efts.sec.gov",
            }
            resp = self._sync_client.get(url, headers=headers)

            if resp.status_code != 200:
                # Fallback: use yfinance calendar/earnings
                return self._fallback_filings(ticker, filing_type, limit)

            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])

            result = []
            for hit in hits[:limit]:
                src = hit.get("_source", {})
                result.append({
                    "filing_type": src.get("form_type", [filing_type])[0] if isinstance(src.get("form_type"), list) else src.get("form_type", filing_type),
                    "filing_date": src.get("file_date", ""),
                    "accession_number": src.get("adsh", ""),
                    "filing_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={filing_type}&dateb=&owner=include&count=40",
                    "company_name": src.get("display_names", [""])[0] if isinstance(src.get("display_names"), list) else "",
                    "description": src.get("file_description", ""),
                })

            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return self._fallback_filings(ticker, filing_type, limit)

    def _fallback_filings(self, ticker: str, filing_type: str, limit: int) -> list[dict[str, Any]]:
        """Fallback filings from yfinance."""
        try:
            t = yf.Ticker(ticker)
            # Use earnings dates as proxy
            cal = t.calendar
            return [{"note": f"SEC EDGAR direct access pending. File type: {filing_type}", "ticker": ticker}]
        except:
            return []

    def get_sec_filing_content(
        self, cik: str, accession_number: str, filing_type: str = "10-K"
    ) -> dict[str, Any]:
        """Get specific filing content — replaces /filings/items/"""
        cache_key = f"filing_content:{cik}:{accession_number}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Get filing index
            acc_clean = accession_number.replace("-", "")
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"

            headers = {
                "User-Agent": "HeonAgent/1.0 (Research)",
            }
            resp = self._sync_client.get(url, headers=headers)

            if resp.status_code != 200:
                return {"error": f"SEC API returned {resp.status_code}"}

            data = resp.json()

            # Get the filing document URL
            url2 = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{accession_number}-index.htm"
            resp2 = self._sync_client.get(url2, headers=headers)

            if resp2.status_code != 200:
                return {"error": f"Could not fetch filing index"}

            # Parse the index to find the main document
            soup = BeautifulSoup(resp2.text, "html.parser")
            doc_link = None
            for link in soup.find_all("a"):
                href = link.get("href", "")
                if href.endswith(".htm") or href.endswith(".html"):
                    if "primary" in href.lower() or href.endswith(f"{acc_clean.split('-')[0]}.htm"):
                        doc_link = href
                        break

            if not doc_link:
                # Use first .htm file in the directory
                for link in soup.find_all("a"):
                    href = link.get("href", "")
                    if href.endswith(".htm") or href.endswith(".html"):
                        doc_link = href
                        break

            if not doc_link:
                return {"error": "Could not find filing document"}

            if not doc_link.startswith("http"):
                doc_link = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc_link}"

            resp3 = self._sync_client.get(doc_link, headers=headers)
            if resp3.status_code != 200:
                return {"error": f"Could not fetch filing document"}

            content = resp3.text

            result = {
                "filing_type": filing_type,
                "accession_number": accession_number,
                "cik": cik,
                "document_url": doc_link,
                "content": content[:50000],  # Cap at 50KB
                "content_length": len(content),
                "source": "SEC EDGAR",
            }

            self.cache.set(cache_key, result, ttl=604800)  # 7 days — filings are immutable
            return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # STOCK SCREENER (using yfinance + manual filtering)
    # =========================================================================

    def screen_stocks(
        self, criteria: dict[str, Any], limit: int = 25
    ) -> list[dict[str, Any]]:
        """
        Screen stocks by criteria — replaces /financials/search/screener/
        Since we don't have the Financial Datasets screener API, we use
        a curated list of S&P 500 / NASDAQ tickers and filter locally.
        """
        cache_key = f"screener:{hash(json.dumps(criteria, sort_keys=True))}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Get S&P 500 tickers from Wikipedia
            sp500 = self._get_sp500_tickers()
            results = []

            for ticker in sp500[:100]:  # Limit to top 100 for speed
                try:
                    t = yf.Ticker(ticker)
                    info = t.info

                    match = True
                    for field, condition in criteria.items():
                        value = self._get_nested_field(info, field)
                        if value is None:
                            match = False
                            break

                        op = condition.get("operator", "gt")
                        threshold = condition.get("value")

                        if op == "gt" and not (value > threshold):
                            match = False
                            break
                        elif op == "gte" and not (value >= threshold):
                            match = False
                            break
                        elif op == "lt" and not (value < threshold):
                            match = False
                            break
                        elif op == "lte" and not (value <= threshold):
                            match = False
                            break
                        elif op == "eq" and not (value == threshold):
                            match = False
                            break

                    if match:
                        results.append({
                            "ticker": ticker,
                            "name": info.get("shortName", ""),
                            "sector": info.get("sector", ""),
                            "market_cap": info.get("marketCap"),
                            "pe_ratio": info.get("trailingPE"),
                            "pb_ratio": info.get("priceToBook"),
                            "dividend_yield": info.get("dividendYield"),
                            "revenue_growth": info.get("revenueGrowth"),
                            "gross_margin": info.get("grossMargins"),
                            "operating_margin": info.get("operatingMargins"),
                            "roe": info.get("returnOnEquity"),
                        })

                    if len(results) >= limit:
                        break
                except:
                    continue

            self.cache.set(cache_key, results, ttl=3600)
            return results
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # ETF DATA
    # =========================================================================

    def get_etf_data(self, ticker: str) -> dict[str, Any]:
        """Get comprehensive ETF data."""
        cache_key = f"etf:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            info = t.info

            # Get holdings if available
            holdings = []
            try:
                hold = t.fund_top_holders
                if hold is not None and not hold.empty:
                    for _, row in hold.head(10).iterrows:
                        holdings.append({
                            "name": row.get("Name", ""),
                            "pct": row.get("% Out", 0),
                        })
            except:
                pass

            result = {
                "ticker": ticker.upper(),
                "name": info.get("longName") or info.get("shortName"),
                "category": info.get("category"),
                "family": info.get("fundFamily"),
                "exchange": info.get("exchange"),
                "currency": info.get("currency"),
                "total_assets": info.get("totalAssets") or info.get("netAssets"),
                "nav_price": info.get("navPrice") or info.get("previousClose"),
                "expense_ratio": info.get("annualReportExpenseRatio") or info.get("expenseRatio"),
                "dividend_yield": info.get("dividendYield"),
                "yield_12m": info.get("yield"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "avg_volume": info.get("averageVolume"),
                "inception_date": str(info.get("fundInceptionDate")) if info.get("fundInceptionDate") else None,
                "holdings_count": info.get("holdingsCount"),
                "top_holdings": holdings,
                "source": "Yahoo Finance",
            }
            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @staticmethod
    def _safe_float(value) -> float | None:
        """Safely convert value to float."""
        if value is None:
            return None
        try:
            f = float(value)
            if f != f:  # NaN check
                return None
            return round(f, 2)
        except (ValueError, TypeError):
            return None

    def _get_cik(self, ticker: str) -> str | None:
        """Get CIK number from ticker."""
        cache_key = f"cik:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={}&type=&dateb=&owner=include&count=10&output=atom"
            resp = self._sync_client.get(url.format(ticker), headers={"User-Agent": "HeonAgent/1.0"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "xml")
                cik_tag = soup.find("cik")
                if cik_tag:
                    cik = cik_tag.text.strip().zfill(10)
                    self.cache.set(cache_key, cik, ttl=604800)
                    return cik
            return None
        except:
            return None

    def _get_sp500_tickers(self) -> list[str]:
        """Get S&P 500 ticker list from Wikipedia."""
        cache_key = "sp500_tickers"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            resp = self._sync_client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", {"id": "constituents"})
            tickers = []
            if table:
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if cells:
                        ticker = cells[0].text.strip()
                        if ticker:
                            tickers.append(ticker)
            self.cache.set(cache_key, tickers, ttl=604800)
            return tickers
        except:
            # Fallback: popular tickers
            return [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
                "UNH", "JNJ", "V", "XOM", "WMT", "PG", "JPM", "MA", "HD", "CVX",
                "MRK", "ABBV", "LLY", "PEP", "KO", "COST", "AVGO", "TMO", "MCD",
                "CSCO", "ACN", "ABT", "DHR", "LIN", "ADBE", "CRM", "UPS", "TXN",
                "PM", "NEE", "BMY", "QCOM", "RTX", "AMD", "INTC", "AMGN", "SPGI",
                "IBM", "GE", "CAT", "BA", "GS", "MS", "BLK", "BKNG", "SBUX",
                "INTU", "ISRG", "MDLZ", "GILD", "ADI", "SYK", "VRTX", "REGN",
                "ZTS", "HON", "ELV", "LRCX", "PANW", "SNPS", "CDNS", "CME",
                "TGT", "CI", "BDX", "CL", "MO", "TMUS", "DE", "CB", "SO", "DUK",
                "SCHW", "MMC", "EOG", "MPC", "PSX", "APH", "KLAC", "AON", "ITW",
                "ICE", "SHW", "CMG", "MCO", "ORLY", "FCX", "APD", "F", "GM",
            ]

    # =========================================================================
    # WEB SCRAPING SUPPLEMENTARY DATA
    # =========================================================================

    def get_financecharts_data(self, ticker: str, metric: str) -> dict[str, Any]:
        """Scrape FinanceCharts.com for supplementary data."""
        try:
            url = f"https://financecharts.com/stocks/{ticker}/financials/{metric}"
            resp = self._sync_client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                return {"url": url, "status": "fetched", "length": len(resp.text)}
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def get_macrotrends_data(self, ticker: str, metric: str) -> dict[str, Any]:
        """Scrape Macrotrends.net for supplementary data."""
        try:
            encoded = quote(metric.replace("_", "-"))
            url = f"https://www.macrotrends.net/stocks/charts/{ticker}/{encoded}"
            resp = self._sync_client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                tables = soup.find_all("table")
                result = []
                for table in tables:
                    rows = []
                    for tr in table.find_all("tr"):
                        cells = [td.text.strip() for td in tr.find_all("td")]
                        if cells:
                            rows.append(cells)
                    if rows:
                        result.append(rows)
                return {"url": url, "tables_found": len(result), "data": result[:3]}
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}


def col_date_to_year(col) -> str:
    """Extract year from a column header."""
    try:
        s = str(col)
        if "-" in s:
            return s[:4]
        return s
    except:
        return ""
