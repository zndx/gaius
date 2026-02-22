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
            from pyiceberg.exceptions import NoSuchTableError
            try:
                return catalog.load_table(table_id)
            except NoSuchTableError:
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


def evolve_table_schema(table: Table) -> bool:
    """Evolve table schema to match current definition.

    Adds any missing columns from the current schema definition.
    Iceberg supports safe schema evolution for adding nullable columns.

    Args:
        table: PyIceberg Table instance.

    Returns:
        True if schema was updated, False if already current.
    """
    from pyiceberg.types import StringType

    current_schema = table.schema()
    target_schema = get_raw_content_schema()

    # Find missing columns
    current_names = {f.name for f in current_schema.fields}
    missing_fields = [f for f in target_schema.fields if f.name not in current_names]

    if not missing_fields:
        return False

    logger.info(f"Evolving schema: adding {[f.name for f in missing_fields]}")

    # Add missing columns
    with table.update_schema() as update:
        for field in missing_fields:
            logger.info(f"  Adding column: {field.name} ({field.field_type})")
            update.add_column(field.name, field.field_type, doc=field.doc)

    logger.info("Schema evolution complete")
    return True


def get_llm_generation_schema():
    """Get the schema for LLM generation storage.

    Stores full LLM outputs including thinking traces for future distillation,
    RL training, and dataset creation. Used by collection summary generation
    and other LLM-backed features.

    Returns:
        PyIceberg Schema for llm.generations table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        NestedField(1, "id", StringType(), required=True, doc="UUID of the generation record"),
        NestedField(2, "collection_id", StringType(), required=False, doc="Associated collection ID"),
        NestedField(3, "summary_type", StringType(), required=True, doc="Generation type (frontier, open_weights)"),
        NestedField(4, "prompt", StringType(), required=True, doc="Full prompt sent to the model"),
        NestedField(5, "output", StringType(), required=True, doc="Model output text"),
        NestedField(6, "thinking_trace", StringType(), required=False, doc="Chain-of-thought reasoning trace"),
        NestedField(7, "model_name", StringType(), required=True, doc="Model identifier used for generation"),
        NestedField(8, "input_tokens", LongType(), required=False, doc="Input token count"),
        NestedField(9, "output_tokens", LongType(), required=False, doc="Output token count"),
        NestedField(10, "latency_ms", LongType(), required=False, doc="Generation latency in milliseconds"),
        NestedField(11, "generated_at", TimestamptzType(), required=True, doc="When the generation was created"),
    )


def get_llm_generation_partition_spec():
    """Get the partition specification for LLM generations.

    Partitions by:
    - summary_type: Separate files per generation type (frontier, open_weights)
    - generation_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=3,  # summary_type field
            field_id=1000,
            transform=IdentityTransform(),
            name="summary_type_part",
        ),
        PartitionField(
            source_id=11,  # generated_at field
            field_id=1001,
            transform=MonthTransform(),
            name="generation_month",
        ),
    )


def get_llm_generation_sort_order():
    """Get the sort order for LLM generations.

    Sorts by generated_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=11, direction=SortDirection.DESC),  # generated_at DESC
    )


def create_llm_generation_table(
    catalog: Catalog,
    namespace: str = "llm",
    table_name: str = "generations",
    if_not_exists: bool = True,
) -> Table:
    """Create the LLM generation Iceberg table.

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
        if if_not_exists:
            from pyiceberg.exceptions import NoSuchTableError
            try:
                return catalog.load_table(table_id)
            except NoSuchTableError:
                pass  # Table doesn't exist, create it

        schema = get_llm_generation_schema()
        partition_spec = get_llm_generation_partition_spec()
        sort_order = get_llm_generation_sort_order()

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


def get_llm_generation_table(
    catalog: Catalog,
    namespace: str = "llm",
    table_name: str = "generations",
) -> Table:
    """Get the LLM generation table, creating if necessary.

    Args:
        catalog: PyIceberg catalog instance.
        namespace: Namespace for the table.
        table_name: Name of the table.

    Returns:
        PyIceberg Table instance.
    """
    from pyiceberg.exceptions import NoSuchTableError

    table_id = f"{namespace}.{table_name}"

    try:
        table = catalog.load_table(table_id)
        return table
    except NoSuchTableError:
        return create_llm_generation_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )


def get_raw_content_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "content",
) -> Table:
    """Get the raw content table, creating if necessary.

    Also evolves schema if new columns have been added to the definition.

    Args:
        catalog: PyIceberg catalog instance.
        namespace: Namespace for the table.
        table_name: Name of the table.

    Returns:
        PyIceberg Table instance.
    """
    from pyiceberg.exceptions import NoSuchTableError

    table_id = f"{namespace}.{table_name}"

    try:
        table = catalog.load_table(table_id)
        # Evolve schema if needed (adds missing columns)
        evolve_table_schema(table)
        return table
    except NoSuchTableError:
        return create_raw_content_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )
