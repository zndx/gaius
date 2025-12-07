"""HX Configuration management.

Provides access to HX-specific configuration from the main Gaius config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.core.config import GaiusConfig, HxConfig as CoreHxConfig


@dataclass
class HxConfig:
    """Gaius HX configuration with computed properties.

    This is a convenience wrapper around the core HxConfig that adds
    computed properties like the full warehouse path.
    """

    enabled: bool = True
    catalog_name: str = "gaius_hx"
    namespace: str = "raw"

    # MinIO storage
    use_minio: bool = True
    minio_endpoint: str = "localhost:9010"
    minio_bucket: str = "zndx-gaius"
    minio_prefix: str = "hx/"
    minio_access_key: str = ""
    minio_secret_key: str = ""

    # Filesystem fallback
    filesystem_warehouse: str = ".iceberg"
    kb_root: str = "build/dev"

    # Lineage
    lineage_enabled: bool = True
    lineage_graph_name: str = "gaius_hx"
    materialize_graph: bool = True

    # Database URL for catalog
    database_url: str = ""

    @property
    def warehouse_path(self) -> str:
        """Get the warehouse path for Iceberg.

        Returns S3 path if MinIO enabled, otherwise filesystem path.
        """
        if self.use_minio:
            # s3://bucket/prefix
            prefix = self.minio_prefix.rstrip("/")
            return f"s3://{self.minio_bucket}/{prefix}"
        else:
            # Filesystem path under KB root
            from pathlib import Path
            return str(Path(self.kb_root) / self.filesystem_warehouse)

    @property
    def s3_endpoint(self) -> str:
        """Get the S3 endpoint URL for MinIO."""
        if "://" in self.minio_endpoint:
            return self.minio_endpoint
        return f"http://{self.minio_endpoint}"


def get_hx_config(config: GaiusConfig | None = None) -> HxConfig:
    """Get HX configuration from main Gaius config.

    Args:
        config: Optional GaiusConfig. If None, loads from global config.

    Returns:
        HxConfig with all settings populated.
    """
    if config is None:
        from gaius.core.config import get_config
        config = get_config()

    hx = config.hx
    return HxConfig(
        enabled=hx.enabled,
        catalog_name=hx.iceberg.catalog,
        namespace=hx.iceberg.namespace,
        use_minio=hx.iceberg.use_minio,
        minio_endpoint=hx.minio.endpoint,
        minio_bucket=hx.minio.bucket,
        minio_prefix=hx.minio.prefix,
        minio_access_key=hx.minio.access_key,
        minio_secret_key=hx.minio.secret_key,
        filesystem_warehouse=hx.filesystem.warehouse,
        kb_root=config.kb.root,
        lineage_enabled=hx.lineage.enabled,
        lineage_graph_name=hx.lineage.graph_name,
        materialize_graph=hx.lineage.materialize_graph,
        database_url=config.database.url,
    )
