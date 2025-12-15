"""Brave Search API client.

Usage:
    search = BraveSearch(api_key="...")
    results = await search.search("query")

    # For KB population
    structured = await search.search_for_kb("topic", domain="pension")

Exchanges are captured to Iceberg for training data (when enabled).
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, asdict

import httpx

logger = logging.getLogger(__name__)


def _is_exchange_capture_enabled() -> bool:
    """Check if exchange capture is enabled."""
    env_val = os.environ.get("GAIUS_HX_CAPTURE_EXCHANGES", "true")
    return env_val.lower() in ("1", "true", "yes")


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    published: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


class BraveSearch:
    """Brave Search API client.

    API docs: https://api.search.brave.com/app/documentation
    """

    BASE_URL = "https://api.search.brave.com/res/v1"

    def __init__(self, api_key: str, capture_exchanges: bool | None = None):
        """Initialize Brave search client.

        Args:
            api_key: Brave API key.
            capture_exchanges: Whether to capture exchanges to Iceberg.
                               If None, reads from GAIUS_HX_CAPTURE_EXCHANGES env.
        """
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

        # Exchange capture (lazy initialization)
        if capture_exchanges is None:
            capture_exchanges = _is_exchange_capture_enabled()
        self._capture_enabled = capture_exchanges
        self._exchange_capture = None

    def _get_exchange_capture(self):
        """Get or create exchange capture instance (lazy initialization)."""
        if not self._capture_enabled:
            return None
        if self._exchange_capture is None:
            try:
                from gaius.hx.exchange import get_exchange_capture
                self._exchange_capture = get_exchange_capture()
            except Exception as e:
                logger.warning(f"Failed to initialize exchange capture: {e}")
                self._capture_enabled = False
                return None
        return self._exchange_capture

    async def search(
        self,
        query: str,
        count: int = 10,
        country: str = "us",
        freshness: str | None = None,
    ) -> list[SearchResult]:
        """Execute a web search.

        Args:
            query: Search query
            count: Number of results (max 20)
            country: Country code for localization
            freshness: Recency filter (pd=past day, pw=past week, pm=past month, py=past year)

        Returns:
            List of SearchResult objects
        """
        params = {
            "q": query,
            "count": min(count, 20),
            "country": country,
        }
        if freshness:
            params["freshness"] = freshness

        start_time = time.time()
        response = await self._client.get(
            f"{self.BASE_URL}/web/search",
            params=params,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    published=item.get("age"),
                )
            )

        # Capture exchange to Iceberg (fire-and-forget)
        if results:  # Only capture successful searches with results
            capture = self._get_exchange_capture()
            if capture:
                try:
                    from gaius.hx.exchange import ExchangeRecord
                    record = ExchangeRecord(
                        provider="brave",
                        request_messages=[{"role": "user", "content": query}],
                        request_model="brave-search-v1",
                        request_params={
                            "count": count,
                            "country": country,
                            "freshness": freshness,
                        },
                        response_content=json.dumps([r.to_dict() for r in results]),
                        response_model="brave-search-v1",
                        input_tokens=0,  # Not applicable for search
                        output_tokens=len(results),  # Use result count as proxy
                        latency_ms=latency_ms,
                        source_context={"provider": "brave", "result_count": len(results)},
                    )
                    asyncio.create_task(capture.capture(record))
                except Exception as e:
                    logger.debug(f"Failed to capture Brave search exchange: {e}")

        return results

    async def search_for_kb(
        self,
        topic: str,
        domain: str,
        count: int = 5,
    ) -> list[dict]:
        """Search optimized for KB population.

        Returns structured data suitable for creating KB entries.

        Args:
            topic: Topic to research
            domain: Domain context (e.g., "Apache Kudu", "pension")
            count: Number of results

        Returns:
            List of dicts with source, title, summary, domain, query keys
        """
        # Build a domain-aware query
        full_query = f"{domain}: {topic}"
        results = await self.search(full_query, count=count)

        return [
            {
                "source": r.url,
                "title": r.title,
                "summary": r.snippet,
                "domain": domain,
                "query": topic,
                "published": r.published,
            }
            for r in results
        ]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
