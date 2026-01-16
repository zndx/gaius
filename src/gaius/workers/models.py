"""Data models for fetch workers.

These models map to the database schema defined in db/migrations/.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SourceType(Enum):
    """Feed source types matching the database enum."""

    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    RSS = "rss"
    API = "api"
    SCRAPER = "scraper"
    PHILPAPERS = "philpapers"
    PHILEVENTS = "philevents"  # Philosophy events and CFPs
    DOCS = "docs"
    BRAVE = "brave"  # Uses Brave Search API for RSS-less sources
    X_BOOKMARKS = "x_bookmarks"  # X (Twitter) bookmarks via OAuth 2.0
    HACKERNEWS = "hackernews"  # Hacker News front page and newcomments


class JobStatus(Enum):
    """Fetch job status values."""

    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class FeedSource:
    """Configuration for a feed source.

    Maps to: feed_sources table
    """

    id: int
    name: str
    source_type: SourceType
    base_url: str
    config: dict[str, Any] = field(default_factory=dict)
    fetch_interval_minutes: int = 60
    active: bool = True
    last_fetch_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "FeedSource":
        """Create from database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            source_type=SourceType(row["source_type"]),
            base_url=row["base_url"],
            config=row.get("config", {}),
            fetch_interval_minutes=row.get("fetch_interval_minutes", 60),
            active=row.get("active", True),
            last_fetch_at=row.get("last_fetch_at"),
        )


@dataclass
class FetchJob:
    """A scheduled or running fetch job.

    Maps to: fetch_jobs table
    """

    id: int
    source_id: int
    status: JobStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    items_fetched: int = 0
    items_new: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Populated after loading
    source: FeedSource | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "FetchJob":
        """Create from database row."""
        return cls(
            id=row["id"],
            source_id=row["source_id"],
            status=JobStatus(row["status"]),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            items_fetched=row.get("items_fetched", 0),
            items_new=row.get("items_new", 0),
            error_message=row.get("error_message"),
            metadata=row.get("metadata", {}),
        )


@dataclass
class ContentItem:
    """A fetched content item.

    Maps to: content_items table (metadata) + Iceberg raw.content (raw content)

    Architecture:
    - PostgreSQL stores metadata for fast queries (title, authors, URLs, timestamps)
    - Iceberg stores raw content for long-term storage (full text, abstracts)
    - iceberg_id links PostgreSQL metadata to Iceberg raw content
    """

    # Required fields
    title: str
    source_id: int

    # Optional identification
    id: int | None = None
    external_id: str | None = None  # arxiv ID, DOI, URL hash
    url: str | None = None

    # Content - raw content stored in Iceberg, only summary in PostgreSQL
    authors: list[str] = field(default_factory=list)
    summary: str | None = None  # Brief summary (stored in PostgreSQL)
    content: str | None = None  # Raw content (stored in Iceberg only, not PostgreSQL)
    content_type: str = "text/plain"

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    processed_at: datetime | None = None

    # KB integration
    kb_path: str | None = None  # Path in build/dev/ if written
    embedding_id: str | None = None  # Qdrant point ID

    # HX (Iceberg) integration
    iceberg_id: str | None = None  # UUID linking to raw.content in Iceberg
    iceberg_snapshot_id: int | None = None  # Iceberg snapshot for time-travel

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ContentItem":
        """Create from database row."""
        return cls(
            id=row.get("id"),
            source_id=row["source_id"],
            external_id=row.get("external_id"),
            url=row.get("url"),
            title=row["title"],
            authors=row.get("authors", []),
            summary=row.get("summary"),
            content=row.get("content"),  # May be None after migration
            content_type=row.get("content_type", "text/plain"),
            metadata=row.get("metadata", {}),
            published_at=row.get("published_at"),
            fetched_at=row.get("fetched_at"),
            processed_at=row.get("processed_at"),
            kb_path=row.get("kb_path"),
            embedding_id=row.get("embedding_id"),
            iceberg_id=row.get("iceberg_id"),
            iceberg_snapshot_id=row.get("iceberg_snapshot_id"),
        )


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    items: list[ContentItem] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if fetch was successful."""
        return self.error is None

    @property
    def count(self) -> int:
        """Number of items fetched."""
        return len(self.items)
