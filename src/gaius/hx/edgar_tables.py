"""Iceberg Table Schema for SEC EDGAR Filings.

Defines the schema for sync-oriented SEC filing storage.
The accession_number is the primary key - SEC guarantees uniqueness.

Table Structure:
- Primary key: accession_number (unique per filing)
- Partitioned by: filing_type, filing_month
- Sorted by: symbol ASC, filing_date DESC
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


def get_edgar_filings_schema():
    """Get the schema for EDGAR filings storage.

    Returns:
        PyIceberg Schema for raw.edgar_filings table.
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
        # Primary key - SEC's unique filing identifier
        NestedField(1, "accession_number", StringType(), required=True,
                    doc="SEC accession number (primary key, e.g., 0001104659-26-001107)"),

        # Filing metadata
        NestedField(2, "symbol", StringType(), required=True, doc="Stock symbol"),
        NestedField(3, "cik", StringType(), required=True, doc="Central Index Key"),
        NestedField(4, "filing_type", StringType(), required=True,
                    doc="Filing type (10-K, 10-Q, 8-K, etc.)"),
        NestedField(5, "filing_date", StringType(), required=True, doc="Date filed with SEC"),
        NestedField(6, "url", StringType(), required=True, doc="Full SEC EDGAR URL"),

        # Raw content
        NestedField(7, "raw_html", StringType(), required=True, doc="Full HTML content"),
        NestedField(8, "content_hash", StringType(), required=True,
                    doc="SHA-256 hash of raw_html for integrity verification"),
        NestedField(9, "raw_html_length", LongType(), required=True, doc="Length of raw HTML in bytes"),
        NestedField(10, "title", StringType(), required=False, doc="Filing title from HTML"),

        # Fetch metadata
        NestedField(11, "fetched_at", TimestamptzType(), required=False, doc="When content was fetched"),
        NestedField(12, "fetch_latency_ms", LongType(), required=False, doc="Fetch latency in milliseconds"),

        # Extraction metadata (populated by Metaflow docling step)
        NestedField(13, "extracted_text", StringType(), required=False,
                    doc="Docling-extracted text content"),
        NestedField(14, "extracted_at", TimestamptzType(), required=False,
                    doc="When extraction was performed"),
        NestedField(15, "extraction_model", StringType(), required=False,
                    doc="Docling model version used"),

        # Source tracking
        NestedField(16, "source_context", StringType(), required=False,
                    doc="JSON: profile, domain, etc."),

        # Analysis metadata (populated by Cerebras GLM 4.7)
        NestedField(17, "analyzed_at", TimestamptzType(), required=False,
                    doc="When LLM analysis was performed"),
        NestedField(18, "analysis_model", StringType(), required=False,
                    doc="LLM model used for analysis (e.g., zai-glm-4.7)"),
        NestedField(19, "analysis_json", StringType(), required=False,
                    doc="JSON: FilingAnalysis serialized result"),

        # Chain-of-thought reasoning (for distillation training data)
        NestedField(20, "analysis_reasoning", StringType(), required=False,
                    doc="GLM chain-of-thought reasoning for distillation"),
    )


def get_edgar_filings_partition_spec():
    """Get the partition specification for EDGAR filings table.

    Partitions by:
    - filing_type: Separate files per type (10-K, 10-Q, 8-K, etc.)
    - filing_month: Monthly partitions based on filing_date

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, TruncateTransform

    return PartitionSpec(
        PartitionField(
            source_id=4,  # filing_type field
            field_id=1000,
            transform=IdentityTransform(),
            name="filing_type_part",
        ),
        # Partition by year-month from filing_date (YYYY-MM format)
        PartitionField(
            source_id=5,  # filing_date field
            field_id=1001,
            transform=TruncateTransform(width=7),  # YYYY-MM
            name="filing_month",
        ),
    )


def get_edgar_filings_sort_order():
    """Get the sort order for EDGAR filings table.

    Sorts by symbol then filing_date descending for efficient queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import NullOrder, SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=2, direction=SortDirection.ASC, null_order=NullOrder.NULLS_LAST),  # symbol ASC
        SortField(source_id=5, direction=SortDirection.DESC),  # filing_date DESC
    )


def create_edgar_filings_table(
    catalog: "Catalog",
    namespace: str = "raw",
    table_name: str = "edgar_filings",
    if_not_exists: bool = True,
) -> "Table":
    """Create the EDGAR filings Iceberg table.

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

        schema = get_edgar_filings_schema()
        partition_spec = get_edgar_filings_partition_spec()
        sort_order = get_edgar_filings_sort_order()

        logger.info(f"Creating EDGAR filings Iceberg table: {table_id}")

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

        logger.info(f"Created EDGAR filings Iceberg table: {table_id}")
        return table

    except TableAlreadyExistsError:
        if if_not_exists:
            logger.debug(f"EDGAR filings table already exists: {table_id}")
            return catalog.load_table(table_id)
        raise


def evolve_edgar_filings_schema(table: "Table") -> bool:
    """Evolve EDGAR filings table schema to match current definition.

    Args:
        table: PyIceberg Table instance.

    Returns:
        True if schema was updated, False if already current.
    """
    current_schema = table.schema()
    target_schema = get_edgar_filings_schema()

    # Find missing columns
    current_names = {f.name for f in current_schema.fields}
    missing_fields = [f for f in target_schema.fields if f.name not in current_names]

    if not missing_fields:
        return False

    logger.info(f"Evolving EDGAR filings schema: adding {[f.name for f in missing_fields]}")

    with table.update_schema() as update:
        for field in missing_fields:
            logger.info(f"  Adding column: {field.name} ({field.field_type})")
            update.add_column(field.name, field.field_type, doc=field.doc)

    logger.info("EDGAR filings schema evolution complete")
    return True


def get_edgar_filings_table(
    catalog: "Catalog",
    namespace: str = "raw",
    table_name: str = "edgar_filings",
) -> "Table":
    """Get the EDGAR filings table, creating if necessary.

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
        # Refresh to get latest schema (important after schema evolution)
        table.refresh()
        evolve_edgar_filings_schema(table)
        return table
    except Exception:
        return create_edgar_filings_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )


# Legacy aliases for backward compatibility
get_edgar_exchange_schema = get_edgar_filings_schema
create_edgar_exchange_table = create_edgar_filings_table
get_edgar_exchange_table = get_edgar_filings_table
