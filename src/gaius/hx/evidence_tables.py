"""Iceberg Table Schema for RASE Verification Evidence.

Defines the schema for storing verification results from the RASE
objective verification pipeline. Each record represents a complete
verification run with:
- Objective metadata
- Verification result (verdict, accuracy, reward)
- Constraint results
- Digital thread for training lineage
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


def get_evidence_schema():
    """Get the schema for RASE verification evidence storage.

    Returns:
        PyIceberg Schema for rase.evidence table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        BooleanType,
        DoubleType,
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        # Identity
        NestedField(1, "id", StringType(), required=True, doc="UUID of the evidence record"),
        NestedField(2, "run_id", StringType(), required=True, doc="Human-readable run ID (timestamp_thread)"),

        # Objective metadata
        NestedField(3, "objective_name", StringType(), required=True, doc="Name of the verified objective"),
        NestedField(4, "objective_type", StringType(), required=False, doc="Objective type (rase-objective, etc.)"),
        NestedField(5, "domain", StringType(), required=True, doc="Domain (kb, nifi, etc.)"),

        # Verification result
        NestedField(6, "verdict", StringType(), required=True, doc="Verdict: pass, fail, inconclusive, error"),
        NestedField(7, "accuracy", DoubleType(), required=True, doc="Accuracy score 0.0-1.0"),
        NestedField(8, "reward", DoubleType(), required=True, doc="Computed reward for training"),

        # Gate results
        NestedField(9, "gates_total", LongType(), required=True, doc="Total number of gates evaluated"),
        NestedField(10, "gates_passed", LongType(), required=True, doc="Number of gates that passed"),
        NestedField(11, "constraint_results", StringType(), required=True, doc="JSON array of constraint results"),

        # Document context
        NestedField(12, "document_path", StringType(), required=False, doc="Path to verified document"),
        NestedField(13, "document_hash", StringType(), required=False, doc="SHA-256 of document content"),

        # Digital thread
        NestedField(14, "thread_id", StringType(), required=True, doc="TraceableId of digital thread"),
        NestedField(15, "thread_data", StringType(), required=False, doc="JSON digital thread for lineage"),

        # Timing
        NestedField(16, "created_at", TimestamptzType(), required=True, doc="When verification was performed"),
        NestedField(17, "duration_ms", LongType(), required=False, doc="Verification duration in ms"),

        # Training metadata
        NestedField(18, "is_training_eligible", BooleanType(), required=False, doc="Eligible for training"),
        NestedField(19, "calibration_source", StringType(), required=False, doc="External calibration: cerebras, xai"),
        NestedField(20, "calibration_score", DoubleType(), required=False, doc="External calibration score"),
    )


def get_evidence_partition_spec():
    """Get the partition specification for evidence table.

    Partitions by:
    - domain: Separate files per verification domain
    - created_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=5,  # domain field
            field_id=1000,
            transform=IdentityTransform(),
            name="domain_part",
        ),
        PartitionField(
            source_id=16,  # created_at field
            field_id=1001,
            transform=MonthTransform(),
            name="created_month",
        ),
    )


def get_evidence_sort_order():
    """Get the sort order for evidence table.

    Sorts by created_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=16, direction=SortDirection.DESC),  # created_at DESC
    )


def create_evidence_table(
    catalog: Catalog,
    namespace: str = "rase",
    table_name: str = "evidence",
    if_not_exists: bool = True,
) -> Table:
    """Create the RASE evidence Iceberg table.

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

        schema = get_evidence_schema()
        partition_spec = get_evidence_partition_spec()
        sort_order = get_evidence_sort_order()

        logger.info(f"Creating Iceberg table: {table_id}")

        # Ensure namespace exists
        try:
            catalog.create_namespace(namespace)
        except Exception:
            pass  # Namespace may already exist

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


def evolve_evidence_schema(table: Table) -> bool:
    """Evolve evidence table schema to match current definition.

    Adds any missing columns from the current schema definition.
    Iceberg supports safe schema evolution for adding nullable columns.

    Args:
        table: PyIceberg Table instance.

    Returns:
        True if schema was updated, False if already current.
    """
    current_schema = table.schema()
    target_schema = get_evidence_schema()

    # Find missing columns
    current_names = {f.name for f in current_schema.fields}
    missing_fields = [f for f in target_schema.fields if f.name not in current_names]

    if not missing_fields:
        return False

    logger.info(f"Evolving evidence schema: adding {[f.name for f in missing_fields]}")

    # Add missing columns
    with table.update_schema() as update:
        for field in missing_fields:
            logger.info(f"  Adding column: {field.name} ({field.field_type})")
            update.add_column(field.name, field.field_type, doc=field.doc)

    logger.info("Evidence schema evolution complete")
    return True


def get_evidence_table(
    catalog: Catalog,
    namespace: str = "rase",
    table_name: str = "evidence",
) -> Table:
    """Get the evidence table, creating if necessary.

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
        evolve_evidence_schema(table)
        return table
    except Exception:
        return create_evidence_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )


__all__ = [
    "get_evidence_schema",
    "get_evidence_partition_spec",
    "get_evidence_sort_order",
    "create_evidence_table",
    "get_evidence_table",
    "evolve_evidence_schema",
]
