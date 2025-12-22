"""Cloudera Documentation ETL Flow.

Syncs Cloudera documentation from docs.cloudera.com to the KB,
with support for versioning, content hashing, and quarterly archival.

Products supported:
- CSA (Cloudera Streaming Analytics): Flink, SQL Stream Builder
- Kudu: Apache Kudu columnar storage
- Impala: Apache Impala SQL engine
- CFM (Cloudera Flow Management): Apache NiFi

Usage:
    # Sync all configured products
    uv run gaius-cli --cmd "/docs-sync"

    # Sync specific product
    uv run gaius-cli --cmd "/docs-sync csa"

    # Check sync status
    uv run gaius-cli --cmd "/docs-sync status"
"""

from .flow import ClouderaDocsFlow, sync_product, sync_product_smart
from .parallel import ParallelDocProcessor, sync_product_parallel
from .sources import PRODUCT_SOURCES, ProductSource

__all__ = [
    "ClouderaDocsFlow",
    "PRODUCT_SOURCES",
    "ProductSource",
    "ParallelDocProcessor",
    "sync_product",
    "sync_product_parallel",
    "sync_product_smart",
]
