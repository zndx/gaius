"""PyIceberg Catalog Configuration.

Sets up the Iceberg catalog using PostgreSQL as the metadata store.
Supports MinIO (S3-compatible) as primary storage with filesystem fallback.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog

from gaius.hx.config import HxConfig, get_hx_config

logger = logging.getLogger(__name__)


class CatalogType(Enum):
    """Supported catalog types."""
    SQL = "sql"  # PostgreSQL-backed catalog
    REST = "rest"  # Future: REST catalog


# Module-level singleton
_catalog: Catalog | None = None


def get_catalog(
    config: HxConfig | None = None,
    catalog_type: CatalogType = CatalogType.SQL,
    force_reload: bool = False,
) -> Catalog:
    """Get or create the Iceberg catalog.

    Args:
        config: Optional HxConfig. If None, loads from global config.
        catalog_type: Type of catalog to create (default: SQL/PostgreSQL).
        force_reload: If True, recreate the catalog even if cached.

    Returns:
        PyIceberg Catalog instance.

    Raises:
        ImportError: If pyiceberg is not installed.
        ConnectionError: If unable to connect to catalog backend.
    """
    global _catalog

    if _catalog is not None and not force_reload:
        return _catalog

    if config is None:
        config = get_hx_config()

    if catalog_type == CatalogType.SQL:
        _catalog = _create_sql_catalog(config)
    else:
        raise ValueError(f"Unsupported catalog type: {catalog_type}")

    return _catalog


def _create_sql_catalog(config: HxConfig) -> Catalog:
    """Create a PostgreSQL-backed Iceberg catalog.

    The SQL catalog uses PostgreSQL to store table metadata while
    data files (parquet) are stored in MinIO or filesystem.
    """
    try:
        from pyiceberg.catalog.sql import SqlCatalog
    except ImportError as e:
        # More specific error message based on the actual missing dependency
        error_msg = str(e)
        if "sqlalchemy" in error_msg.lower():
            raise ImportError(
                "SQLAlchemy required for PyIceberg SQL catalog. "
                "Install with: uv add 'pyiceberg[sql-postgres]'"
            ) from e
        raise ImportError(
            f"PyIceberg SQL catalog not available: {e}. "
            "Ensure pyiceberg[sql-postgres] is installed."
        ) from e

    # Build catalog properties
    properties = {
        "uri": _postgres_uri_to_jdbc(config.database_url),
        "warehouse": config.warehouse_path,
    }

    # Add S3/MinIO properties if using object storage
    if config.use_minio:
        properties.update(_get_s3_properties(config))

    logger.info(
        f"Creating SQL catalog '{config.catalog_name}' "
        f"with warehouse at {config.warehouse_path}"
    )

    catalog = SqlCatalog(
        name=config.catalog_name,
        **properties,
    )

    # Ensure namespace exists
    _ensure_namespace(catalog, config.namespace)

    return catalog


def _postgres_uri_to_jdbc(uri: str) -> str:
    """Convert postgres:// URI to JDBC format for PyIceberg.

    PyIceberg SQL catalog expects JDBC-style URIs:
    postgresql://host:port/database -> postgresql+psycopg2://host:port/database

    Args:
        uri: PostgreSQL connection URI (postgres://... or postgresql://...)

    Returns:
        SQLAlchemy-compatible connection string.
    """
    # Remove sslmode parameter if present (handle separately)
    if "?" in uri:
        base, params = uri.split("?", 1)
    else:
        base, params = uri, ""

    # Convert postgres:// to postgresql+psycopg2://
    if base.startswith("postgres://"):
        base = base.replace("postgres://", "postgresql+psycopg2://", 1)
    elif base.startswith("postgresql://"):
        base = base.replace("postgresql://", "postgresql+psycopg2://", 1)

    # Re-add params if any (excluding sslmode for now)
    if params:
        # Filter out sslmode for local dev
        param_pairs = [p for p in params.split("&") if not p.startswith("sslmode=")]
        if param_pairs:
            base = f"{base}?{'&'.join(param_pairs)}"

    return base


def _get_s3_properties(config: HxConfig) -> dict:
    """Get S3/MinIO properties for Iceberg file I/O.

    Returns:
        Dictionary of S3 configuration properties.
    """
    properties = {
        "s3.endpoint": config.s3_endpoint,
        "s3.access-key-id": config.minio_access_key,
        "s3.secret-access-key": config.minio_secret_key,
        # MinIO-specific settings
        "s3.path-style-access": "true",
        "s3.region": "us-east-1",  # MinIO default
    }

    # Only add credentials if provided
    if not config.minio_access_key:
        # Use environment variables or default MinIO credentials
        import os
        properties["s3.access-key-id"] = os.environ.get("MINIO_ROOT_USER", "minioadmin")
        properties["s3.secret-access-key"] = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")

    return properties


def _ensure_namespace(catalog: Catalog, namespace: str) -> None:
    """Ensure the namespace exists in the catalog.

    Creates the namespace if it doesn't exist.
    """
    from pyiceberg.catalog import Catalog

    try:
        namespaces = catalog.list_namespaces()
        if (namespace,) not in namespaces:
            logger.info(f"Creating namespace '{namespace}'")
            catalog.create_namespace(namespace)
    except Exception as e:
        logger.warning(f"Could not check/create namespace: {e}")


def reset_catalog() -> None:
    """Reset the catalog singleton (for testing)."""
    global _catalog
    _catalog = None
