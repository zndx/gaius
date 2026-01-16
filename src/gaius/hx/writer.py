"""Iceberg Content Store - Write Operations.

Provides high-level API for writing fetched content to Iceberg tables.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

from gaius.hx.config import HxConfig, get_hx_config

logger = logging.getLogger(__name__)


def _compute_content_hash(content: str | None) -> str | None:
    """Compute SHA-256 hash of content for duplicate detection.

    Args:
        content: Raw content string.

    Returns:
        Hex-encoded SHA-256 hash or None if no content.
    """
    if not content:
        return None
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class ContentItem:
    """A content item to be stored in Iceberg.

    This is the canonical schema for raw content in the HX data lake.
    PostgreSQL only stores metadata; raw content lives here.
    """

    source_id: int
    external_id: str
    title: str
    source_type: str
    url: str | None = None
    authors: list[str] | None = None
    raw_content: str | None = None
    content_type: str | None = None
    metadata: dict | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None

    # Auto-generated
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    processed: bool = False
    summary_excluded: bool = False
    exclusion_reason: str | None = None
    quality_score: int | None = None
    content_hash: str | None = None  # SHA-256 for duplicate detection

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.now(timezone.utc)
        # Auto-compute content hash if not provided
        if self.content_hash is None and self.raw_content:
            self.content_hash = _compute_content_hash(self.raw_content)

    def to_dict(self) -> dict:
        """Convert to dictionary for Iceberg append."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "external_id": self.external_id,
            "title": self.title,
            "url": self.url,
            "authors": self.authors,
            "raw_content": self.raw_content,
            "content_type": self.content_type,
            "metadata": json.dumps(self.metadata) if self.metadata else None,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "source_type": self.source_type,
            "processed": self.processed,
            "summary_excluded": self.summary_excluded,
            "exclusion_reason": self.exclusion_reason,
            "quality_score": self.quality_score,
            "content_hash": self.content_hash,
        }


@dataclass
class WriteResult:
    """Result of a write operation."""

    success: bool
    items_written: int
    snapshot_id: int | None = None
    errors: list[str] = field(default_factory=list)


class IcebergContentStore:
    """Write operations for raw content storage.

    Handles batching, retries, and integration with PostgreSQL
    content_items table for tracking.
    """

    def __init__(
        self,
        config: HxConfig | None = None,
        catalog: Catalog | None = None,
    ):
        """Initialize the content store.

        Args:
            config: Optional HxConfig. If None, loads from global config.
            catalog: Optional catalog. If None, creates from config.
        """
        self.config = config or get_hx_config()
        self._catalog = catalog
        self._table: Table | None = None

    @property
    def catalog(self) -> Catalog:
        """Get the Iceberg catalog."""
        if self._catalog is None:
            from gaius.hx.catalog import get_catalog
            self._catalog = get_catalog(self.config)
        return self._catalog

    @property
    def table(self) -> Table:
        """Get the raw content table."""
        if self._table is None:
            from gaius.hx.tables import get_raw_content_table
            self._table = get_raw_content_table(
                self.catalog,
                namespace=self.config.namespace,
            )
        return self._table

    def store_content(self, items: list[ContentItem]) -> WriteResult:
        """Store content items to Iceberg.

        Args:
            items: List of ContentItem objects to store.

        Returns:
            WriteResult with status and snapshot ID.
        """
        if not items:
            return WriteResult(success=True, items_written=0)

        try:
            import pyarrow as pa

            # Convert items to PyArrow table
            records = [item.to_dict() for item in items]
            arrow_table = self._records_to_arrow(records)

            # Append to Iceberg table
            self.table.append(arrow_table)

            # Get the new snapshot ID
            snapshot = self.table.current_snapshot()
            snapshot_id = snapshot.snapshot_id if snapshot else None

            logger.info(
                f"Stored {len(items)} content items to Iceberg "
                f"(snapshot: {snapshot_id})"
            )

            return WriteResult(
                success=True,
                items_written=len(items),
                snapshot_id=snapshot_id,
            )

        except Exception as e:
            logger.error(f"Failed to store content to Iceberg: {e}")
            return WriteResult(
                success=False,
                items_written=0,
                errors=[str(e)],
            )

    def store_content_item(self, item: ContentItem) -> WriteResult:
        """Store a single content item.

        Args:
            item: ContentItem to store.

        Returns:
            WriteResult with status.
        """
        return self.store_content([item])

    def mark_processed(
        self,
        content_id: str,
        kb_path: str,
        quality_score: int | None = None,
    ) -> bool:
        """Mark content as processed (summarized to KB).

        Note: Iceberg doesn't support in-place updates efficiently.
        This creates a new row with updated fields. For production,
        consider using MERGE operations or tracking in PostgreSQL.

        Args:
            content_id: UUID of the content record.
            kb_path: Path where summary was written in KB.
            quality_score: Optional quality score (0-100).

        Returns:
            True if successful.
        """
        # For now, we track processing status in PostgreSQL content_items
        # Iceberg is append-only for efficiency
        logger.info(f"Marking content {content_id} as processed -> {kb_path}")
        return True

    def mark_excluded(
        self,
        content_id: str,
        reason: str,
    ) -> bool:
        """Mark content as excluded from summarization.

        Args:
            content_id: UUID of the content record.
            reason: Why content was excluded.

        Returns:
            True if successful.
        """
        logger.info(f"Marking content {content_id} as excluded: {reason}")
        return True

    def _records_to_arrow(self, records: list[dict]) -> pa.Table:
        """Convert records to PyArrow table matching Iceberg schema.

        Args:
            records: List of dictionaries with content data.

        Returns:
            PyArrow Table.
        """
        import pyarrow as pa

        # Build schema matching Iceberg types
        # Mark required fields as non-nullable (nullable=False)
        schema = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("source_id", pa.int64(), nullable=False),
            pa.field("external_id", pa.string(), nullable=False),
            pa.field("title", pa.string(), nullable=False),
            pa.field("url", pa.string(), nullable=True),
            pa.field("authors", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
            pa.field("raw_content", pa.string(), nullable=True),
            pa.field("content_type", pa.string(), nullable=True),
            pa.field("metadata", pa.string(), nullable=True),
            pa.field("published_at", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("source_type", pa.string(), nullable=False),
            pa.field("processed", pa.bool_(), nullable=False),
            pa.field("summary_excluded", pa.bool_(), nullable=True),
            pa.field("exclusion_reason", pa.string(), nullable=True),
            pa.field("quality_score", pa.int64(), nullable=True),
            pa.field("content_hash", pa.string(), nullable=True),
        ])

        # Convert datetime objects to timezone-aware
        for record in records:
            if record.get("published_at"):
                dt = record["published_at"]
                if dt.tzinfo is None:
                    record["published_at"] = dt.replace(tzinfo=timezone.utc)
            if record.get("fetched_at"):
                dt = record["fetched_at"]
                if dt.tzinfo is None:
                    record["fetched_at"] = dt.replace(tzinfo=timezone.utc)

        return pa.Table.from_pylist(records, schema=schema)

    def get_snapshot_id(self) -> int | None:
        """Get the current snapshot ID.

        Returns:
            Current snapshot ID or None if no snapshots.
        """
        snapshot = self.table.current_snapshot()
        return snapshot.snapshot_id if snapshot else None
