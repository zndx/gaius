"""Documentation fetcher.

Fetches documentation pages from sitemap.xml files.
Useful for product documentation sites like docs.cloudera.com.

Usage in feed_sources config:
    {
        "sitemap_url": "https://docs.example.com/sitemap.xml",
        "priority_paths": ["/product/", "/guide/"],
        "exclude_patterns": ["/_archive/", "/old/"],
        "max_results": 50
    }
"""

import hashlib
import re
from datetime import datetime
from xml.etree import ElementTree

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


@register_fetcher(SourceType.DOCS)
class DocsFetcher(BaseFetcher):
    """Fetcher for documentation sites via sitemap.xml."""

    # XML namespaces used in sitemaps
    SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch documentation pages from sitemap.

        Source config options:
            sitemap_url: str - URL to sitemap.xml
            priority_paths: list[str] - URL path prefixes to prioritize
            exclude_patterns: list[str] - URL patterns to exclude
            max_results: int - Maximum pages to fetch (default: 50)
        """
        config = source.config
        sitemap_url = config.get("sitemap_url", f"{source.base_url}/sitemap.xml")
        priority_paths = config.get("priority_paths", [])
        exclude_patterns = config.get("exclude_patterns", [])
        max_results = config.get("max_results", 50)

        try:
            items = await self._fetch_from_sitemap(
                sitemap_url=sitemap_url,
                priority_paths=priority_paths,
                exclude_patterns=exclude_patterns,
                max_results=max_results,
                source=source,
            )
            return FetchResult(
                items=items,
                metadata={
                    "sitemap_url": sitemap_url,
                    "actual_count": len(items),
                },
            )
        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={"sitemap_url": sitemap_url},
            )

    async def _fetch_from_sitemap(
        self,
        sitemap_url: str,
        priority_paths: list[str],
        exclude_patterns: list[str],
        max_results: int,
        source: FeedSource,
    ) -> list[ContentItem]:
        """Fetch and parse sitemap, returning doc pages as items."""
        response = await self.fetch_url(sitemap_url)
        content = response.text

        # Parse XML
        root = ElementTree.fromstring(content)

        # Handle sitemap index (contains references to other sitemaps)
        sitemap_refs = root.findall(".//sm:sitemap/sm:loc", self.SITEMAP_NS)
        if sitemap_refs:
            # This is a sitemap index - fetch first sub-sitemap
            sub_sitemap_url = sitemap_refs[0].text
            response = await self.fetch_url(sub_sitemap_url)
            content = response.text
            root = ElementTree.fromstring(content)

        items = []
        urls = root.findall(".//sm:url", self.SITEMAP_NS)

        # Sort URLs - prioritize paths if specified
        def priority_score(url_elem):
            loc = url_elem.find("sm:loc", self.SITEMAP_NS)
            if loc is None:
                return 999
            url = loc.text or ""
            for i, path in enumerate(priority_paths):
                if path in url:
                    return i
            return len(priority_paths)

        urls.sort(key=priority_score)

        for url_elem in urls:
            loc_elem = url_elem.find("sm:loc", self.SITEMAP_NS)
            if loc_elem is None:
                continue

            url = loc_elem.text
            if not url:
                continue

            # Check exclude patterns
            if any(pattern in url for pattern in exclude_patterns):
                continue

            # Parse last modified date
            lastmod_elem = url_elem.find("sm:lastmod", self.SITEMAP_NS)
            lastmod = None
            if lastmod_elem is not None and lastmod_elem.text:
                try:
                    lastmod = datetime.fromisoformat(lastmod_elem.text.replace("Z", "+00:00"))
                except ValueError:
                    pass

            item = self._create_doc_item(url, lastmod, source)
            if item:
                items.append(item)

            if len(items) >= max_results:
                break

        return items

    def _create_doc_item(
        self, url: str, lastmod: datetime | None, source: FeedSource
    ) -> ContentItem | None:
        """Create a ContentItem from a sitemap URL."""
        try:
            # Generate external_id from URL
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]

            # Extract title from URL path
            path = url.replace(source.base_url, "").strip("/")
            title = path.split("/")[-1].replace("-", " ").replace("_", " ").title()
            if not title:
                title = "Documentation"

            return self.create_item(
                source=source,
                external_id=url_hash,
                title=title,
                url=url,
                content_type="text/html",
                published_at=lastmod,
                metadata={
                    "doc_path": path,
                    "last_modified": lastmod.isoformat() if lastmod else None,
                },
            )
        except Exception:
            return None
