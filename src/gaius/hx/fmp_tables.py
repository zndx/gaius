"""Iceberg Table Schema for FMP Exchange Data.

Defines the schema for storing FMP API request-response pairs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


def get_fmp_exchange_schema():
    """Get the schema for FMP exchange storage.

    Returns:
        PyIceberg Schema for raw.fmp_exchange table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        IntegerType,
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        NestedField(1, "id", StringType(), required=True, doc="UUID of the exchange record"),
        NestedField(2, "provider", StringType(), required=True, doc="Always 'fmp'"),
        NestedField(3, "endpoint", StringType(), required=True, doc="FMP endpoint type (sec-filings, institutional-holder, etc.)"),
        NestedField(4, "request_hash", StringType(), required=True, doc="SHA-256 hash for deduplication"),
        NestedField(5, "url", StringType(), required=True, doc="Full URL (apikey masked)"),
        NestedField(6, "symbol", StringType(), required=False, doc="Stock symbol if applicable"),
        NestedField(7, "params", StringType(), required=False, doc="JSON: query parameters"),
        NestedField(8, "response_data", StringType(), required=True, doc="Full JSON response"),
        NestedField(9, "status_code", IntegerType(), required=True, doc="HTTP status code"),
        NestedField(10, "latency_ms", LongType(), required=False, doc="Request latency in milliseconds"),
        NestedField(11, "created_at", TimestamptzType(), required=True, doc="When exchange was captured"),
        NestedField(12, "source_context", StringType(), required=False, doc="JSON: profile, domain, etc."),
    )


def get_fmp_partition_spec():
    """Get the partition specification for FMP exchange table.

    Partitions by:
    - endpoint: Separate files per endpoint type (sec-filings, holdings, etc.)
    - created_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=3,  # endpoint field
            field_id=1000,
            transform=IdentityTransform(),
            name="endpoint_part",
        ),
        PartitionField(
            source_id=11,  # created_at field
            field_id=1001,
            transform=MonthTransform(),
            name="created_month",
        ),
    )


def get_fmp_sort_order():
    """Get the sort order for FMP exchange table.

    Sorts by symbol then created_at descending for efficient queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import NullOrder, SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=6, direction=SortDirection.ASC, null_order=NullOrder.NULLS_LAST),  # symbol ASC
        SortField(source_id=11, direction=SortDirection.DESC),  # created_at DESC
    )


def create_fmp_exchange_table(
    catalog: "Catalog",
    namespace: str = "raw",
    table_name: str = "fmp_exchange",
    if_not_exists: bool = True,
) -> "Table":
    """Create the FMP exchange Iceberg table.

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

        schema = get_fmp_exchange_schema()
        partition_spec = get_fmp_partition_spec()
        sort_order = get_fmp_sort_order()

        logger.info(f"Creating FMP exchange Iceberg table: {table_id}")

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

        logger.info(f"Created FMP exchange Iceberg table: {table_id}")
        return table

    except TableAlreadyExistsError:
        if if_not_exists:
            logger.debug(f"FMP table already exists: {table_id}")
            return catalog.load_table(table_id)
        raise


def evolve_fmp_schema(table: "Table") -> bool:
    """Evolve FMP exchange table schema to match current definition.

    Args:
        table: PyIceberg Table instance.

    Returns:
        True if schema was updated, False if already current.
    """
    current_schema = table.schema()
    target_schema = get_fmp_exchange_schema()

    # Find missing columns
    current_names = {f.name for f in current_schema.fields}
    missing_fields = [f for f in target_schema.fields if f.name not in current_names]

    if not missing_fields:
        return False

    logger.info(f"Evolving FMP exchange schema: adding {[f.name for f in missing_fields]}")

    with table.update_schema() as update:
        for field in missing_fields:
            logger.info(f"  Adding column: {field.name} ({field.field_type})")
            update.add_column(field.name, field.field_type, doc=field.doc)

    logger.info("FMP exchange schema evolution complete")
    return True


def get_fmp_exchange_table(
    catalog: "Catalog",
    namespace: str = "raw",
    table_name: str = "fmp_exchange",
) -> "Table":
    """Get the FMP exchange table, creating if necessary.

    Also evolves schema if new columns have been added.

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
        evolve_fmp_schema(table)
        return table
    except Exception:
        return create_fmp_exchange_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )
