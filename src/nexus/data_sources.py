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
                "User-Agent": "NexusAgent/1.0 (Financial Research)"
            }
        )
        self._sync_client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "NexusAgent/1.0 (Financial Research)"
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
                    "stock_based_compensation": self._safe_float(row.get("Stock Based Compensation") or row.get("StockBasedCompensation") or 0),
                    "change_in_working_capital": self._safe_float(row.get("Change In Working Capital")),
                    "depreciation_amortization": self._safe_float(row.get("Depreciation Amortization Depletion") or row.get("Depreciation And Amortization")),
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
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "net_margin": info.get("profitMargins"),
                "calculated_profit_margin": profit_margin,
                "roe": info.get("returnOnEquity") or roe,
                "roa": info.get("returnOnAssets") or roa,
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
                "fcf_adjusted": (
                    (op_cf - capex - abs(self._safe_float(
                        cashflow[0].get("stock_based_compensation", 0)
                    )))
                    if op_cf is not None and capex is not None
                    else None
                ),
                "sbc_ttm": abs(self._safe_float(
                    cashflow[0].get("stock_based_compensation", 0)
                )) if cashflow and "error" not in cashflow[0] else None,
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

            # V10: True ROIC calculation (replace ROE proxy)
            roic_value = info.get("returnOnInvestedCapital")
            if roic_value is None and income and "error" not in income[0] and balance and "error" not in balance[0]:
                op_inc = income[0].get("operating_income")
                tax_prov = income[0].get("tax_provision")
                pretax = income[0].get("pretax_income")
                if op_inc is not None and tax_prov is not None and pretax and pretax != 0:
                    nopat = float(op_inc) * (1 - float(tax_prov) / float(pretax))
                    td = balance[0].get("total_debt") or 0
                    te = balance[0].get("total_equity") or 0
                    cash_eq = balance[0].get("cash_and_equivalents") or 0
                    gw = balance[0].get("goodwill") or 0
                    invested_capital = float(td) + float(te) - float(cash_eq) - float(gw)
                    roic_value = (nopat / invested_capital) if invested_capital > 0 else None
            result["roic"] = roic_value

            # V10: Add WACC estimate (store as decimal fraction, not percentage)
            wacc_data = self.get_wacc_estimate(ticker)
            if wacc_data and "error" not in wacc_data:
                result["wacc_estimate"] = wacc_data["wacc_pct"] / 100.0

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
            miss_count = 0
            for date, row in earnings_dates.head(limit).iterrows():
                eps_est = row.get("EPS Estimate")
                eps_rep = row.get("Reported EPS")
                if eps_est and eps_rep and eps_rep < eps_est:
                    miss_count += 1
                result.append({
                    "report_period": date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
                    "eps_estimate": eps_est,
                    "eps_reported": eps_rep,
                    "eps_surprise": (
                        (eps_rep - eps_est) / abs(eps_est)
                        if eps_est and eps_rep and eps_est != 0
                        else None
                    ),
                    "eps_surprise_abs": (
                        eps_rep - eps_est
                        if eps_est and eps_rep
                        else None
                    ),
                })

            self.cache.set(cache_key, {"results": result, "misses_last_4q": miss_count}, ttl=3600)
            return {"results": result, "misses_last_4q": miss_count}
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
            # V10: Add WACC estimate (store as decimal fraction)
            wacc_data = self.get_wacc_estimate(ticker)
            if wacc_data and "error" not in wacc_data:
                result["wacc"] = wacc_data["wacc_pct"] / 100.0
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
        """Get SEC filing metadata via Submissions API."""
        cache_key = f"filings:{ticker.upper()}:{filing_type}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            cik = self._get_cik(ticker)
            if not cik:
                return [{"error": f"CIK not found for {ticker}"}]

            # Use SEC Submissions API (reliable, no key needed)
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            headers = {"User-Agent": "NexusAgent/1.0 (Research)"}
            resp = self._sync_client.get(url, headers=headers)

            if resp.status_code != 200:
                return self._fallback_filings(ticker, filing_type, limit)

            data = resp.json()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accession_numbers = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            description = recent.get("primaryDocDescription", [])

            result = []
            count = 0
            for i in range(len(forms)):
                if forms[i] == filing_type:
                    acc = accession_numbers[i] if i < len(accession_numbers) else ""
                    result.append({
                        "filing_type": filing_type,
                        "filing_date": dates[i] if i < len(dates) else "",
                        "accession_number": acc,
                        "filing_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={filing_type}&dateb=&owner=include&count=40",
                        "company_name": data.get("name", ""),
                        "description": description[i][:200] if i < len(description) else "",
                        "cik": cik,
                    })
                    count += 1
                    if count >= limit:
                        break

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
        """Get specific filing content via SEC EDGAR TXT URL."""
        cache_key = f"filing_content:{cik}:{accession_number}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        headers = {"User-Agent": "NexusAgent/1.0 (Research)"}

        try:
            acc_clean = accession_number.replace("-", "")
            cik_num = int(cik)

            # Primary: Direct TXT URL (most reliable)
            txt_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_num}/"
                f"{acc_clean}/{accession_number}.txt"
            )
            resp = self._sync_client.get(txt_url, headers=headers)

            if resp.status_code != 200:
                # Fallback: try index page to find the document
                index_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_num}/"
                    f"{acc_clean}/{accession_number}-index.htm"
                )
                resp_idx = self._sync_client.get(index_url, headers=headers)
                if resp_idx.status_code != 200:
                    return {"error": f"Could not fetch filing (HTTP {resp.status_code})"}

                soup = BeautifulSoup(resp_idx.text, "html.parser")
                doc_link = None
                for a in soup.find_all("a"):
                    href = a.get("href", "")
                    if href.endswith(".txt"):
                        doc_link = href
                        break
                if not doc_link:
                    for a in soup.find_all("a"):
                        href = a.get("href", "")
                        if href.endswith(".htm") or href.endswith(".html"):
                            doc_link = href
                            break
                if not doc_link:
                    return {"error": "Could not find filing document in index"}

                if not doc_link.startswith("http"):
                    doc_link = (
                        f"https://www.sec.gov/Archives/edgar/data/{cik_num}/"
                        f"{acc_clean}/{doc_link}"
                    )
                resp = self._sync_client.get(doc_link, headers=headers)
                if resp.status_code != 200:
                    return {"error": f"Could not fetch filing document (HTTP {resp.status_code})"}

            content = resp.text

            result = {
                "filing_type": filing_type,
                "accession_number": accession_number,
                "cik": cik,
                "document_url": str(resp.url),
                "content": content[:500000],  # Cap at 500KB for footnote extraction
                "content_length": len(content),
                "source": "SEC EDGAR",
            }

            self.cache.set(cache_key, result, ttl=604800)
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
                # V10: Bid-ask spread
                "bid": info.get("bid"),
                "ask": info.get("ask"),
                "bid_ask_spread_bps": round(
                    (float(info.get("ask", 0)) - float(info.get("bid", 0)))
                    / max(float(info.get("navPrice") or info.get("previousClose", 1)), 1)
                    * 10000, 2
                ) if info.get("bid") and info.get("ask") else None,
                "source": "Yahoo Finance",
            }
            self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # WACC ESTIMATION (V10) — using sector-wacc.md lookup + adjustments
    # =========================================================================

    def get_wacc_estimate(self, ticker: str) -> dict[str, Any]:
        """
        Estimate WACC using sector baseline + company-specific adjustments.

        Strategy:
          1. Read sector base WACC from .heon/sector-wacc.md reference table
          2. Apply adjustment factors based on company metrics
          3. Return estimated WACC with breakdown

        All data from existing yfinance metrics — no new API calls.
        """
        cache_key = f"wacc:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Get baseline metrics
        metrics = self.get_key_metrics(ticker)
        info = {}
        try:
            t = yf.Ticker(ticker)
            info = t.info
        except Exception:
            pass

        sector = (metrics.get("sector") or info.get("sector") or "").lower()
        sector_wacc = self._lookup_sector_wacc(sector)

        if sector_wacc is None:
            # Fallback: use a generic 9% midpoint
            sector_wacc = {"sector": sector, "low": 8.0, "high": 10.0, "midpoint": 9.0, "notes": "Fallback estimate"}

        base_wacc = sector_wacc["midpoint"]
        adjustments = []
        adjustment_pct = 0.0

        # --- Positive adjustments (increase WACC) ---

        # High debt: D/E > 1.5 → +1-2%
        de = metrics.get("debt_to_equity")
        if de is not None and de > 1.5:
            adj = min(2.0, (float(de) - 1.5) * 1.0)
            adjustments.append(("High debt (D/E > 1.5)", adj))
            adjustment_pct += adj

        # Small cap: market cap < $2B → +1-2%
        mcap = metrics.get("market_cap")
        if mcap is not None and mcap < 2e9:
            adj = 1.5
            adjustments.append(("Small cap (< $2B)", adj))
            adjustment_pct += adj

        # Emerging markets exposure → +1-3% (proxy: country not US)
        country = (info.get("country") or "").upper()
        if country not in ("US", "USA", "UNITED STATES", ""):
            adj = 1.0
            adjustments.append(("Non-US exposure", adj))
            adjustment_pct += adj

        # Regulatory uncertainty → +0.5-1.5% (proxy: fintech/bio/pharma keywords in sector)
        if any(kw in sector for kw in ("fintech", "biotechnology", "pharmaceutical")):
            adj = 1.0
            adjustments.append(("Regulatory uncertainty sector", adj))
            adjustment_pct += adj

        # --- Negative adjustments (decrease WACC) ---

        # Market leader with moat: gross margin > 50% → -0.5-1%
        gm = metrics.get("gross_margin")
        if gm is not None and gm > 0.50:
            adj = -0.75
            adjustments.append(("Market leader / wide moat (GM > 50%)", adj))
            adjustment_pct += adj

        # Recurring revenue model → -0.5-1% (proxy: sector)
        if any(kw in sector for kw in ("software", "subscription", "saas")):
            adj = -0.5
            adjustments.append(("Recurring revenue model", adj))
            adjustment_pct += adj

        # Final WACC
        wacc = base_wacc + adjustment_pct
        wacc = max(4.0, min(15.0, wacc))  # Clamp to 4-15% range

        result = {
            "ticker": ticker.upper(),
            "wacc_pct": round(wacc, 2),
            "base_sector_wacc": round(base_wacc, 2),
            "sector": sector_wacc["sector"],
            "sector_range": f"{sector_wacc['low']}%-{sector_wacc['high']}%",
            "adjustments": adjustments,
            "adjustment_total": round(adjustment_pct, 2),
            "method": "Sector WACC table + company adjustments",
            "source": "sector-wacc.md reference table",
        }
        self.cache.set(cache_key, result, ttl=86400)
        return result

    SECTOR_WACC_CACHE: dict[str, dict] | None = None

    def _lookup_sector_wacc(self, sector: str) -> dict | None:
        """Look up a sector's WACC range from .heon/sector-wacc.md reference table."""
        if FreeFinanceAPI.SECTOR_WACC_CACHE is None:
            FreeFinanceAPI.SECTOR_WACC_CACHE = self._load_sector_wacc_table()

        if not sector:
            return None

        # Exact match first
        if sector in FreeFinanceAPI.SECTOR_WACC_CACHE:
            return FreeFinanceAPI.SECTOR_WACC_CACHE[sector]

        # Fuzzy match (e.g. "technology" matches "information technology")
        for key, val in FreeFinanceAPI.SECTOR_WACC_CACHE.items():
            if sector in key or key in sector:
                return val

        return None

    @staticmethod
    def _load_sector_wacc_table() -> dict[str, dict]:
        """
        Parse .heon/sector-wacc.md into a dict of sector -> {low, high, midpoint, notes}.
        File format: markdown table with | Sector | Typical WACC Range | Notes |
        """
        import os
        import re

        # Search paths for the reference file
        search_paths = [
            os.path.join(os.path.dirname(__file__), "..", "..", ".heon", "sector-wacc.md"),
            os.path.join(os.path.dirname(__file__), "..", "..", ".heon", "sector-wacc.md"),
            ".heon/sector-wacc.md",
        ]
        filepath = None
        for p in search_paths:
            if os.path.exists(p):
                filepath = p
                break

        if not filepath:
            return {}

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        result = {}
        # Parse table rows: | Sector | 8-10% | Notes |
        pattern = r"\|\s*([A-Za-z\s/-]+)\s*\|\s*(\d+)\s*-\s*(\d+)%\s*\|"
        for match in re.finditer(pattern, content):
            sector_name = match.group(1).strip().lower()
            low = float(match.group(2))
            high = float(match.group(3))
            midpoint = (low + high) / 2

            # Extract notes from the rest of the line up to the closing |
            line_start = max(0, match.start() - 2)
            line_end = content.find("\n", match.start())
            line = content[line_start:line_end] if line_end > 0 else content[line_start:]
            notes = ""
            notes_match = re.search(r"\|\s*[^\|]+\|\s*([^\|]+)\s*\|", line)
            if notes_match:
                notes = notes_match.group(1).strip()

            result[sector_name] = {
                "sector": sector_name.title(),
                "low": low,
                "high": high,
                "midpoint": midpoint,
                "notes": notes,
            }

        return result

    # =========================================================================
    # OFF-BALANCE SHEET COMMITMENTS (V10) — from SEC 10-K footnotes
    # =========================================================================

    def get_off_balance_sheet_commitments(self, ticker: str) -> dict[str, Any]:
        """
        Fetch off-balance sheet commitments from latest 10-K.
        Uses direct TXT URL for full filing text.
        """
        cache_key = f"obs:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        result = {
            "ticker": ticker.upper(),
            "purchase_obligations": None,
            "commitment_ratio": None,
            "cash_on_balance_sheet": None,
            "source": "SEC EDGAR 10-K footnotes",
            "filing_date": None,
            "status": "not_found",
        }

        try:
            filings = self.get_sec_filings_list(ticker, "10-K", limit=1)
            if not filings or "error" in (filings[0] if filings else {}):
                result["status"] = "no_10k_found"
                self.cache.set(cache_key, result, ttl=86400)
                return result

            latest = filings[0]
            cik_str = latest.get("cik") or self._get_cik(ticker) or "0000000000"
            accession = latest.get("accession_number")
            result["filing_date"] = latest.get("filing_date")
            if not accession:
                result["status"] = "missing_accession"
                self.cache.set(cache_key, result, ttl=86400)
                return result

            # Direct TXT URL for full content (no cap)
            acc_clean = accession.replace("-", "")
            cik_num = int(cik_str)
            txt_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_num}/"
                f"{acc_clean}/{accession}.txt"
            )
            headers = {"User-Agent": "NexusAgent/1.0 (Research)"}
            resp = self._sync_client.get(txt_url, headers=headers)
            if resp.status_code != 200:
                result["status"] = f"fetch_failed_http_{resp.status_code}"
                self.cache.set(cache_key, result, ttl=86400)
                return result

            content = resp.text

            # Parse commitments from full text (search strategically)
            text_len = len(content)
            obligations = self._parse_commitments_from_text(content)

            if obligations is not None and obligations > 0:
                result["purchase_obligations"] = round(obligations, 2)
                result["status"] = "found"
                balance = self.get_balance_sheets(ticker, "annual", 1)
                if balance and "error" not in balance[0]:
                    cash = balance[0].get("cash_and_equivalents")
                    if cash is not None and cash > 0:
                        cash_val = float(cash)
                        result["cash_on_balance_sheet"] = round(cash_val, 2)
                        # Normalize: if obligations are in millions vs cash in raw dollars
                        if obligations < cash_val * 0.01 and obligations > 0:
                            obligations_scaled = obligations * 1_000_000
                            result["purchase_obligations"] = round(obligations_scaled, 2)
                            obligations = obligations_scaled
                        ratio = obligations / cash_val
                        result["commitment_ratio"] = round(ratio, 4)
            else:
                result["status"] = "not_found_in_filing"

            self.cache.set(cache_key, result, ttl=86400)
            return result

        except Exception as e:
            result["status"] = f"error: {str(e)[:100]}"
            self.cache.set(cache_key, result, ttl=86400)
            return result

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from SEC filing text for clean regex matching."""
        import re
        # Remove all HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decode common entities
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        text = re.sub(r'&#\d+;', ' ', text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _parse_commitments_from_text(text: str) -> float | None:
        """
        Parse "Commitments and Contingencies" or "Contractual Obligations"
        footnotes from SEC filing text. Strips HTML first.
        """
        import re

        # Strip HTML for reliable pattern matching
        text = FreeFinanceAPI._strip_html(text)

        total_obligations = 0.0
        found_any = False

        def _extract_total_from_section(section: str) -> float | None:
            """Extract the 'Total' row dollar amount from a section."""
            # Look for "Total" near a dollar amount
            total_match = re.search(
                r"(?i)total\s+[^\$]{0,100}?\$\s*([\d,]+(?:\.\d+)?)\s*(?:million|billion)?",
                section,
            )
            if total_match:
                val = float(total_match.group(1).replace(",", ""))
                return val
            return None

        def _extract_largest_amount(section: str) -> float | None:
            """Extract the largest dollar amount from a section."""
            amounts = re.findall(r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:million|billion)?', section)
            if not amounts:
                return None
            parsed = []
            for a in amounts:
                val = float(a.replace(",", ""))
                if val < 1e6:  # Likely in thousands/millions
                    parsed.append(val * 1e6)
                elif val < 1e12:  # Already correct
                    parsed.append(val)
            return max(parsed) if parsed else None

        # Strategy 1: "Contractual Obligations" table
        co_match = re.search(r"(?i)contractual\s+obligations[\s\S]{0,5000}?(?=critical|item\s+|$)", text)
        if co_match:
            section = co_match.group(0)
            total_val = _extract_total_from_section(section)
            if total_val:
                total_obligations += total_val
                found_any = True
            else:
                val = _extract_largest_amount(section)
                if val:
                    total_obligations = val
                    found_any = True

        # Strategy 2: "Commitments and Contingencies" footnote section
        if not found_any:
            cc_match = re.search(
                r"(?i)commitments\s+and\s+contingencies[\s\S]{0,8000}?(?=note\s+\d+|item\s+|$)",
                text,
            )
            if cc_match:
                section = cc_match.group(0)
                total_val = _extract_total_from_section(section)
                if total_val:
                    total_obligations = total_val
                    found_any = True
                # Check for "Purchase Obligations" within the note
                po = re.search(r"(?i)purchase\s+obligations?[\s\S]{0,500}", section)
                if po and not found_any:
                    val = _extract_largest_amount(po.group(0))
                    if val:
                        total_obligations = val
                        found_any = True

        # Strategy 3: Direct "Purchase Obligations" line (anywhere)
        if not found_any:
            po_match = re.search(r"(?i)purchase\s+obligations?[\s\S]{0,500}?(?=total|due|\$)", text)
            if po_match:
                val = _extract_largest_amount(po_match.group(0))
                if val:
                    total_obligations = val
                    found_any = True

        return total_obligations if found_any and total_obligations > 0 else None

    # =========================================================================
    # LEGAL / REGULATORY FRESHNESS CHECK (V10)
    # =========================================================================

    def get_legal_regulatory_status(self, ticker: str) -> dict[str, Any]:
        """
        Check legal/regulatory freshness from SEC filings.
        V10: must have verifiable development within 90 days.
        """
        cache_key = f"legal:{ticker.upper()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        from datetime import datetime, timedelta
        now = datetime.now()
        ninety_days_ago = now - timedelta(days=90)

        result = {
            "ticker": ticker.upper(),
            "fresh": False,
            "latest_date": None,
            "source": None,
            "details": "No legal/regulatory data found within 90 days",
            "status": "not_checked",
        }

        def _fetch_txt_content(ticker_inner: str, filing_type: str) -> str | None:
            """Helper: fetch full TXT from SEC for a filing type."""
            filings_inner = self.get_sec_filings_list(ticker_inner, filing_type, limit=1)
            if not filings_inner or "error" in (filings_inner[0] if filings_inner else {}):
                return None
            f = filings_inner[0]
            cik_str = f.get("cik") or self._get_cik(ticker_inner)
            acc = f.get("accession_number")
            if not cik_str or not acc:
                return None
            acc_clean = acc.replace("-", "")
            txt_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik_str)}/"
                f"{acc_clean}/{acc}.txt"
            )
            try:
                r = self._sync_client.get(txt_url, headers={"User-Agent": "NexusAgent/1.0 (Research)"})
                if r.status_code == 200:
                    # Search Item 3 in the first 30% of the filing (where legal proceedings live)
                    section_end = len(r.text) // 3
                    return r.text[:section_end]
            except Exception:
                pass
            return None

        def _check_filing(filing_type: str) -> bool:
            """Check a specific filing type for legal dates."""
            content = _fetch_txt_content(ticker, filing_type)
            if not content:
                return False
            legal_text = self._extract_legal_proceedings(content)
            if not legal_text:
                return False
            dates = self._extract_dates(legal_text)
            if not dates:
                return False
            latest = max(dates)
            result["latest_date"] = latest.strftime("%Y-%m-%d")
            result["details"] = legal_text[:500].replace("\n", " ").strip()
            result["source"] = f"SEC {filing_type} Item 3"
            result["fresh"] = latest >= ninety_days_ago
            result["status"] = "fresh" if result["fresh"] else "stale"
            return result["fresh"]

        try:
            # Strategy 1: 10-K Item 3
            if _check_filing("10-K"):
                self.cache.set(cache_key, result, ttl=3600)
                return result

            # Strategy 2: 10-Q fallback
            if _check_filing("10-Q"):
                self.cache.set(cache_key, result, ttl=3600)
                return result

            if not result.get("latest_date"):
                result["status"] = "legal_section_not_found"
            else:
                result["status"] = "stale"

            self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            result["status"] = f"error: {str(e)[:100]}"
            self.cache.set(cache_key, result, ttl=3600)
            return result

    @staticmethod
    def _extract_legal_proceedings(text: str) -> str | None:
        """Extract Item 3 (Legal Proceedings) body from 10-K. Strips HTML."""
        import re

        clean = FreeFinanceAPI._strip_html(text)

        # Skip the TOC section (first ~60000 chars) to find actual body content
        # The TOC has brief entries like "Item 3. Legal Proceedings 24"
        # The body has actual paragraphs describing litigation
        body_start = max(60000, len(clean) // 10)
        body = clean[body_start:]

        # Search for legal proceedings content in the body section
        patterns = [
            r"(?i)item\s+3\.?\s*legal\s+proceedings[\s\S]{0,8000}?(?=item\s+4|item\s+5)",
            r"(?i)legal\s+proceedings[\s\S]{0,5000}?(?=item\s+\d|PART\s+II)",
        ]
        for pat in patterns:
            m = re.search(pat, body)
            if m:
                section = m.group(0)
                # Verify this is substantive content (not just TOC page numbers)
                if len(section) > 200 and re.search(r'\b[a-z]{4,}\b', section):
                    return section

        # Fallback: find any substantive "Legal Proceedings" section
        for m in re.finditer(r"(?i)legal\s+proceedings?\s*", body):
            start = m.start()
            # Skip if it looks like TOC (just digits after)
            after = body[start:start+200]
            if re.match(r'^.{0,50}\d{1,3}\s*$', after) and len(after.strip()) < 20:
                continue
            # Take the next 3000 chars as the legal section
            section = body[start:start+5000]
            if len(section) > 200:
                end = re.search(r"(?=item\s+\d|PART\s+II|$)", section)
                if end:
                    section = section[:end.start()]
                return section.strip()

        return None

    @staticmethod
    def _extract_dates(text: str) -> list:
        """Extract all dates from a text block."""
        import re
        from datetime import datetime

        dates = []
        pattern1 = (
            r"(?i)(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+\d{1,2},?\s+\d{4}"
        )
        for m in re.finditer(pattern1, text):
            try:
                dt = datetime.strptime(m.group(0).replace(",", "").strip(), "%B %d %Y")
                dates.append(dt)
            except ValueError:
                pass

        pattern2 = r"\d{4}-\d{2}-\d{2}"
        for m in re.finditer(pattern2, text):
            try:
                dt = datetime.strptime(m.group(0), "%Y-%m-%d")
                dates.append(dt)
            except ValueError:
                pass

        pattern3 = r"\d{2}/\d{2}/\d{4}"
        for m in re.finditer(pattern3, text):
            try:
                dt = datetime.strptime(m.group(0), "%m/%d/%Y")
                dates.append(dt)
            except ValueError:
                try:
                    dt = datetime.strptime(m.group(0), "%d/%m/%Y")
                    dates.append(dt)
                except ValueError:
                    pass

        return dates

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
            resp = self._sync_client.get(url.format(ticker), headers={"User-Agent": "NexusAgent/1.0"})
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
