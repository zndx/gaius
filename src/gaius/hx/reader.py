"""Iceberg Content Reader - Query Operations.

Provides high-level API for reading content from Iceberg tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table
    import pyarrow as pa

from gaius.hx.config import HxConfig, get_hx_config
from gaius.hx.writer import ContentItem

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of a content query."""

    items: list[ContentItem]
    total_count: int
    snapshot_id: int | None = None
    query_time_ms: float = 0.0


class IcebergContentReader:
    """Read operations for raw content storage.

    Provides efficient queries for:
    - Unprocessed content (for summarization)
    - Content by source type
    - Time-range queries
    - Full-text search (via metadata)
    """

    def __init__(
        self,
        config: HxConfig | None = None,
        catalog: Catalog | None = None,
    ):
        """Initialize the content reader.

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

    def get_unprocessed(
        self,
        limit: int = 20,
        source_type: str | None = None,
    ) -> QueryResult:
        """Get unprocessed content for summarization.

        Args:
            limit: Maximum items to return.
            source_type: Optional filter by source type.

        Returns:
            QueryResult with unprocessed items.
        """
        import time

        start = time.time()

        # Build filter expression
        filters = ["processed == false", "summary_excluded == false"]
        if source_type:
            filters.append(f"source_type == '{source_type}'")

        filter_expr = " and ".join(filters)

        try:
            # Scan with filter and limit
            scan = self.table.scan(
                row_filter=filter_expr,
                limit=limit,
            )

            # Convert to items
            items = list(self._scan_to_items(scan))

            query_time = (time.time() - start) * 1000

            return QueryResult(
                items=items,
                total_count=len(items),
                snapshot_id=self._get_snapshot_id(),
                query_time_ms=query_time,
            )

        except Exception as e:
            logger.error(f"Failed to query unprocessed content: {e}")
            return QueryResult(items=[], total_count=0)

    def get_by_source(
        self,
        source_type: str,
        limit: int = 100,
        include_processed: bool = True,
    ) -> QueryResult:
        """Get content by source type.

        Args:
            source_type: Source type to filter by.
            limit: Maximum items to return.
            include_processed: Whether to include processed items.

        Returns:
            QueryResult with matching items.
        """
        import time

        start = time.time()

        filters = [f"source_type == '{source_type}'"]
        if not include_processed:
            filters.append("processed == false")

        filter_expr = " and ".join(filters)

        try:
            scan = self.table.scan(
                row_filter=filter_expr,
                limit=limit,
            )

            items = list(self._scan_to_items(scan))
            query_time = (time.time() - start) * 1000

            return QueryResult(
                items=items,
                total_count=len(items),
                snapshot_id=self._get_snapshot_id(),
                query_time_ms=query_time,
            )

        except Exception as e:
            logger.error(f"Failed to query content by source: {e}")
            return QueryResult(items=[], total_count=0)

    def get_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime | None = None,
        source_type: str | None = None,
        limit: int = 100,
    ) -> QueryResult:
        """Get content within a time range.

        Args:
            start_time: Start of time range.
            end_time: End of time range (default: now).
            source_type: Optional source type filter.
            limit: Maximum items to return.

        Returns:
            QueryResult with matching items.
        """
        import time

        query_start = time.time()

        if end_time is None:
            end_time = datetime.now(timezone.utc)

        # Ensure timezone-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        # Build filter - Iceberg uses ISO format
        start_str = start_time.isoformat()
        end_str = end_time.isoformat()

        filters = [
            f"fetched_at >= '{start_str}'",
            f"fetched_at <= '{end_str}'",
        ]
        if source_type:
            filters.append(f"source_type == '{source_type}'")

        filter_expr = " and ".join(filters)

        try:
            scan = self.table.scan(
                row_filter=filter_expr,
                limit=limit,
            )

            items = list(self._scan_to_items(scan))
            query_time = (time.time() - query_start) * 1000

            return QueryResult(
                items=items,
                total_count=len(items),
                snapshot_id=self._get_snapshot_id(),
                query_time_ms=query_time,
            )

        except Exception as e:
            logger.error(f"Failed to query content by time range: {e}")
            return QueryResult(items=[], total_count=0)

    def get_by_id(self, content_id: str) -> ContentItem | None:
        """Get a specific content item by ID.

        Args:
            content_id: UUID of the content record.

        Returns:
            ContentItem or None if not found.
        """
        try:
            scan = self.table.scan(
                row_filter=f"id == '{content_id}'",
                limit=1,
            )

            items = list(self._scan_to_items(scan))
            return items[0] if items else None

        except Exception as e:
            logger.error(f"Failed to get content by ID: {e}")
            return None

    def count_unprocessed(self, source_type: str | None = None) -> int:
        """Count unprocessed items.

        Args:
            source_type: Optional source type filter.

        Returns:
            Count of unprocessed items.
        """
        filters = ["processed == false", "summary_excluded == false"]
        if source_type:
            filters.append(f"source_type == '{source_type}'")

        filter_expr = " and ".join(filters)

        try:
            # Use count aggregation if available, otherwise scan
            scan = self.table.scan(
                row_filter=filter_expr,
                selected_fields=("id",),  # Minimize data transfer
            )

            # Count rows
            count = sum(1 for _ in scan.to_arrow())
            return count

        except Exception as e:
            logger.error(f"Failed to count unprocessed: {e}")
            return 0

    def _scan_to_items(self, scan) -> Iterator[ContentItem]:
        """Convert a table scan to ContentItem objects.

        Args:
            scan: PyIceberg TableScan.

        Yields:
            ContentItem objects.
        """
        import json

        # Convert scan to a single Arrow table
        arrow_table = scan.to_arrow()
        for i in range(arrow_table.num_rows):
            row = {col: arrow_table.column(col)[i].as_py()
                   for col in arrow_table.column_names}

            # Parse metadata JSON if present
            metadata = None
            if row.get("metadata"):
                try:
                    metadata = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    metadata = None

            yield ContentItem(
                id=row["id"],
                source_id=row["source_id"],
                external_id=row["external_id"],
                title=row["title"],
                url=row.get("url"),
                authors=row.get("authors"),
                raw_content=row.get("raw_content"),
                content_type=row.get("content_type"),
                metadata=metadata,
                published_at=row.get("published_at"),
                fetched_at=row.get("fetched_at"),
                source_type=row["source_type"],
                processed=row.get("processed", False),
                summary_excluded=row.get("summary_excluded", False),
                exclusion_reason=row.get("exclusion_reason"),
                quality_score=row.get("quality_score"),
            )

    def _get_snapshot_id(self) -> int | None:
        """Get current snapshot ID."""
        snapshot = self.table.current_snapshot()
        return snapshot.snapshot_id if snapshot else None
