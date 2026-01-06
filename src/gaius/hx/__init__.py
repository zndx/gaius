"""Gaius HX - Raw Content Data Lake.

HX (history) stores high-volume raw fetched content in Apache Iceberg
tables, separate from curated KB summaries. This prevents content
acquisition from overwhelming thoughts and summaries with raw data.

Architecture:
    Sources → Iceberg (raw parquet) → Summarization Pipeline → KB (markdown)
                                             ↓
                                     OpenLineage events → AGE graph

Components:
    - catalog: PyIceberg catalog setup with PostgreSQL backend
    - storage: MinIO primary storage with filesystem fallback
    - tables: Iceberg table schemas for raw content
    - writer: IcebergContentStore for writing fetched content
    - reader: IcebergContentReader for querying content
    - exchange: ExchangeCapture for external API request-response pairs
    - lineage: OpenLineage event emission and AGE graph integration
"""

from gaius.hx.config import HxConfig, get_hx_config
from gaius.hx.catalog import get_catalog, CatalogType
from gaius.hx.storage import get_storage_config, StorageBackend
from gaius.hx.tables import RAW_CONTENT_SCHEMA, create_raw_content_table
from gaius.hx.writer import IcebergContentStore
from gaius.hx.reader import IcebergContentReader
from gaius.hx.exchange import ExchangeCapture, ExchangeRecord, get_exchange_capture
from gaius.hx.evidence import EvidenceCapture, EvidenceRecord, get_evidence_capture
from gaius.hx.bookmarks_tables import (
    create_bookmarks_table,
    get_bookmarks_table,
    get_bookmarks_schema,
    write_x_bookmarks_to_iceberg,
)
from gaius.hx.hf_tables import (
    create_hf_datasets_table,
    get_hf_datasets_table,
    get_hf_datasets_schema,
    build_hf_datasets_arrow_table,
    hf_dataset_to_record,
    create_hf_models_table,
    get_hf_models_table,
    get_hf_models_schema,
    build_hf_models_arrow_table,
    hf_model_to_record,
    HFCapture,
    get_hf_capture,
)

__all__ = [
    # Config
    "HxConfig",
    "get_hx_config",
    # Catalog
    "get_catalog",
    "CatalogType",
    # Storage
    "get_storage_config",
    "StorageBackend",
    # Tables
    "RAW_CONTENT_SCHEMA",
    "create_raw_content_table",
    # Read/Write
    "IcebergContentStore",
    "IcebergContentReader",
    # Exchange Capture
    "ExchangeCapture",
    "ExchangeRecord",
    "get_exchange_capture",
    # Evidence Capture (RASE)
    "EvidenceCapture",
    "EvidenceRecord",
    "get_evidence_capture",
    # Bookmarks (multi-source)
    "create_bookmarks_table",
    "get_bookmarks_table",
    "get_bookmarks_schema",
    "write_x_bookmarks_to_iceberg",
    # HuggingFace datasets
    "create_hf_datasets_table",
    "get_hf_datasets_table",
    "get_hf_datasets_schema",
    "build_hf_datasets_arrow_table",
    "hf_dataset_to_record",
    # HuggingFace models
    "create_hf_models_table",
    "get_hf_models_table",
    "get_hf_models_schema",
    "build_hf_models_arrow_table",
    "hf_model_to_record",
    # HuggingFace capture (two-phase fetch)
    "HFCapture",
    "get_hf_capture",
]
