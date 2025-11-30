"""Source-specific fetchers.

Each fetcher implements the BaseFetcher interface for a specific source type.
Import all fetchers here to ensure they're registered with the registry.
"""

from gaius.workers.fetchers.arxiv import ArxivFetcher
from gaius.workers.fetchers.biorxiv import BiorxivFetcher
from gaius.workers.fetchers.brave import BraveFetcher
from gaius.workers.fetchers.docs import DocsFetcher
from gaius.workers.fetchers.philevents import PhilEventsFetcher
from gaius.workers.fetchers.rss import RSSFetcher

__all__ = [
    "ArxivFetcher",
    "BiorxivFetcher",
    "BraveFetcher",
    "DocsFetcher",
    "PhilEventsFetcher",
    "RSSFetcher",
]
