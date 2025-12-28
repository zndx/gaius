"""Iceberg Table Schema for Bookmarks Data.

Defines the schema for storing bookmarked content in Iceberg.
Supports multiple sources (X/Twitter, Pinboard, Pocket, etc.).
Raw data is stored here for long-term archival, while PostgreSQL
holds sync state and the KB holds curated summaries.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pyarrow as pa

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


def get_bookmarks_schema():
    """Get the schema for bookmarks storage.

    Returns:
        PyIceberg Schema for raw.bookmarks table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        ListType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        # Core identification
        NestedField(1, "id", StringType(), required=True, doc="UUID of the bookmark record"),
        NestedField(2, "source", StringType(), required=True, doc="Source service: x, pinboard, pocket, etc."),
        NestedField(3, "source_id", StringType(), required=True, doc="ID from the source service (tweet_id, etc.)"),
        NestedField(4, "user_id", StringType(), required=True, doc="User ID who bookmarked"),
        NestedField(5, "content_hash", StringType(), required=True, doc="SHA-256 hash for deduplication"),
        # Content
        NestedField(6, "text", StringType(), required=True, doc="Text content"),
        NestedField(7, "author_id", StringType(), required=False, doc="Content author ID"),
        NestedField(8, "author_username", StringType(), required=False, doc="Content author @handle or name"),
        # Extracted data
        NestedField(9, "urls", ListType(20, StringType()), required=False, doc="Extracted URLs"),
        NestedField(10, "media_urls", ListType(21, StringType()), required=False, doc="Media attachment URLs"),
        NestedField(11, "tags", ListType(22, StringType()), required=False, doc="Tags/labels"),
        # Folder organization
        NestedField(12, "folder_id", StringType(), required=False, doc="Folder/collection ID"),
        NestedField(13, "folder_name", StringType(), required=False, doc="Folder/collection name"),
        # Timestamps
        NestedField(14, "content_created_at", TimestamptzType(), required=False, doc="When content was created"),
        NestedField(15, "bookmarked_at", TimestamptzType(), required=False, doc="When bookmark was added"),
        NestedField(16, "synced_at", TimestamptzType(), required=True, doc="When synced to Iceberg"),
        # Raw data
        NestedField(17, "raw_content", StringType(), required=False, doc="Full raw content JSON from API"),
        NestedField(18, "metadata", StringType(), required=False, doc="Additional metadata as JSON"),
    )


def get_bookmarks_partition_spec():
    """Get the partition specification for bookmarks table.

    Partitions by:
    - source: Separate files per source service (x, pinboard, etc.)
    - synced_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=2,  # source field
            field_id=1000,
            transform=IdentityTransform(),
            name="source_part",
        ),
        PartitionField(
            source_id=16,  # synced_at field
            field_id=1001,
            transform=MonthTransform(),
            name="synced_month",
        ),
    )


def get_bookmarks_sort_order():
    """Get the sort order for bookmarks table.

    Sorts by synced_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=16, direction=SortDirection.DESC),  # synced_at DESC
    )


def create_bookmarks_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "bookmarks",
    if_not_exists: bool = True,
) -> Table:
    """Create the bookmarks Iceberg table.

    Args:
        catalog: PyIceberg catalog instance.
        namespace: Namespace for the table.
        table_name: Name of the table.
        if_not_exists: If True, don't error if table exists.

    Returns:
        PyIceberg Table instance.
    """
    from pyiceberg.exceptions import TableAlreadyExistsError

    table_id = f"{namespace}.{table_name}"

    try:
        # Check if table exists
        if if_not_exists:
            try:
                return catalog.load_table(table_id)
            except Exception:
                pass  # Table doesn't exist, create it

        schema = get_bookmarks_schema()
        partition_spec = get_bookmarks_partition_spec()
        sort_order = get_bookmarks_sort_order()

        logger.info(f"Creating Iceberg table: {table_id}")

        table = catalog.create_table(
            identifier=table_id,
            schema=schema,
            partition_spec=partition_spec,
            sort_order=sort_order,
            properties={
                "write.parquet.compression-codec": "zstd",
                "write.parquet.compression-level": "3",
                "write.metadata.delete-after-commit.enabled": "true",
                "write.metadata.previous-versions-max": "10",
            },
        )

        logger.info(f"Created Iceberg table: {table_id}")
        return table

    except TableAlreadyExistsError:
        if if_not_exists:
            logger.debug(f"Table already exists: {table_id}")
            return catalog.load_table(table_id)
        raise


def evolve_bookmarks_schema(table: Table) -> bool:
    """Evolve bookmarks table schema to match current definition.

    Adds any missing columns from the current schema definition.
    Iceberg supports safe schema evolution for adding nullable columns.

    Args:
        table: PyIceberg Table instance.

    Returns:
        True if schema was updated, False if already current.
    """
    current_schema = table.schema()
    target_schema = get_bookmarks_schema()

    # Find missing columns
    current_names = {f.name for f in current_schema.fields}
    missing_fields = [f for f in target_schema.fields if f.name not in current_names]

    if not missing_fields:
        return False

    logger.info(f"Evolving bookmarks schema: adding {[f.name for f in missing_fields]}")

    # Add missing columns
    with table.update_schema() as update:
        for field in missing_fields:
            logger.info(f"  Adding column: {field.name} ({field.field_type})")
            update.add_column(field.name, field.field_type, doc=field.doc)

    logger.info("Bookmarks schema evolution complete")
    return True


def get_bookmarks_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "bookmarks",
) -> Table:
    """Get the bookmarks table, creating if necessary.

    Also evolves schema if new columns have been added to the definition.

    Args:
        catalog: PyIceberg catalog instance.
        namespace: Namespace for the table.
        table_name: Name of the table.

    Returns:
        PyIceberg Table instance.
    """
    table_id = f"{namespace}.{table_name}"

    try:
        table = catalog.load_table(table_id)
        # Evolve schema if needed (adds missing columns)
        evolve_bookmarks_schema(table)
        return table
    except Exception:
        return create_bookmarks_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )


def x_bookmark_to_arrow(row: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Convert an X bookmark from PostgreSQL to Arrow-compatible dict.

    Args:
        row: PostgreSQL row from x_bookmarks_sync.
        metadata: Parsed JSONB metadata from the row.

    Returns:
        Dict ready for Arrow/Iceberg ingestion.
    """
    now = datetime.now(timezone.utc)

    # Parse timestamps
    bookmarked_at = metadata.get("bookmarked_at")
    if bookmarked_at and isinstance(bookmarked_at, str):
        bookmarked_at = datetime.fromisoformat(bookmarked_at.replace("Z", "+00:00"))

    content_created_at = metadata.get("tweet_created_at")
    if content_created_at and isinstance(content_created_at, str):
        content_created_at = datetime.fromisoformat(content_created_at.replace("Z", "+00:00"))

    return {
        "id": str(uuid.uuid4()),
        "source": "x",
        "source_id": row["tweet_id"],
        "user_id": row["user_id"],
        "content_hash": row["content_hash"],
        "text": metadata.get("text", ""),
        "author_id": metadata.get("author_id"),
        "author_username": metadata.get("author_username"),
        "urls": metadata.get("urls", []),
        "media_urls": metadata.get("media_urls", []),
        "tags": [],  # X doesn't have tags on bookmarks
        "folder_id": row.get("folder_id"),
        "folder_name": metadata.get("folder_name"),
        "content_created_at": content_created_at,
        "bookmarked_at": bookmarked_at,
        "synced_at": now,
        "raw_content": json.dumps(metadata.get("metadata", {}).get("raw", {})),
        "metadata": json.dumps(metadata),
    }


def build_bookmarks_arrow_table(records: list[dict[str, Any]]) -> pa.Table:
    """Build a PyArrow table from bookmark records.

    Args:
        records: List of dicts from x_bookmark_to_arrow or similar.

    Returns:
        PyArrow Table ready for Iceberg append.
    """
    # Define Arrow schema matching Iceberg schema
    # List elements must be non-nullable to match Iceberg's list<string> type
    arrow_schema = pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("content_hash", pa.string(), nullable=False),
        pa.field("text", pa.string(), nullable=False),
        pa.field("author_id", pa.string(), nullable=True),
        pa.field("author_username", pa.string(), nullable=True),
        pa.field("urls", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("media_urls", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("tags", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("folder_id", pa.string(), nullable=True),
        pa.field("folder_name", pa.string(), nullable=True),
        pa.field("content_created_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("bookmarked_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("synced_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("raw_content", pa.string(), nullable=True),
        pa.field("metadata", pa.string(), nullable=True),
    ])

    # Build arrays for each column
    arrays = []
    for field in arrow_schema:
        values = [r.get(field.name) for r in records]
        arrays.append(pa.array(values, type=field.type))

    return pa.Table.from_arrays(arrays, schema=arrow_schema)


async def write_x_bookmarks_to_iceberg(
    pool,
    catalog: Catalog,
    batch_size: int = 100,
) -> int:
    """Write unsynced X bookmarks from PostgreSQL to Iceberg.

    Args:
        pool: asyncpg connection pool.
        catalog: PyIceberg catalog instance.
        batch_size: Number of records to process per batch.

    Returns:
        Number of records written.
    """
    table = get_bookmarks_table(catalog)

    async with pool.acquire() as conn:
        # Get bookmarks not yet in Iceberg
        rows = await conn.fetch(
            """
            SELECT tweet_id, folder_id, user_id, content_hash,
                   iceberg_id, bookmarked_at, synced_at, metadata
            FROM x_bookmarks_sync
            WHERE iceberg_id IS NULL
            ORDER BY synced_at
            LIMIT $1
            """,
            batch_size,
        )

        if not rows:
            logger.info("No new X bookmarks to write to Iceberg")
            return 0

        # Convert to Arrow records
        records = []
        for row in rows:
            # Parse metadata - asyncpg returns JSONB as string
            raw_metadata = row["metadata"]
            if isinstance(raw_metadata, str):
                metadata = json.loads(raw_metadata)
            elif isinstance(raw_metadata, dict):
                metadata = raw_metadata
            else:
                metadata = {}
            record = x_bookmark_to_arrow(dict(row), metadata)
            records.append(record)

        # Build Arrow table and append to Iceberg
        arrow_table = build_bookmarks_arrow_table(records)
        table.append(arrow_table)

        # Update PostgreSQL with Iceberg IDs
        for record in records:
            await conn.execute(
                """
                UPDATE x_bookmarks_sync
                SET iceberg_id = $1
                WHERE tweet_id = $2
                """,
                uuid.UUID(record["id"]),
                record["source_id"],
            )

        logger.info(f"Wrote {len(records)} X bookmarks to Iceberg raw.bookmarks")
        return len(records)
