"""bioRxiv fetcher.

Fetches preprints from bioRxiv using their API (api.biorxiv.org).
API docs: https://api.biorxiv.org/

The API returns JSON with paginated results (100 per page).
We can fetch by date range or use RSS feeds for collections.

Usage in feed_sources config:
    {
        "collection": "synthetic-biology",     # Subject collection
        "days_back": 30,                       # How far back to fetch
        "max_results": 100                     # Max papers to fetch
    }
"""

from datetime import datetime, timedelta

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


@register_fetcher(SourceType.BIORXIV)
class BiorxivFetcher(BaseFetcher):
    """Fetcher for bioRxiv preprints via their API."""

    # bioRxiv API endpoint
    API_URL = "https://api.biorxiv.org/details/biorxiv"

    # Map collection names to API subject codes
    COLLECTION_MAP = {
        "synthetic-biology": "synthetic_biology",
        "bioinformatics": "bioinformatics",
        "genetics": "genetics",
        "genomics": "genomics",
        "neuroscience": "neuroscience",
        "systems-biology": "systems_biology",
    }

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch preprints from bioRxiv.

        Source config options:
            collection: str - Subject collection (e.g., "synthetic-biology")
            days_back: int - How many days back to fetch (default: 30)
            max_results: int - Maximum papers to fetch (default: 100)
        """
        config = source.config
        collection = config.get("collection", "synthetic-biology")
        days_back = config.get("days_back", 30)
        max_results = config.get("max_results", 100)

        try:
            items = await self._fetch_papers(
                collection=collection,
                days_back=days_back,
                max_results=max_results,
                source=source,
            )
            return FetchResult(
                items=items,
                metadata={
                    "collection": collection,
                    "days_back": days_back,
                    "actual_count": len(items),
                },
            )
        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={"collection": collection},
            )

    async def _fetch_papers(
        self,
        collection: str,
        days_back: int,
        max_results: int,
        source: FeedSource,
    ) -> list[ContentItem]:
        """Fetch papers from bioRxiv API."""
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # Build URL - fetch all papers in date range
        url = f"{self.API_URL}/{start_str}/{end_str}/0/json"

        # Fetch the data
        response = await self.fetch_url(url)
        data = response.json()

        items = []

        # Get category keywords to filter by (if any)
        collection_filter = self.COLLECTION_MAP.get(collection, collection)
        filter_keywords = collection_filter.replace("_", " ").lower().split() if collection_filter else []

        for paper in data.get("collection", []):
            # Filter by category keywords if specified
            category = paper.get("category", "").lower()
            title = paper.get("title", "").lower()
            abstract = paper.get("abstract", "").lower()

            # Check if any filter keyword appears in category, title or abstract
            if filter_keywords:
                text = f"{category} {title} {abstract}"
                if not any(kw in text for kw in filter_keywords):
                    continue

            item = self._parse_paper(paper, source)
            if item:
                items.append(item)

            if len(items) >= max_results:
                break

        return items

    def _parse_paper(self, paper: dict, source: FeedSource) -> ContentItem | None:
        """Parse a bioRxiv paper into a ContentItem."""
        try:
            doi = paper.get("doi", "")
            if not doi:
                return None

            # Parse date
            published_at = None
            date_str = paper.get("date", "")
            if date_str:
                try:
                    published_at = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    pass

            # Extract authors (bioRxiv returns comma-separated string)
            authors_str = paper.get("authors", "")
            authors = [a.strip() for a in authors_str.split(";") if a.strip()]

            return self.create_item(
                source=source,
                external_id=doi,
                title=paper.get("title", ""),
                url=f"https://www.biorxiv.org/content/{doi}",
                authors=authors,
                summary=paper.get("abstract", ""),
                content_type="text/plain",
                published_at=published_at,
                metadata={
                    "doi": doi,
                    "category": paper.get("category", ""),
                    "version": paper.get("version", "1"),
                    "type": paper.get("type", "new"),
                    "jatsxml": paper.get("jatsxml", ""),
                    "license": paper.get("license", ""),
                },
            )
        except Exception:
            return None
