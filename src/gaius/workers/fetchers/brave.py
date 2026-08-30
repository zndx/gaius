"""Brave Search fetcher.

Fetches content via Brave Search API for sources without RSS feeds.
Brave explicitly permits storing and using search results in AI pipelines.

Usage in feed_sources config:
    {
        "query": "site:example.com",           # Base search query
        "topics": ["topic1", "topic2"],        # Optional: search per topic
        "freshness": "pw",                     # Optional: pd/pw/pm/py
        "max_results": 20                      # Results per search
    }
"""

import hashlib
import os
from datetime import datetime

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


@register_fetcher(SourceType.BRAVE)
class BraveFetcher(BaseFetcher):
    """Fetcher using Brave Search API for RSS-less sources."""

    def __init__(self, config, http_client):
        super().__init__(config, http_client)
        self._search_client = None

    def _get_search_client(self):
        """Lazy-load the Brave search client."""
        if self._search_client is None:
            api_key = os.getenv("BRAVE_API_KEY")
            if not api_key:
                raise ValueError("BRAVE_API_KEY environment variable required")

            from gaius.search.brave import BraveSearch

            self._search_client = BraveSearch(api_key)
        return self._search_client

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch content via Brave Search.

        Source config options:
            query: str - Base search query (e.g., "site:example.com")
            topics: list[str] - Optional topics to search (creates multiple queries)
            freshness: str - Recency filter (pd=day, pw=week, pm=month, py=year)
            max_results: int - Maximum results per query (default: 10)
        """
        config = source.config
        base_query = config.get("query", f"site:{source.base_url.replace('https://', '').replace('http://', '')}")
        topics = config.get("topics", [])
        freshness = config.get("freshness", "pw")  # Default: past week
        max_results = config.get("max_results", 10)

        try:
            search = self._get_search_client()
            all_items = []
            seen_urls = set()

            # If topics provided, search for each
            queries = []
            if topics:
                for topic in topics:
                    queries.append(f"{base_query} {topic}")
            else:
                queries.append(base_query)

            for query in queries:
                results = await search.search(
                    query=query,
                    count=max_results,
                    freshness=freshness,
                )

                for result in results:
                    # Skip duplicates
                    if result.url in seen_urls:
                        continue
                    seen_urls.add(result.url)

                    item = self._parse_result(result, source, query)
                    if item:
                        all_items.append(item)

            return FetchResult(
                items=all_items,
                metadata={
                    "queries": queries,
                    "freshness": freshness,
                    "actual_count": len(all_items),
                },
            )

        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={"query": base_query},
            )

    def _parse_result(
        self, result, source: FeedSource, query: str
    ) -> ContentItem | None:
        """Parse a Brave search result into a ContentItem."""
        try:
            # Generate stable external_id from URL
            url_hash = hashlib.sha256(result.url.encode()).hexdigest()[:16]

            # Parse published date if available
            published_at = None
            if result.published:
                # Brave returns relative dates like "2 days ago"
                # Store as metadata, use current time for sorting
                published_at = datetime.now()

            return self.create_item(
                source=source,
                external_id=url_hash,
                title=result.title,
                url=result.url,
                summary=result.snippet,
                content_type="text/html",
                published_at=published_at,
                metadata={
                    "brave_age": result.published,
                    "search_query": query,
                    "source_domain": source.base_url,
                },
            )
        except Exception:
            return None
