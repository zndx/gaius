"""Storage Backend Configuration.

Manages the storage backend for Iceberg data files (parquet).
Supports MinIO (S3-compatible) as primary and filesystem as fallback.
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
    MINIO = "minio"      # S3-compatible MinIO
    FILESYSTEM = "fs"    # Local filesystem


@dataclass
class StorageConfig:
    """Storage configuration for Iceberg data files."""

    backend: StorageBackend
    warehouse_path: str

    # MinIO settings (when backend == MINIO)
    endpoint: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    bucket: str | None = None
    prefix: str | None = None

    # Filesystem settings (when backend == FILESYSTEM)
    local_path: Path | None = None


def get_storage_config(
    config: HxConfig | None = None,
    check_minio: bool = True,
) -> StorageConfig:
    """Get storage configuration, with automatic MinIO fallback.

    Args:
        config: Optional HxConfig. If None, loads from global config.
        check_minio: If True, check MinIO availability and fallback to filesystem.

    Returns:
        StorageConfig with appropriate backend settings.
    """
    if config is None:
        config = get_hx_config()

    if config.use_minio:
        if check_minio and not _check_minio_available(config):
            logger.warning(
                f"MinIO not available at {config.minio_endpoint}, "
                f"falling back to filesystem at {config.filesystem_warehouse}"
            )
            return _get_filesystem_config(config)
        return _get_minio_config(config)
    else:
        return _get_filesystem_config(config)


def _get_minio_config(config: HxConfig) -> StorageConfig:
    """Get MinIO storage configuration."""
    import os

    return StorageConfig(
        backend=StorageBackend.MINIO,
        warehouse_path=config.warehouse_path,
        endpoint=config.s3_endpoint,
        access_key=config.minio_access_key or os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        secret_key=config.minio_secret_key or os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"),
        bucket=config.minio_bucket,
        prefix=config.minio_prefix,
    )


def _get_filesystem_config(config: HxConfig) -> StorageConfig:
    """Get filesystem storage configuration."""
    local_path = Path(config.kb_root) / config.filesystem_warehouse

    return StorageConfig(
        backend=StorageBackend.FILESYSTEM,
        warehouse_path=str(local_path),
        local_path=local_path,
    )


def _check_minio_available(config: HxConfig) -> bool:
    """Check if MinIO is available and accessible.

    Returns:
        True if MinIO is available, False otherwise.
    """
    import os

    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available for MinIO health check")
        return True  # Assume available

    try:
        # MinIO health endpoint
        endpoint = config.s3_endpoint.rstrip("/")
        response = httpx.get(f"{endpoint}/minio/health/live", timeout=2.0)
        return response.status_code == 200
    except Exception as e:
        logger.debug(f"MinIO health check failed: {e}")
        return False


def ensure_storage_exists(storage: StorageConfig) -> None:
    """Ensure the storage location exists.

    For MinIO: Creates the bucket if it doesn't exist.
    For filesystem: Creates the directory if it doesn't exist.
    """
    if storage.backend == StorageBackend.FILESYSTEM:
        if storage.local_path:
            storage.local_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured filesystem warehouse exists: {storage.local_path}")
    elif storage.backend == StorageBackend.MINIO:
        _ensure_minio_bucket(storage)


def _ensure_minio_bucket(storage: StorageConfig) -> None:
    """Ensure the MinIO bucket exists."""
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
            logger.info(f"Creating MinIO bucket: {storage.bucket}")
            fs.mkdir(storage.bucket)
        else:
            logger.debug(f"MinIO bucket exists: {storage.bucket}")

        # Ensure prefix directory exists (if configured)
        if storage.prefix is None:
            return
        prefix_path = f"{storage.bucket}/{storage.prefix.rstrip('/')}"
        if not fs.exists(prefix_path):
            logger.info(f"Creating MinIO prefix: {prefix_path}")
            fs.mkdir(prefix_path)

    except Exception as e:
        logger.error(f"Failed to ensure MinIO bucket: {e}")
        raise
