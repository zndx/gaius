"""Storage Backend Configuration.

Manages the storage backend for Iceberg data files (parquet).
Supports RustFS (S3-compatible) as primary and filesystem as fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.io import FileIO

from gaius.hx.config import HxConfig, get_hx_config

logger = logging.getLogger(__name__)


class StorageBackend(Enum):
    """Supported storage backends."""
    RUSTFS = "rustfs"      # S3-compatible RustFS
    FILESYSTEM = "fs"    # Local filesystem


@dataclass
class StorageConfig:
    """Storage configuration for Iceberg data files."""

    backend: StorageBackend
    warehouse_path: str

    # RustFS settings (when backend == RUSTFS)
    endpoint: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    bucket: str | None = None
    prefix: str | None = None

    # Filesystem settings (when backend == FILESYSTEM)
    local_path: Path | None = None


def get_storage_config(
    config: HxConfig | None = None,
    check_rustfs: bool = True,
) -> StorageConfig:
    """Get storage configuration. Signals RustFS is required; no filesystem fallback.

    Args:
        config: Optional HxConfig. If None, loads from global config.
        check_rustfs: If True, probe RustFS and fail-fast when it is down.

    Returns:
        StorageConfig with appropriate backend settings.
    """
    if config is None:
        config = get_hx_config()

    if config.use_rustfs:
        if check_rustfs and not _check_rustfs_available(config):
            raise RuntimeError(
                "#HX.00000001.NORUSTFS Signals RustFS is required for "
                f"HX at {config.rustfs_endpoint} (no filesystem fallback).\n"
                "  Try: just signals-ready; confirm :9010 rustfsadmin\n"
                "  devenv RustFS is not a warehouse"
            )
        return _get_rustfs_config(config)
    else:
        return _get_filesystem_config(config)


def _get_rustfs_config(config: HxConfig) -> StorageConfig:
    """Get RustFS storage configuration."""
    import os

    return StorageConfig(
        backend=StorageBackend.RUSTFS,
        warehouse_path=config.warehouse_path,
        endpoint=config.s3_endpoint,
        access_key=config.rustfs_access_key or os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin"),
        secret_key=config.rustfs_secret_key or os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin"),
        bucket=config.rustfs_bucket,
        prefix=config.rustfs_prefix,
    )


def _get_filesystem_config(config: HxConfig) -> StorageConfig:
    """Get filesystem storage configuration."""
    local_path = Path(config.kb_root) / config.filesystem_warehouse

    return StorageConfig(
        backend=StorageBackend.FILESYSTEM,
        warehouse_path=str(local_path),
        local_path=local_path,
    )


def _check_rustfs_available(config: HxConfig) -> bool:
    """Check if RustFS is available and accessible.

    Returns:
        True if RustFS is available, False otherwise.
    """
    import os

    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available for RustFS health check")
        return True  # Assume available

    try:
        # RustFS health endpoint
        endpoint = config.s3_endpoint.rstrip("/")
        response = httpx.get(f"{endpoint}/health", timeout=2.0)
        return response.status_code == 200
    except Exception as e:
        logger.debug(f"RustFS health check failed: {e}")
        return False


def ensure_storage_exists(storage: StorageConfig) -> None:
    """Ensure the storage location exists.

    For RustFS: Creates the bucket if it doesn't exist.
    For filesystem: Creates the directory if it doesn't exist.
    """
    if storage.backend == StorageBackend.FILESYSTEM:
        if storage.local_path:
            storage.local_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured filesystem warehouse exists: {storage.local_path}")
    elif storage.backend == StorageBackend.RUSTFS:
        _ensure_rustfs_bucket(storage)


def _ensure_rustfs_bucket(storage: StorageConfig) -> None:
    """Ensure the RustFS bucket exists."""
    try:
        import s3fs
    except ImportError:
        logger.warning("s3fs not installed, cannot ensure bucket exists")
        return

    try:
        fs = s3fs.S3FileSystem(
            endpoint_url=storage.endpoint,
            key=storage.access_key,
            secret=storage.secret_key,
        )

        if not fs.exists(storage.bucket):
            logger.info(f"Creating RustFS bucket: {storage.bucket}")
            fs.mkdir(storage.bucket)
        else:
            logger.debug(f"RustFS bucket exists: {storage.bucket}")

        # Ensure prefix directory exists (if configured)
        if storage.prefix is None:
            return
        prefix_path = f"{storage.bucket}/{storage.prefix.rstrip('/')}"
        if not fs.exists(prefix_path):
            logger.info(f"Creating RustFS prefix: {prefix_path}")
            fs.mkdir(prefix_path)

    except Exception as e:
        logger.error(f"Failed to ensure RustFS bucket: {e}")
        raise
