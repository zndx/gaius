"""Brave Search API client.

Usage:
    search = BraveSearch(api_key="...")
    results = await search.search("query")

    # For KB population
    structured = await search.search_for_kb("topic", domain="pension")
"""

from dataclasses import dataclass
import httpx


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    published: str | None = None


class BraveSearch:
    """Brave Search API client.

    API docs: https://api.search.brave.com/app/documentation
    """

    BASE_URL = "https://api.search.brave.com/res/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

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

        response = await self._client.get(
            f"{self.BASE_URL}/web/search",
            params=params,
        )
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
