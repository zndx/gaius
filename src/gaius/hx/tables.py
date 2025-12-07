"""Iceberg Table Schemas.

Defines the schema for raw content storage in Iceberg tables.
Uses PyIceberg schema definitions with partitioning by source type and month.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


def get_raw_content_schema():
    """Get the schema for raw content storage.

    Returns:
        PyIceberg Schema for raw_content table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        BooleanType,
        ListType,
        LongType,
        NestedField,
        StringType,
        TimestampType,
        TimestamptzType,
    )

    return Schema(
        NestedField(1, "id", StringType(), required=True, doc="UUID of the content record"),
        NestedField(2, "source_id", LongType(), required=True, doc="FK to sources table"),
        NestedField(3, "external_id", StringType(), required=True, doc="Source-specific ID (e.g., arxiv ID)"),
        NestedField(4, "title", StringType(), required=True, doc="Content title"),
        NestedField(5, "url", StringType(), required=False, doc="Source URL"),
        NestedField(6, "authors", ListType(10, StringType()), required=False, doc="List of authors"),
        NestedField(7, "raw_content", StringType(), required=False, doc="Raw content text (may be large)"),
        NestedField(8, "content_type", StringType(), required=False, doc="MIME type or content format"),
        NestedField(9, "metadata", StringType(), required=False, doc="Additional metadata as JSON"),
        NestedField(10, "published_at", TimestamptzType(), required=False, doc="Publication timestamp"),
        NestedField(11, "fetched_at", TimestamptzType(), required=True, doc="When content was fetched"),
        NestedField(12, "source_type", StringType(), required=True, doc="Source type (arxiv, rss, docs)"),
        NestedField(13, "processed", BooleanType(), required=True, doc="Whether summarized to KB"),
        NestedField(14, "summary_excluded", BooleanType(), required=False, doc="Excluded from summarization"),
        NestedField(15, "exclusion_reason", StringType(), required=False, doc="Why content was excluded"),
        NestedField(16, "quality_score", LongType(), required=False, doc="Quality assessment (0-100)"),
        NestedField(17, "content_hash", StringType(), required=False, doc="SHA-256 hash for duplicate detection"),
    )


# Module-level constant for schema
RAW_CONTENT_SCHEMA = None  # Lazily initialized


def _get_schema():
    """Lazily get the schema."""
    global RAW_CONTENT_SCHEMA
    if RAW_CONTENT_SCHEMA is None:
        RAW_CONTENT_SCHEMA = get_raw_content_schema()
    return RAW_CONTENT_SCHEMA


def get_partition_spec():
    """Get the partition specification for raw content.

    Partitions by:
    - source_type: Separate files per source (arxiv, rss, docs)
    - fetch_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=12,  # source_type field
            field_id=1000,
            transform=IdentityTransform(),
            name="source_type_part",
        ),
        PartitionField(
            source_id=11,  # fetched_at field
            field_id=1001,
            transform=MonthTransform(),
            name="fetch_month",
        ),
    )


def get_sort_order():
    """Get the sort order for raw content.

    Sorts by fetched_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=11, direction=SortDirection.DESC),  # fetched_at DESC
    )


def create_raw_content_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "content",
    if_not_exists: bool = True,
) -> Table:
    """Create the raw content Iceberg table.

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

        schema = get_raw_content_schema()
        partition_spec = get_partition_spec()
        sort_order = get_sort_order()

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


def get_raw_content_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "content",
) -> Table:
    """Get the raw content table, creating if necessary.

    Args:
        catalog: PyIceberg catalog instance.
        namespace: Namespace for the table.
        table_name: Name of the table.

    Returns:
        PyIceberg Table instance.
    """
    table_id = f"{namespace}.{table_name}"

    try:
        return catalog.load_table(table_id)
    except Exception:
        return create_raw_content_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )
