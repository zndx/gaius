"""Iceberg Table Schema for HuggingFace Hub Data.

Defines schemas for storing HuggingFace datasets and models metadata,
including README content for quality filtering. Enables:
1. Caching to avoid redundant API calls
2. Quality filtering by content richness
3. Time-travel for historical analysis
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


# =============================================================================
# HuggingFace Datasets Table
# =============================================================================


def get_hf_datasets_schema():
    """Get the schema for HuggingFace datasets storage.

    Returns:
        PyIceberg Schema for raw.hf_datasets table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        BooleanType,
        ListType,
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        # Core identification
        NestedField(1, "id", StringType(), required=True, doc="UUID of the record"),
        NestedField(2, "dataset_id", StringType(), required=True, doc="HF dataset ID (org/name)"),
        NestedField(3, "content_hash", StringType(), required=True, doc="SHA-256 of dataset_id for dedup"),
        # Metadata from list_datasets()
        NestedField(4, "author", StringType(), required=False, doc="Dataset author/org"),
        NestedField(5, "downloads", LongType(), required=False, doc="Download count"),
        NestedField(6, "likes", LongType(), required=False, doc="Like count"),
        NestedField(7, "private", BooleanType(), required=False, doc="Whether private"),
        NestedField(8, "tags", ListType(20, StringType()), required=False, doc="Dataset tags"),
        NestedField(9, "created_at", TimestamptzType(), required=False, doc="HF creation timestamp"),
        NestedField(10, "last_modified", TimestamptzType(), required=False, doc="HF last modified"),
        # README content (from DatasetCard.load())
        NestedField(11, "readme_content", StringType(), required=False, doc="Full README.md content"),
        NestedField(12, "readme_length", LongType(), required=False, doc="README length for filtering"),
        NestedField(13, "has_readme", BooleanType(), required=False, doc="Whether README exists"),
        # Sync tracking
        NestedField(14, "fetched_at", TimestamptzType(), required=True, doc="When synced to Iceberg"),
        NestedField(15, "readme_fetched", BooleanType(), required=False, doc="Whether README was fetched"),
        # Raw API response
        NestedField(16, "raw_metadata", StringType(), required=False, doc="Full API response as JSON"),
    )


def get_hf_datasets_partition_spec():
    """Get the partition specification for HF datasets table.

    Partitions by:
    - fetched_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=14,  # fetched_at field
            field_id=1000,
            transform=MonthTransform(),
            name="fetched_month",
        ),
    )


def get_hf_datasets_sort_order():
    """Get the sort order for HF datasets table.

    Sorts by fetched_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=14, direction=SortDirection.DESC),  # fetched_at DESC
    )


def create_hf_datasets_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "hf_datasets",
    if_not_exists: bool = True,
) -> Table:
    """Create the HF datasets Iceberg table.

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
            try:
                return catalog.load_table(table_id)
            except Exception:
                pass

        schema = get_hf_datasets_schema()
        partition_spec = get_hf_datasets_partition_spec()
        sort_order = get_hf_datasets_sort_order()

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


def get_hf_datasets_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "hf_datasets",
) -> Table:
    """Get the HF datasets table, creating if necessary.

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
        return create_hf_datasets_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )


# =============================================================================
# HuggingFace Models Table
# =============================================================================


def get_hf_models_schema():
    """Get the schema for HuggingFace models storage.

    Returns:
        PyIceberg Schema for raw.hf_models table.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        BooleanType,
        ListType,
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        # Core identification
        NestedField(1, "id", StringType(), required=True, doc="UUID of the record"),
        NestedField(2, "model_id", StringType(), required=True, doc="HF model ID (org/name)"),
        NestedField(3, "content_hash", StringType(), required=True, doc="SHA-256 of model_id for dedup"),
        # Metadata from list_models()
        NestedField(4, "author", StringType(), required=False, doc="Model author/org"),
        NestedField(5, "pipeline_tag", StringType(), required=False, doc="Pipeline task type"),
        NestedField(6, "library_name", StringType(), required=False, doc="Library (transformers, etc)"),
        NestedField(7, "downloads", LongType(), required=False, doc="Download count"),
        NestedField(8, "likes", LongType(), required=False, doc="Like count"),
        NestedField(9, "private", BooleanType(), required=False, doc="Whether private"),
        NestedField(10, "gated", BooleanType(), required=False, doc="Whether gated access"),
        NestedField(11, "tags", ListType(20, StringType()), required=False, doc="Model tags"),
        NestedField(12, "created_at", TimestamptzType(), required=False, doc="HF creation timestamp"),
        NestedField(13, "last_modified", TimestamptzType(), required=False, doc="HF last modified"),
        # README content (from ModelCard.load())
        NestedField(14, "readme_content", StringType(), required=False, doc="Full README.md content"),
        NestedField(15, "readme_length", LongType(), required=False, doc="README length for filtering"),
        NestedField(16, "has_readme", BooleanType(), required=False, doc="Whether README exists"),
        # Sync tracking
        NestedField(17, "fetched_at", TimestamptzType(), required=True, doc="When synced to Iceberg"),
        NestedField(18, "readme_fetched", BooleanType(), required=False, doc="Whether README was fetched"),
        # Raw API response
        NestedField(19, "raw_metadata", StringType(), required=False, doc="Full API response as JSON"),
    )


def get_hf_models_partition_spec():
    """Get the partition specification for HF models table.

    Partitions by:
    - fetched_month: Monthly partitions for time-based queries

    Returns:
        PyIceberg PartitionSpec.
    """
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import MonthTransform

    return PartitionSpec(
        PartitionField(
            source_id=17,  # fetched_at field
            field_id=1000,
            transform=MonthTransform(),
            name="fetched_month",
        ),
    )


def get_hf_models_sort_order():
    """Get the sort order for HF models table.

    Sorts by fetched_at descending for efficient recent-first queries.

    Returns:
        PyIceberg SortOrder.
    """
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(
        SortField(source_id=17, direction=SortDirection.DESC),  # fetched_at DESC
    )


def create_hf_models_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "hf_models",
    if_not_exists: bool = True,
) -> Table:
    """Create the HF models Iceberg table.

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
            try:
                return catalog.load_table(table_id)
            except Exception:
                pass

        schema = get_hf_models_schema()
        partition_spec = get_hf_models_partition_spec()
        sort_order = get_hf_models_sort_order()

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


def get_hf_models_table(
    catalog: Catalog,
    namespace: str = "raw",
    table_name: str = "hf_models",
) -> Table:
    """Get the HF models table, creating if necessary.

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
        return create_hf_models_table(
            catalog,
            namespace=namespace,
            table_name=table_name,
            if_not_exists=True,
        )


# =============================================================================
# Arrow Conversion Utilities
# =============================================================================


def build_hf_datasets_arrow_table(records: list[dict[str, Any]]) -> pa.Table:
    """Build a PyArrow table from HF dataset records.

    Args:
        records: List of dicts with dataset metadata.

    Returns:
        PyArrow Table ready for Iceberg append.
    """
    arrow_schema = pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("content_hash", pa.string(), nullable=False),
        pa.field("author", pa.string(), nullable=True),
        pa.field("downloads", pa.int64(), nullable=True),
        pa.field("likes", pa.int64(), nullable=True),
        pa.field("private", pa.bool_(), nullable=True),
        pa.field("tags", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("last_modified", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("readme_content", pa.string(), nullable=True),
        pa.field("readme_length", pa.int64(), nullable=True),
        pa.field("has_readme", pa.bool_(), nullable=True),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("readme_fetched", pa.bool_(), nullable=True),
        pa.field("raw_metadata", pa.string(), nullable=True),
    ])

    # Ensure timestamps are timezone-aware
    for record in records:
        for ts_field in ["created_at", "last_modified", "fetched_at"]:
            if record.get(ts_field):
                dt = record[ts_field]
                if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                    record[ts_field] = dt.replace(tzinfo=timezone.utc)

    return pa.Table.from_pylist(records, schema=arrow_schema)


def build_hf_models_arrow_table(records: list[dict[str, Any]]) -> pa.Table:
    """Build a PyArrow table from HF model records.

    Args:
        records: List of dicts with model metadata.

    Returns:
        PyArrow Table ready for Iceberg append.
    """
    arrow_schema = pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("model_id", pa.string(), nullable=False),
        pa.field("content_hash", pa.string(), nullable=False),
        pa.field("author", pa.string(), nullable=True),
        pa.field("pipeline_tag", pa.string(), nullable=True),
        pa.field("library_name", pa.string(), nullable=True),
        pa.field("downloads", pa.int64(), nullable=True),
        pa.field("likes", pa.int64(), nullable=True),
        pa.field("private", pa.bool_(), nullable=True),
        pa.field("gated", pa.bool_(), nullable=True),
        pa.field("tags", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("last_modified", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("readme_content", pa.string(), nullable=True),
        pa.field("readme_length", pa.int64(), nullable=True),
        pa.field("has_readme", pa.bool_(), nullable=True),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("readme_fetched", pa.bool_(), nullable=True),
        pa.field("raw_metadata", pa.string(), nullable=True),
    ])

    # Ensure timestamps are timezone-aware
    for record in records:
        for ts_field in ["created_at", "last_modified", "fetched_at"]:
            if record.get(ts_field):
                dt = record[ts_field]
                if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                    record[ts_field] = dt.replace(tzinfo=timezone.utc)

    return pa.Table.from_pylist(records, schema=arrow_schema)


# =============================================================================
# Conversion from HuggingFace API
# =============================================================================


def hf_dataset_to_record(
    ds_info: Any,
    readme_content: str | None = None,
) -> dict[str, Any]:
    """Convert HuggingFace DatasetInfo to Iceberg record.

    Args:
        ds_info: HuggingFace DatasetInfo object from list_datasets() or dataset_info()
        readme_content: Optional README content from DatasetCard.load()

    Returns:
        Dict ready for Arrow/Iceberg ingestion.
    """
    import hashlib

    now = datetime.now(timezone.utc)
    dataset_id = ds_info.id

    # Compute content hash for deduplication
    content_hash = hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()

    # Extract timestamps
    created_at = getattr(ds_info, "created_at", None)
    last_modified = getattr(ds_info, "last_modified", None)

    # Get tags as list
    tags = list(ds_info.tags) if ds_info.tags else []

    # README info
    has_readme = readme_content is not None and len(readme_content.strip()) > 0
    readme_length = len(readme_content) if readme_content else 0

    return {
        "id": str(uuid.uuid4()),
        "dataset_id": dataset_id,
        "content_hash": content_hash,
        "author": getattr(ds_info, "author", None) or "",
        "downloads": getattr(ds_info, "downloads", 0) or 0,
        "likes": getattr(ds_info, "likes", 0) or 0,
        "private": getattr(ds_info, "private", False) or False,
        "tags": tags,
        "created_at": created_at,
        "last_modified": last_modified,
        "readme_content": readme_content,
        "readme_length": readme_length,
        "has_readme": has_readme,
        "fetched_at": now,
        "readme_fetched": readme_content is not None,
        "raw_metadata": json.dumps({
            "id": dataset_id,
            "author": getattr(ds_info, "author", None),
            "downloads": getattr(ds_info, "downloads", 0),
            "likes": getattr(ds_info, "likes", 0),
            "tags": tags,
        }),
    }


def hf_model_to_record(
    model_info: Any,
    readme_content: str | None = None,
) -> dict[str, Any]:
    """Convert HuggingFace ModelInfo to Iceberg record.

    Args:
        model_info: HuggingFace ModelInfo object from list_models() or model_info()
        readme_content: Optional README content from ModelCard.load()

    Returns:
        Dict ready for Arrow/Iceberg ingestion.
    """
    import hashlib

    now = datetime.now(timezone.utc)
    model_id = model_info.id

    # Compute content hash for deduplication
    content_hash = hashlib.sha256(model_id.encode("utf-8")).hexdigest()

    # Extract timestamps
    created_at = getattr(model_info, "created_at", None)
    last_modified = getattr(model_info, "last_modified", None)

    # Get tags as list
    tags = list(model_info.tags) if model_info.tags else []

    # README info
    has_readme = readme_content is not None and len(readme_content.strip()) > 0
    readme_length = len(readme_content) if readme_content else 0

    return {
        "id": str(uuid.uuid4()),
        "model_id": model_id,
        "content_hash": content_hash,
        "author": getattr(model_info, "author", None) or "",
        "pipeline_tag": getattr(model_info, "pipeline_tag", None) or "",
        "library_name": getattr(model_info, "library_name", None) or "",
        "downloads": getattr(model_info, "downloads", 0) or 0,
        "likes": getattr(model_info, "likes", 0) or 0,
        "private": getattr(model_info, "private", False) or False,
        "gated": getattr(model_info, "gated", False) or False,
        "tags": tags,
        "created_at": created_at,
        "last_modified": last_modified,
        "readme_content": readme_content,
        "readme_length": readme_length,
        "has_readme": has_readme,
        "fetched_at": now,
        "readme_fetched": readme_content is not None,
        "raw_metadata": json.dumps({
            "id": model_id,
            "author": getattr(model_info, "author", None),
            "pipeline_tag": getattr(model_info, "pipeline_tag", None),
            "library_name": getattr(model_info, "library_name", None),
            "downloads": getattr(model_info, "downloads", 0),
            "likes": getattr(model_info, "likes", 0),
            "tags": tags,
        }),
    }


# =============================================================================
# HuggingFace Capture - Two-Phase Fetch with Caching
# =============================================================================


MIN_README_LENGTH = 100  # Minimum README length to be considered "informative"


class HFCapture:
    """Captures HuggingFace datasets/models to Iceberg with two-phase fetch.

    Phase 1: Fetch list from HF API, check cache for existing records
    Phase 2: For uncached items, fetch README content via DatasetCard/ModelCard

    This avoids redundant API calls by caching in Iceberg, and enables
    quality filtering by README content richness.

    Usage:
        capture = HFCapture()

        # Get datasets with rich content (cached or fresh)
        datasets = await capture.get_rich_datasets(limit=5, min_readme_length=100)

        # Get models with rich content
        models = await capture.get_rich_models(limit=5, min_readme_length=100)
    """

    def __init__(
        self,
        namespace: str = "raw",
    ):
        """Initialize HF capture.

        Args:
            namespace: Iceberg namespace for tables.
        """
        self._namespace = namespace
        self._catalog = None
        self._datasets_table = None
        self._models_table = None

    def _get_catalog(self):
        """Get or create the Iceberg catalog."""
        if self._catalog is None:
            from gaius.hx.catalog import get_catalog
            from gaius.hx.config import get_hx_config

            config = get_hx_config()
            self._catalog = get_catalog(config)
        return self._catalog

    def _get_datasets_table(self):
        """Get or create the HF datasets table."""
        if self._datasets_table is None:
            self._datasets_table = get_hf_datasets_table(
                self._get_catalog(),
                namespace=self._namespace,
            )
        return self._datasets_table

    def _get_models_table(self):
        """Get or create the HF models table."""
        if self._models_table is None:
            self._models_table = get_hf_models_table(
                self._get_catalog(),
                namespace=self._namespace,
            )
        return self._models_table

    async def get_rich_datasets(
        self,
        limit: int = 5,
        fetch_batch: int = 50,
        min_readme_length: int = MIN_README_LENGTH,
    ) -> list[dict[str, Any]]:
        """Get datasets with rich README content.

        Two-phase fetch:
        1. Fetch larger batch from HF API
        2. Check Iceberg cache for existing records with README
        3. For uncached items, fetch README via DatasetCard
        4. Store new records in Iceberg
        5. Return top N with richest content

        Args:
            limit: Number of rich datasets to return.
            fetch_batch: Number of datasets to fetch from HF API.
            min_readme_length: Minimum README length to qualify as "rich".

        Returns:
            List of dataset records with README content, sorted by richness.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()

        # Phase 1: Fetch list from HF API
        def fetch_hf_list():
            from huggingface_hub import HfApi
            api = HfApi()
            return list(api.list_datasets(
                sort="createdAt",
                direction=-1,
                limit=fetch_batch,
            ))

        hf_datasets = await loop.run_in_executor(None, fetch_hf_list)
        logger.info(f"HFCapture: fetched {len(hf_datasets)} datasets from HF API")

        # Phase 1b: Check cache for existing records
        table = self._get_datasets_table()
        cached_ids = set()

        def get_cached_ids():
            import pyarrow.compute as pc
            # Get dataset_ids from cache
            try:
                scan = table.scan(selected_fields=("dataset_id", "has_readme", "readme_length"))
                df = scan.to_arrow()
                if len(df) > 0:
                    return {row["dataset_id"].as_py(): {
                        "has_readme": row["has_readme"].as_py(),
                        "readme_length": row["readme_length"].as_py() or 0,
                    } for row in df.to_pylist()}
            except Exception as e:
                logger.warning(f"Failed to read cache: {e}")
            return {}

        cached = await loop.run_in_executor(None, get_cached_ids)
        logger.info(f"HFCapture: {len(cached)} datasets in cache")

        # Separate into cached (with good README) and uncached
        good_cached = []
        needs_fetch = []

        for ds in hf_datasets:
            ds_id = ds.id
            if ds_id in cached:
                cache_info = cached[ds_id]
                if cache_info.get("has_readme") and cache_info.get("readme_length", 0) >= min_readme_length:
                    good_cached.append(ds_id)
                # If cached but no good README, skip re-fetching (already tried)
            else:
                needs_fetch.append(ds)

        logger.info(f"HFCapture: {len(good_cached)} cached with README, {len(needs_fetch)} need fetch")

        # Phase 2: Fetch README for uncached items
        def fetch_readme(ds_info):
            """Fetch README content for a dataset."""
            try:
                from huggingface_hub import DatasetCard
                card = DatasetCard.load(ds_info.id)
                # Extract content after YAML frontmatter
                content = card.content
                if "---" in content:
                    parts = content.split("---")
                    if len(parts) >= 3:
                        readme_content = parts[2].strip()
                    else:
                        readme_content = content
                else:
                    readme_content = content.strip()
                return (ds_info, readme_content)
            except Exception as e:
                logger.debug(f"No README for {ds_info.id}: {e}")
                return (ds_info, None)

        # Fetch in parallel (limit concurrency)
        new_records = []
        if needs_fetch:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [loop.run_in_executor(executor, fetch_readme, ds) for ds in needs_fetch[:20]]
                results = await asyncio.gather(*futures, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException):
                    continue
                ds_info, readme_content = result
                record = hf_dataset_to_record(ds_info, readme_content)
                new_records.append(record)

            # Store new records in Iceberg
            if new_records:
                def write_records():
                    arrow_table = build_hf_datasets_arrow_table(new_records)
                    table.append(arrow_table)
                    logger.info(f"HFCapture: wrote {len(new_records)} dataset records to Iceberg")

                await loop.run_in_executor(None, write_records)

        # Combine cached and new, filter by README quality
        rich_datasets = []

        # Add newly fetched with good README
        for rec in new_records:
            if rec.get("has_readme") and rec.get("readme_length", 0) >= min_readme_length:
                rich_datasets.append(rec)

        # If not enough, fetch cached records
        if len(rich_datasets) < limit and good_cached:
            def get_cached_records():
                import pyarrow.compute as pc
                try:
                    # Filter for good cached IDs
                    scan = table.scan(
                        row_filter=pc.field("has_readme") == True,
                    )
                    df = scan.to_arrow().to_pylist()
                    return [r for r in df if r["dataset_id"] in good_cached]
                except Exception:
                    return []

            cached_records = await loop.run_in_executor(None, get_cached_records)
            rich_datasets.extend(cached_records)

        # Sort by README length descending, take top N
        rich_datasets.sort(key=lambda r: r.get("readme_length", 0), reverse=True)
        return rich_datasets[:limit]

    async def get_rich_models(
        self,
        limit: int = 5,
        fetch_batch: int = 50,
        min_readme_length: int = MIN_README_LENGTH,
        filter_tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get models with rich README content.

        Two-phase fetch similar to get_rich_datasets.

        Args:
            limit: Number of rich models to return.
            fetch_batch: Number of models to fetch from HF API.
            min_readme_length: Minimum README length to qualify as "rich".
            filter_tag: Optional tag filter (e.g., "text-generation").

        Returns:
            List of model records with README content, sorted by richness.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()

        # Phase 1: Fetch list from HF API
        def fetch_hf_list():
            from huggingface_hub import HfApi
            api = HfApi()
            kwargs = {
                "sort": "lastModified",
                "direction": -1,
                "limit": fetch_batch,
            }
            if filter_tag:
                kwargs["filter"] = filter_tag
            return list(api.list_models(**kwargs))

        hf_models = await loop.run_in_executor(None, fetch_hf_list)
        logger.info(f"HFCapture: fetched {len(hf_models)} models from HF API")

        # Phase 1b: Check cache for existing records
        table = self._get_models_table()

        def get_cached_ids():
            try:
                scan = table.scan(selected_fields=("model_id", "has_readme", "readme_length"))
                df = scan.to_arrow()
                if len(df) > 0:
                    return {row["model_id"].as_py(): {
                        "has_readme": row["has_readme"].as_py(),
                        "readme_length": row["readme_length"].as_py() or 0,
                    } for row in df.to_pylist()}
            except Exception as e:
                logger.warning(f"Failed to read cache: {e}")
            return {}

        cached = await loop.run_in_executor(None, get_cached_ids)
        logger.info(f"HFCapture: {len(cached)} models in cache")

        # Separate into cached (with good README) and uncached
        good_cached = []
        needs_fetch = []

        for m in hf_models:
            m_id = m.id
            if m_id in cached:
                cache_info = cached[m_id]
                if cache_info.get("has_readme") and cache_info.get("readme_length", 0) >= min_readme_length:
                    good_cached.append(m_id)
            else:
                needs_fetch.append(m)

        logger.info(f"HFCapture: {len(good_cached)} cached with README, {len(needs_fetch)} need fetch")

        # Phase 2: Fetch README for uncached items
        def fetch_readme(model_info):
            """Fetch README content for a model."""
            try:
                from huggingface_hub import ModelCard
                card = ModelCard.load(model_info.id)
                content = card.content
                if "---" in content:
                    parts = content.split("---")
                    if len(parts) >= 3:
                        readme_content = parts[2].strip()
                    else:
                        readme_content = content
                else:
                    readme_content = content.strip()
                return (model_info, readme_content)
            except Exception as e:
                logger.debug(f"No README for {model_info.id}: {e}")
                return (model_info, None)

        # Fetch in parallel (limit concurrency)
        new_records = []
        if needs_fetch:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [loop.run_in_executor(executor, fetch_readme, m) for m in needs_fetch[:20]]
                results = await asyncio.gather(*futures, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException):
                    continue
                model_info, readme_content = result
                record = hf_model_to_record(model_info, readme_content)
                new_records.append(record)

            # Store new records in Iceberg
            if new_records:
                def write_records():
                    arrow_table = build_hf_models_arrow_table(new_records)
                    table.append(arrow_table)
                    logger.info(f"HFCapture: wrote {len(new_records)} model records to Iceberg")

                await loop.run_in_executor(None, write_records)

        # Combine cached and new, filter by README quality
        rich_models = []

        # Add newly fetched with good README
        for rec in new_records:
            if rec.get("has_readme") and rec.get("readme_length", 0) >= min_readme_length:
                rich_models.append(rec)

        # If not enough, fetch cached records
        if len(rich_models) < limit and good_cached:
            def get_cached_records():
                import pyarrow.compute as pc
                try:
                    scan = table.scan(
                        row_filter=pc.field("has_readme") == True,
                    )
                    df = scan.to_arrow().to_pylist()
                    return [r for r in df if r["model_id"] in good_cached]
                except Exception:
                    return []

            cached_records = await loop.run_in_executor(None, get_cached_records)
            rich_models.extend(cached_records)

        # Sort by README length descending, take top N
        rich_models.sort(key=lambda r: r.get("readme_length", 0), reverse=True)
        return rich_models[:limit]


# Module-level singleton
_hf_capture: HFCapture | None = None


def get_hf_capture() -> HFCapture:
    """Get or create the HF capture singleton."""
    global _hf_capture
    if _hf_capture is None:
        _hf_capture = HFCapture()
    return _hf_capture
