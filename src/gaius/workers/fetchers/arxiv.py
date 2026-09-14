"""arXiv fetcher.

RSS-first via arxiv_client.discover_papers (rss.arxiv.org, cached).
Does not search export.arxiv.org unless RSS is empty.
"""

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


@register_fetcher(SourceType.ARXIV)
class ArxivFetcher(BaseFetcher):
    """Fetcher for arXiv papers via category RSS."""

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch papers from arXiv.

        Source config options:
            categories: list[str] - arXiv categories (e.g., ["cs.DC", "cs.DB"])
            max_results: int - Maximum papers to fetch (capped at 25)
        """
        from gaius.flows.article_curation.arxiv_client import cap_max_results

        config = source.config
        categories = config.get("categories", ["cs.DC"])
        max_results = cap_max_results(config.get("max_results", 25))

        try:
            items = await self._fetch_papers(
                categories=categories,
                max_results=max_results,
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
        source: FeedSource,
    ) -> list[ContentItem]:
        """RSS-first category listing. No search API unless RSS is empty."""
        from gaius.flows.article_curation.arxiv_client import discover_papers

        papers = await discover_papers(categories, keywords=[], max_results=max_results)
        items = []
        for paper in papers:
            item = self.create_item(
                source=source,
                external_id=paper.arxiv_id,
                title=paper.title,
                url=paper.url,
                authors=paper.authors,
                summary=paper.summary,
                content_type="text/plain",
                published_at=None,
                metadata={
                    "arxiv_id": paper.arxiv_id,
                    "categories": paper.categories or categories,
                    "published": paper.published,
                    "via": paper.via,
                },
            )
            items.append(item)
        return items
