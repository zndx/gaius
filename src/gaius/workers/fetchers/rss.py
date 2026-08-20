"""Generic RSS/Atom fetcher.

Handles standard RSS 2.0 and Atom feeds using feedparser.
Used for legiblenews, blog feeds, etc.
"""

import hashlib
from datetime import datetime
from time import mktime

import feedparser

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


@register_fetcher(SourceType.RSS)
class RSSFetcher(BaseFetcher):
    """Fetcher for RSS/Atom feeds."""

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch items from an RSS/Atom feed.

        Source config options:
            feed_url: str - Direct feed URL (default: base_url + "/feed")
            max_items: int - Maximum items to fetch (default: 50)
            include_content: bool - Include full content if available (default: True)
        """
        config = source.config
        feed_url = config.get("feed_url", f"{source.base_url}/feed")
        max_items = config.get("max_items", 50)
        include_content = config.get("include_content", True)

        try:
            items = await self._fetch_feed(
                feed_url=feed_url,
                max_items=max_items,
                include_content=include_content,
                source=source,
            )
            return FetchResult(
                items=items,
                metadata={
                    "feed_url": feed_url,
                    "max_items": max_items,
                    "actual_count": len(items),
                },
            )
        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={"feed_url": feed_url},
            )

    async def _fetch_feed(
        self,
        feed_url: str,
        max_items: int,
        include_content: bool,
        source: FeedSource,
    ) -> list[ContentItem]:
        """Fetch and parse RSS/Atom feed."""
        response = await self.fetch_url(feed_url)
        content = response.text

        # Parse with feedparser
        feed = feedparser.parse(content)

        items = []
        for entry in feed.entries[:max_items]:
            item = self._parse_entry(entry, source, include_content)
            if item:
                items.append(item)

        return items

    def _parse_entry(
        self,
        entry: dict,
        source: FeedSource,
        include_content: bool,
    ) -> ContentItem | None:
        """Parse a feedparser entry into a ContentItem."""
        try:
            # Get entry URL or ID
            url = entry.get("link", entry.get("id", ""))
            if not url:
                return None

            # Generate external ID from URL
            external_id = self._generate_id(url)

            # Get title
            title = entry.get("title", "Untitled")
            if not title:
                return None

            # Get authors
            authors = []
            if "author" in entry:
                authors.append(entry["author"])
            elif "authors" in entry:
                for author in entry["authors"]:
                    name = author.get("name", str(author))
                    if name:
                        authors.append(name)

            # Get summary/description
            summary = None
            if "summary" in entry:
                summary = self._clean_html(entry["summary"])
            elif "description" in entry:
                summary = self._clean_html(entry["description"])

            # Get full content if requested
            content = None
            content_type = "text/plain"
            if include_content and "content" in entry:
                from gaius.ingest.htmlplain import to_plain_text

                for content_item in entry["content"]:
                    if content_item.get("type", "").startswith("text/html"):
                        content = to_plain_text(content_item.get("value", ""))
                        content_type = "text/markdown"
                        break
                    elif content_item.get("type", "").startswith("text/"):
                        content = to_plain_text(content_item.get("value", ""))
                        content_type = "text/plain"

            # Parse published date
            published_at = None
            if "published_parsed" in entry and entry["published_parsed"]:
                try:
                    published_at = datetime.fromtimestamp(
                        mktime(entry["published_parsed"])
                    )
                except (ValueError, OverflowError):
                    pass
            elif "updated_parsed" in entry and entry["updated_parsed"]:
                try:
                    published_at = datetime.fromtimestamp(
                        mktime(entry["updated_parsed"])
                    )
                except (ValueError, OverflowError):
                    pass

            # Extract tags/categories
            tags = []
            for tag in entry.get("tags", []):
                term = tag.get("term", "")
                if term:
                    tags.append(term)

            return self.create_item(
                source=source,
                external_id=external_id,
                title=title.strip(),
                url=url,
                authors=authors,
                summary=summary,
                content=content,
                content_type=content_type,
                published_at=published_at,
                metadata={
                    "tags": tags,
                    "feed_source": source.name,
                },
            )
        except Exception:
            return None

    def _generate_id(self, url: str) -> str:
        """Generate a stable ID from URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _clean_html(self, html: str) -> str:
        from gaius.ingest.htmlplain import to_plain_text

        return to_plain_text(html)
