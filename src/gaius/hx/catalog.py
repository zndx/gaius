"""PyIceberg catalog: Signals Polarisfork (Iceberg REST) + RustFS warehouse.

PostgreSQL SqlCatalog is tests-only. Polarisfork is started by
``signals-polaris.service`` (``signals.target``), not Gaius.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog

from gaius.hx.config import HxConfig, get_hx_config

logger = logging.getLogger(__name__)


GURU_NOPOLARIS = "#HX.00000002.NOPOLARIS"


class CatalogType(Enum):
    """Supported catalog types."""

    REST = "rest"  # Signals Polarisfork Iceberg REST
    SQL = "sql"  # Tests only; not a lattice warehouse catalog


# Module-level singleton
_catalog: Catalog | None = None


def get_catalog(
    config: HxConfig | None = None,
    catalog_type: CatalogType | None = None,
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

    if catalog_type is None:
        raw = (config.catalog_type or "rest").strip().lower()
        catalog_type = CatalogType.SQL if raw == "sql" else CatalogType.REST

    if catalog_type == CatalogType.REST:
        _catalog = _create_rest_catalog(config)
    elif catalog_type == CatalogType.SQL:
        _catalog = _create_sql_catalog(config)
    else:
        raise ValueError(f"Unsupported catalog type: {catalog_type}")

    return _catalog


def _create_rest_catalog(config: HxConfig) -> Catalog:
    """Connect to Signals Polarisfork (Iceberg REST) with RustFS file I/O."""
    try:
        from pyiceberg.catalog import load_catalog
    except ImportError as e:
        raise ImportError(
            "PyIceberg is required for Polarisfork REST catalog. "
            "Install with: uv add 'pyiceberg[s3]'"
        ) from e

    uri = config.polaris_uri.rstrip("/")
    properties = {
        "type": "rest",
        "uri": uri,
        "warehouse": config.catalog_name,
        "credential": config.polaris_credential,
        "scope": config.polaris_scope,
        # PyIceberg defaults this to vended-credentials. Polarisfork has no
        # STS for llm.generations — client FileIO uses RustFS keys instead.
        "header.X-Iceberg-Access-Delegation": "",
        **_get_s3_properties(config),
    }
    logger.info(
        "Polarisfork REST catalog uri=%s warehouse=%s rustfs=%s",
        uri,
        config.catalog_name,
        config.s3_endpoint,
    )
    try:
        catalog = load_catalog(config.catalog_name, **properties)
    except Exception as e:
        raise RuntimeError(
            f"{GURU_NOPOLARIS} Polarisfork REST catalog is not reachable at {uri}.\n"
            "  Start: sudo systemctl start signals-polaris.service\n"
            "  (PartOf=signals.target; not a Gaius process)\n"
            f"  Cause: {e}"
        ) from e

    for ns in (config.namespace, "llm"):
        _ensure_namespace(catalog, ns)
    return catalog


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

    # Ensure required namespaces exist
    # config.namespace is typically "raw"; "llm" is needed for LLM generation storage
    REQUIRED_NAMESPACES = [config.namespace, "llm"]
    for ns in REQUIRED_NAMESPACES:
        _ensure_namespace(catalog, ns)

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
        properties["s3.access-key-id"] = os.environ.get(
            "GAIUS_MINIO_ACCESS_KEY",
            os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin"),
        )
        properties["s3.secret-access-key"] = os.environ.get(
            "GAIUS_MINIO_SECRET_KEY",
            os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin"),
        )

    return properties


def _ensure_namespace(catalog: Catalog, namespace: str) -> None:
    """Ensure the namespace exists (nested Polarisfork namespaces included)."""
    parts = tuple(p for p in namespace.split(".") if p)
    listed = set(catalog.list_namespaces())
    for i in range(1, len(parts) + 1):
        ns = parts[:i]
        if ns in listed or (ns,) in listed:
            continue
        logger.info("Creating Polarisfork namespace %s", ".".join(ns))
        catalog.create_namespace(ns)
        listed.add(ns)


def reset_catalog() -> None:
    """Reset the catalog singleton (for testing)."""
    global _catalog
    _catalog = None
