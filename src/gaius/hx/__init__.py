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
]
