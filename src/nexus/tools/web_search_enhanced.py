"""
Enhanced web search for NEXUS — adds Exa and Perplexity to the routing chain.

Full routing sequence:
  1. DuckDuckGo (keyless, unlimited)
  2. Exa (free tier — AI-powered semantic search)
  3. Perplexity (free tier — AI-powered answers with citations)
  4. Tavily (free tier — 1000 req/month)
  5. SearXNG (local, self-hosted)
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .web_search import WebSearchRouter, SearchResult, get_search_router


class EnhancedWebSearchRouter(WebSearchRouter):
    """
    Extended web search router with Exa and Perplexity support.
    Falls back gracefully if API keys are not configured.
    """

    def __init__(
        self,
        tavily_api_key: Optional[str] = None,
        tavily_monthly_quota: int = 1000,
        searxng_url: Optional[str] = None,
        exa_api_key: Optional[str] = None,
        perplexity_api_key: Optional[str] = None,
    ):
        super().__init__(
            tavily_api_key=tavily_api_key,
            tavily_monthly_quota=tavily_monthly_quota,
            searxng_url=searxng_url,
        )
        self.exa_api_key = exa_api_key or os.environ.get("EXA_API_KEY", "")
        self.perplexity_api_key = perplexity_api_key or os.environ.get("PERPLEXITY_API_KEY", "")

        # Update provider order
        self._provider_order = ["ddg", "exa", "perplexity", "tavily", "searxng"]

    def _get_ordered_providers(self) -> list[str]:
        """Get providers in priority order, respecting quota limits and available keys."""
        ordered = []

        # Always try DDG first (unlimited, keyless)
        ordered.append("ddg")

        # Exa (free tier)
        if self.exa_api_key:
            ordered.append("exa")

        # Perplexity (free tier)
        if self.perplexity_api_key:
            ordered.append("perplexity")

        # Tavily (only if quota remains)
        if self.tavily_api_key and self.tavily_quota_used < self.tavily_quota_total:
            ordered.append("tavily")

        # SearXNG as final fallback
        ordered.append("searxng")

        return ordered

    async def _search_provider(
        self, provider: str, query: str, max_results: int, timeout: int
    ) -> list[SearchResult]:
        if provider == "exa":
            return await self._search_exa(query, max_results, timeout)
        elif provider == "perplexity":
            return await self._search_perplexity(query, max_results, timeout)
        else:
            return await super()._search_provider(provider, query, max_results, timeout)

    async def _search_exa(
        self, query: str, max_results: int, timeout: int
    ) -> list[SearchResult]:
        """Exa AI-powered semantic search."""
        if not self.exa_api_key:
            return []
        try:
            import httpx
            resp = httpx.post(
                "https://api.exa.ai/search",
                headers={
                    "x-api-key": self.exa_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "numResults": max_results,
                    "useAutoprompt": True,
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    description=r.get("text", r.get("snippet", ""))[:300],
                    provider="exa",
                    rank=i + 1,
                    score=r.get("score", 0.0),
                )
                for i, r in enumerate(data.get("results", []))
            ]
        except Exception:
            return []

    async def _search_perplexity(
        self, query: str, max_results: int, timeout: int
    ) -> list[SearchResult]:
        """Perplexity AI search — returns answers with citations."""
        if not self.perplexity_api_key:
            return []
        try:
            import httpx
            from .web_search import SearchResult
            resp = httpx.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.perplexity_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-sonar-small-128k-online",
                    "messages": [
                        {
                            "role": "system",
                            "content": "Be precise and concise. Return factual information with sources.",
                        },
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": 500,
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            citations = data.get("citations", [])

            results = []
            if content:
                # Use the Perplexity answer as the first result
                results.append(SearchResult(
                    title="Perplexity AI Answer",
                    url=citations[0] if citations else "",
                    description=content[:500],
                    provider="perplexity",
                    rank=1,
                ))
            # Add individual citations as additional results
            for i, url in enumerate(citations[1:max_results], 2):
                results.append(SearchResult(
                    title=f"Source {i}",
                    url=url,
                    description="",
                    provider="perplexity",
                    rank=i,
                ))
            return results
        except Exception:
            return []
