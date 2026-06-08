"""
Free Web Search Fallback Mechanism for NEXUS.

Implements a zero-cost multi-provider routing sequence:
  1. DuckDuckGo Search Scraping (primary — keyless, unlimited)
  2. Tavily Free Tier (secondary — 1,000 free requests/month)
  3. SearXNG Local Engine (tertiary — self-hosted fallback)

All components use open packages with no premium features.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus


@dataclass
class SearchResult:
    """Unified search result across providers."""
    title: str
    url: str
    description: str
    provider: str  # "ddg", "tavily", "searxng"
    rank: int = 0
    score: float = 0.0


@dataclass
class SearchProviderStatus:
    name: str
    available: bool
    quota_remaining: Optional[int] = None
    error: Optional[str] = None


class WebSearchRouter:
    """
    Multi-provider web search with automatic fallback.

    Usage:
        router = WebSearchRouter()
        results = await router.search("AAPL stock analysis")
    """

    def __init__(
        self,
        tavily_api_key: Optional[str] = None,
        tavily_monthly_quota: int = 1000,
        searxng_url: Optional[str] = None,
    ):
        self.tavily_api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
        self.tavily_quota_total = tavily_monthly_quota
        self.tavily_quota_used = 0
        self.searxng_url = searxng_url or os.environ.get("SEARXNG_URL", "http://localhost:8080")

        # Track provider status
        self._provider_order = ["ddg", "tavily", "searxng"]
        self._last_used: dict[str, float] = {}

    def get_provider_status(self) -> list[SearchProviderStatus]:
        """Get availability status for all providers."""
        statuses = []
        for name in self._provider_order:
            if name == "ddg":
                statuses.append(SearchProviderStatus(name="ddg", available=True))
            elif name == "tavily":
                remaining = self.tavily_quota_total - self.tavily_quota_used
                statuses.append(SearchProviderStatus(
                    name="tavily",
                    available=bool(self.tavily_api_key) and remaining > 0,
                    quota_remaining=remaining,
                ))
            elif name == "searxng":
                statuses.append(SearchProviderStatus(name="searxng", available=True))
        return statuses

    async def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 15,
    ) -> list[SearchResult]:
        """
        Search across providers with automatic fallback.
        Default: DuckDuckGo first, then Tavily, then SearXNG.
        """
        providers = self._get_ordered_providers()

        for provider in providers:
            try:
                results = await self._search_provider(
                    provider, query, max_results, timeout
                )
                if results:
                    self._last_used[provider] = time.time()
                    return results
            except Exception:
                continue

        return []

    def _get_ordered_providers(self) -> list[str]:
        """Get providers in priority order, respecting quota limits."""
        ordered = []
        # Always try DDG first (unlimited)
        ordered.append("ddg")

        # Tavily only if API key is set and quota remains
        if self.tavily_api_key and self.tavily_quota_used < self.tavily_quota_total:
            ordered.append("tavily")

        # SearXNG as final fallback
        ordered.append("searxng")
        return ordered

    async def _search_provider(
        self,
        provider: str,
        query: str,
        max_results: int,
        timeout: int,
    ) -> list[SearchResult]:
        """Dispatch to the appropriate provider implementation."""
        if provider == "ddg":
            return await self._search_ddg(query, max_results, timeout)
        elif provider == "tavily":
            return await self._search_tavily(query, max_results, timeout)
        elif provider == "searxng":
            return await self._search_searxng(query, max_results, timeout)
        return []

    # ==================================================================
    # DuckDuckGo (keyless, free, unlimited)
    # ==================================================================

    async def _search_ddg(
        self, query: str, max_results: int, timeout: int
    ) -> list[SearchResult]:
        """
        DuckDuckGo HTML search scraping.
        Uses duckduckgo_search library or direct HTTP as fallback.
        """
        try:
            import warnings
            # Suppress rename warning (duckduckgo_search → ddgs)
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            from duckduckgo_search import DDGS
            warnings.filterwarnings("default", category=RuntimeWarning)
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
                return [
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", r.get("link", "")),
                        description=r.get("body", r.get("snippet", "")),
                        provider="ddg",
                        rank=i + 1,
                    )
                    for i, r in enumerate(raw)
                ]
        except ImportError:
            pass

        # Fallback: direct HTTP to DuckDuckGo HTML
        try:
            import httpx
            encoded = quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            resp = httpx.get(url, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NexusBot/1.0)"
            })
            if resp.status_code != 200:
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for i, result in enumerate(soup.select(".result")[:max_results]):
                title_el = result.select_one(".result__title a")
                snippet_el = result.select_one(".result__snippet")
                link_el = result.select_one(".result__url")

                results.append(SearchResult(
                    title=title_el.get_text(strip=True) if title_el else "",
                    url=link_el.get_text(strip=True) if link_el else "",
                    description=snippet_el.get_text(strip=True) if snippet_el else "",
                    provider="ddg",
                    rank=i + 1,
                ))
            return results
        except Exception:
            return []

    # ==================================================================
    # Tavily (free tier — 1,000 requests/month)
    # ==================================================================

    async def _search_tavily(
        self, query: str, max_results: int, timeout: int
    ) -> list[SearchResult]:
        """Tavily Search API — free tier with 1,000 monthly requests."""
        if not self.tavily_api_key:
            return []

        try:
            import httpx
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return []

            self.tavily_quota_used += 1
            data = resp.json()
            raw = data.get("results", [])

            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    description=r.get("content", r.get("snippet", "")),
                    provider="tavily",
                    rank=i + 1,
                    score=r.get("score", 0.0),
                )
                for i, r in enumerate(raw[:max_results])
            ]
        except Exception:
            return []

    # ==================================================================
    # SearXNG (local engine — self-hosted, zero-cost)
    # ==================================================================

    async def _search_searxng(
        self, query: str, max_results: int, timeout: int
    ) -> list[SearchResult]:
        """SearXNG local instance — self-hosted search engine."""
        try:
            import httpx
            resp = httpx.get(
                f"{self.searxng_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            raw = data.get("results", [])

            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    description=r.get("content", r.get("snippet", "")),
                    provider="searxng",
                    rank=i + 1,
                    score=r.get("score", 0.0),
                )
                for i, r in enumerate(raw[:max_results])
            ]
        except Exception:
            return []


# Singleton router instance
_router: Optional[WebSearchRouter] = None


def get_search_router() -> WebSearchRouter:
    """Get or create the global search router."""
    global _router
    if _router is None:
        _router = WebSearchRouter()
    return _router


async def search_web(query: str, max_results: int = 5) -> list[SearchResult]:
    """Convenience function for web search with automatic fallback."""
    router = get_search_router()
    return await router.search(query, max_results)
