"""arXiv fetcher.

Fetches papers from arXiv using their API (export.arxiv.org/api/query).
The API returns Atom XML which we parse with feedparser.

arXiv API docs: https://info.arxiv.org/help/api/index.html
"""

import re
from datetime import datetime
from urllib.parse import urlencode

import feedparser

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


@register_fetcher(SourceType.ARXIV)
class ArxivFetcher(BaseFetcher):
    """Fetcher for arXiv papers via their API."""

    # arXiv API endpoint (HTTPS)
    API_URL = "https://export.arxiv.org/api/query"

    # Rate limit: 1 request per 3 seconds (arXiv policy)
    RATE_LIMIT_DELAY = 3.0

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch papers from arXiv.

        Source config options:
            categories: list[str] - arXiv categories (e.g., ["cs.DC", "cs.DB"])
            max_results: int - Maximum papers to fetch (default: 100)
            sort_by: str - Sort field (default: "submittedDate")
            sort_order: str - Sort order (default: "descending")
        """
        config = source.config
        categories = config.get("categories", ["cs.DC"])
        max_results = config.get("max_results", 100)
        sort_by = config.get("sort_by", "submittedDate")
        sort_order = config.get("sort_order", "descending")

        try:
            items = await self._fetch_papers(
                categories=categories,
                max_results=max_results,
                sort_by=sort_by,
                sort_order=sort_order,
                source=source,
            )
            return FetchResult(
                items=items,
                metadata={
                    "categories": categories,
                    "max_results": max_results,
                    "actual_count": len(items),
                },
            )
        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={"categories": categories},
            )

    async def _fetch_papers(
        self,
        categories: list[str],
        max_results: int,
        sort_by: str,
        sort_order: str,
        source: FeedSource,
    ) -> list[ContentItem]:
        """Fetch papers from arXiv API."""
        # Build search query for categories
        # Format: cat:cs.DC OR cat:cs.DB
        cat_query = " OR ".join(f"cat:{cat}" for cat in categories)

        params = {
            "search_query": cat_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        url = f"{self.API_URL}?{urlencode(params)}"

        # Fetch the feed
        response = await self.fetch_url(url)
        content = response.text

        # Parse with feedparser
        feed = feedparser.parse(content)

        items = []
        for entry in feed.entries:
            item = self._parse_entry(entry, source)
            if item:
                items.append(item)

        return items

    def _parse_entry(self, entry: dict, source: FeedSource) -> ContentItem | None:
        """Parse a feedparser entry into a ContentItem."""
        try:
            # Extract arXiv ID from the entry ID URL
            # Format: http://arxiv.org/abs/2311.12345v1
            arxiv_id = self._extract_arxiv_id(entry.get("id", ""))
            if not arxiv_id:
                return None

            # Extract authors
            authors = []
            for author in entry.get("authors", []):
                name = author.get("name", "")
                if name:
                    authors.append(name)

            # Extract categories
            categories = []
            for tag in entry.get("tags", []):
                term = tag.get("term", "")
                if term:
                    categories.append(term)

            # Parse published date
            published_at = None
            published_str = entry.get("published", "")
            if published_str:
                try:
                    # arXiv uses ISO format: 2023-11-21T00:00:00Z
                    published_at = datetime.fromisoformat(
                        published_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Get PDF URL
            pdf_url = None
            for link in entry.get("links", []):
                if link.get("type") == "application/pdf":
                    pdf_url = link.get("href")
                    break

            return self.create_item(
                source=source,
                external_id=arxiv_id,
                title=entry.get("title", "").replace("\n", " ").strip(),
                url=entry.get("link", f"https://arxiv.org/abs/{arxiv_id}"),
                authors=authors,
                summary=entry.get("summary", "").strip(),
                content_type="text/plain",
                published_at=published_at,
                metadata={
                    "arxiv_id": arxiv_id,
                    "categories": categories,
                    "primary_category": categories[0] if categories else None,
                    "pdf_url": pdf_url,
                    "comment": entry.get("arxiv_comment", ""),
                    "journal_ref": entry.get("arxiv_journal_ref", ""),
                    "doi": entry.get("arxiv_doi", ""),
                },
            )
        except Exception:
            return None

    def _extract_arxiv_id(self, url: str) -> str | None:
        """Extract arXiv ID from URL or ID string.

        Examples:
            http://arxiv.org/abs/2311.12345v1 -> 2311.12345
            http://arxiv.org/abs/cs/0601001v1 -> cs/0601001
        """
        # New-style IDs: YYMM.NNNNN
        match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url)
        if match:
            return match.group(1)

        # Old-style IDs: archive/YYMMNNN
        match = re.search(r"([a-z-]+/\d{7})(v\d+)?", url)
        if match:
            return match.group(1)

        return None
