"""Iceberg Table Schema for Exchange Data.

Defines the schema for storing external API request-response pairs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


def get_exchange_schema():
    """Get the schema for exchange (request-response) storage.

    Returns:
        PyIceberg Schema for raw.exchange table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        NestedField(1, "id", StringType(), required=True, doc="UUID of the exchange record"),
        NestedField(2, "provider", StringType(), required=True, doc="API provider (xai, cerebras, bytez, brave)"),
        NestedField(3, "request_hash", StringType(), required=True, doc="SHA-256 hash for deduplication"),
        NestedField(4, "request_messages", StringType(), required=True, doc="JSON array of chat messages"),
        NestedField(5, "request_model", StringType(), required=True, doc="Model identifier requested"),
        NestedField(6, "request_params", StringType(), required=False, doc="JSON: temperature, max_tokens, etc."),
        NestedField(7, "response_content", StringType(), required=True, doc="Full response text"),
        NestedField(8, "response_model", StringType(), required=False, doc="Actual model used"),
        NestedField(9, "input_tokens", LongType(), required=False, doc="Input token count"),
        NestedField(10, "output_tokens", LongType(), required=False, doc="Output token count"),
        NestedField(11, "latency_ms", LongType(), required=False, doc="Request latency in milliseconds"),
        NestedField(12, "created_at", TimestamptzType(), required=True, doc="When exchange was captured"),
        NestedField(13, "source_context", StringType(), required=False, doc="JSON: agent_alias, task_type, etc."),
        NestedField(14, "response_reasoning", StringType(), required=False, doc="Chain-of-thought reasoning from reasoning models (GLM-4.7)"),
    )


def get_exchange_partition_spec():
    """Get the partition specification for exchange table.

    Partitions by:
    - provider: Separate files per API provider
    - created_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=2,  # provider field
            field_id=1000,
            transform=IdentityTransform(),
            name="provider_part",
        ),
        PartitionField(
            source_id=12,  # created_at field
            field_id=1001,
            transform=MonthTransform(),
            name="created_month",
        ),
    )


def get_exchange_sort_order():
    """Get the sort order for exchange table.

    Sorts by created_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=12, direction=SortDirection.DESC),  # created_at DESC
    )


def create_exchange_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "exchange",
    if_not_exists: bool = True,
) -> Table:
    """Create the exchange Iceberg table.

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

        schema = get_exchange_schema()
        partition_spec = get_exchange_partition_spec()
        sort_order = get_exchange_sort_order()

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


def evolve_exchange_schema(table: Table) -> bool:
    """Evolve exchange table schema to match current definition.

    Adds any missing columns from the current schema definition.
    Iceberg supports safe schema evolution for adding nullable columns.

    Args:
        table: PyIceberg Table instance.

    Returns:
        True if schema was updated, False if already current.
    """
    current_schema = table.schema()
    target_schema = get_exchange_schema()

    # Find missing columns
    current_names = {f.name for f in current_schema.fields}
    missing_fields = [f for f in target_schema.fields if f.name not in current_names]

    if not missing_fields:
        return False

    logger.info(f"Evolving exchange schema: adding {[f.name for f in missing_fields]}")

    # Add missing columns
    with table.update_schema() as update:
        for field in missing_fields:
            logger.info(f"  Adding column: {field.name} ({field.field_type})")
            update.add_column(field.name, field.field_type, doc=field.doc)

    logger.info("Exchange schema evolution complete")
    return True


def get_exchange_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "exchange",
) -> Table:
    """Get the exchange table, creating if necessary.

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
        evolve_exchange_schema(table)
        return table
    except Exception:
        return create_exchange_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )
