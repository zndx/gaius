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
    catalog_name: str = "signals"
    namespace: str = "raw"
    catalog_type: str = "rest"
    polaris_uri: str = "http://127.0.0.1:8181/api/catalog"
    polaris_credential: str = "admin:admin"
    polaris_scope: str = "PRINCIPAL_ROLE:ALL"

    # S3-compatible storage (Signals RustFS; env names keep MINIO_*)
    use_minio: bool = True
    minio_endpoint: str = "127.0.0.1:9010"
    minio_bucket: str = "signals-dataproducts"
    minio_prefix: str = "iceberg/"
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

        Returns S3 path if object storage enabled, otherwise filesystem path.
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
        """Get the S3 endpoint URL (Signals RustFS)."""
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
    import os

    endpoint = os.environ.get("GAIUS_MINIO_ENDPOINT") or hx.minio.endpoint
    bucket = os.environ.get("GAIUS_MINIO_BUCKET") or hx.minio.bucket
    prefix = (
        os.environ.get("GAIUS_HX_PREFIX")
        or os.environ.get("GAIUS_MINIO_PREFIX")
        or hx.minio.prefix
    )
    access = (
        os.environ.get("GAIUS_MINIO_ACCESS_KEY")
        or os.environ.get("RUSTFS_ACCESS_KEY")
        or hx.minio.access_key
    )
    secret = (
        os.environ.get("GAIUS_MINIO_SECRET_KEY")
        or os.environ.get("RUSTFS_SECRET_KEY")
        or hx.minio.secret_key
    )
    catalog_name = os.environ.get("GAIUS_HX_CATALOG_NAME") or hx.iceberg.catalog
    catalog_type = (
        os.environ.get("GAIUS_HX_CATALOG_TYPE") or "rest"
    ).strip().lower()
    polaris_uri = os.environ.get("GAIUS_HX_POLARIS_URI") or (
        "http://127.0.0.1:8181/api/catalog"
    )
    polaris_credential = os.environ.get("GAIUS_HX_POLARIS_CREDENTIAL") or "admin:admin"
    return HxConfig(
        enabled=hx.enabled,
        catalog_name=catalog_name,
        namespace=hx.iceberg.namespace,
        catalog_type=catalog_type,
        polaris_uri=polaris_uri,
        polaris_credential=polaris_credential,
        use_minio=hx.iceberg.use_minio,
        minio_endpoint=endpoint,
        minio_bucket=bucket,
        minio_prefix=prefix,
        minio_access_key=access,
        minio_secret_key=secret,
        filesystem_warehouse=hx.filesystem.warehouse,
        kb_root=config.kb.root,
        lineage_enabled=hx.lineage.enabled,
        lineage_graph_name=hx.lineage.graph_name,
        materialize_graph=hx.lineage.materialize_graph,
        database_url=config.database.url,
    )
