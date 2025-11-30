"""Base fetcher interface.

All source-specific fetchers inherit from BaseFetcher and implement
the fetch() method for their particular source type.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx

from gaius.workers.config import WorkerConfig
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType

if TYPE_CHECKING:
    from gaius.workers.db import Database


class BaseFetcher(ABC):
    """Abstract base class for content fetchers.

    Each fetcher handles a specific source type (arxiv, rss, etc.).
    """

    # Source type this fetcher handles
    source_type: SourceType

    def __init__(self, config: WorkerConfig, http_client: httpx.AsyncClient):
        """Initialize fetcher with config and shared HTTP client."""
        self.config = config
        self.http = http_client

    @abstractmethod
    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch content from the source.

        Args:
            source: The feed source configuration

        Returns:
            FetchResult with list of ContentItem or error
        """
        ...

    async def fetch_url(self, url: str, **kwargs) -> httpx.Response:
        """Fetch a URL with standard headers and error handling."""
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", self.config.user_agent)

        response = await self.http.get(
            url,
            headers=headers,
            timeout=self.config.http_timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def create_item(
        self,
        source: FeedSource,
        external_id: str,
        title: str,
        **kwargs,
    ) -> ContentItem:
        """Helper to create a ContentItem with source defaults."""
        return ContentItem(
            source_id=source.id,
            external_id=external_id,
            title=title,
            **kwargs,
        )


class FetcherRegistry:
    """Registry of fetcher classes by source type."""

    _fetchers: dict[SourceType, type[BaseFetcher]] = {}

    @classmethod
    def register(cls, source_type: SourceType):
        """Decorator to register a fetcher class."""
        def decorator(fetcher_cls: type[BaseFetcher]):
            cls._fetchers[source_type] = fetcher_cls
            fetcher_cls.source_type = source_type
            return fetcher_cls
        return decorator

    @classmethod
    def get(cls, source_type: SourceType) -> type[BaseFetcher] | None:
        """Get fetcher class for a source type."""
        return cls._fetchers.get(source_type)

    @classmethod
    def create(
        cls,
        source_type: SourceType,
        config: WorkerConfig,
        http_client: httpx.AsyncClient,
    ) -> BaseFetcher | None:
        """Create a fetcher instance for a source type."""
        fetcher_cls = cls.get(source_type)
        if fetcher_cls is None:
            return None
        return fetcher_cls(config, http_client)

    @classmethod
    def supported_types(cls) -> list[SourceType]:
        """List all supported source types."""
        return list(cls._fetchers.keys())


# Convenience decorator
register_fetcher = FetcherRegistry.register
