"""Dataset storage backend for S3/RustFS."""

import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image

# minio-py is the S3 client library (a hard dependency in pyproject); it speaks
# to Signals' RustFS. No availability flag: fail-fast at import.
from minio import Minio
from minio.error import S3Error


@dataclass
class ArtifactInfo:
    """Information about a stored artifact."""

    path: str
    content_hash: str
    size_bytes: int
    etag: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
        }


@dataclass
class DatasetManifest:
    """Manifest for a dataset stored in S3."""

    dataset_id: str
    version: str
    created_at: str
    storage: dict
    artifacts: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "created_at": self.created_at,
            "storage": self.storage,
            "artifacts": self.artifacts,
            "stats": self.stats,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class DatasetStorage:
    """Storage backend for dataset artifacts.

    Supports both local filesystem and RustFS/S3 backends.
    """

    def __init__(
        self,
        backend: str = "filesystem",
        bucket: str = "zndx-gaius",
        prefix: str = "datasets",
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: bool = False,
    ):
        self.backend = backend
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint = endpoint or os.getenv("GAIUS_KB_ENDPOINT", "localhost:9010")
        self.access_key = access_key or os.getenv("GAIUS_KB_ACCESS_KEY", "rustfsadmin")
        self.secret_key = secret_key or os.getenv("GAIUS_KB_SECRET_KEY", "rustfsadmin")
        self.secure = secure

        self._client: Optional[Minio] = None

    def _get_client(self) -> Minio:
        """Get or create the RustFS (S3) client."""
        if self._client is None:
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    def _hash_content(self, content: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return f"sha256:{hashlib.sha256(content).hexdigest()}"

    def _get_s3_key(self, dataset_id: str, path: str) -> str:
        """Build S3 key from dataset ID and relative path."""
        return f"{self.prefix}/{dataset_id}/{path}"

    def upload_bytes(
        self,
        dataset_id: str,
        path: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> ArtifactInfo:
        """Upload bytes to S3.

        Args:
            dataset_id: Dataset identifier
            path: Relative path within dataset
            content: Bytes to upload
            content_type: MIME type

        Returns:
            ArtifactInfo with hash and size
        """
        client = self._get_client()
        key = self._get_s3_key(dataset_id, path)
        content_hash = self._hash_content(content)

        # Upload with retry
        for attempt in range(3):
            try:
                result = client.put_object(
                    self.bucket,
                    key,
                    io.BytesIO(content),
                    length=len(content),
                    content_type=content_type,
                )
                return ArtifactInfo(
                    path=path,
                    content_hash=content_hash,
                    size_bytes=len(content),
                    etag=result.etag,
                )
            except S3Error as e:
                if attempt == 2:
                    raise
                # Retry on transient errors

        raise RuntimeError("Upload failed after retries")

    def upload_image(
        self,
        dataset_id: str,
        path: str,
        image: Image.Image,
        format: str = "PNG",
    ) -> ArtifactInfo:
        """Upload PIL Image to S3.

        Args:
            dataset_id: Dataset identifier
            path: Relative path (e.g., "images/flow_001.png")
            image: PIL Image object
            format: Image format (PNG, JPEG, etc.)

        Returns:
            ArtifactInfo with hash and size
        """
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        content = buffer.getvalue()

        content_type = f"image/{format.lower()}"
        return self.upload_bytes(dataset_id, path, content, content_type)

    def upload_json(
        self,
        dataset_id: str,
        path: str,
        data: dict | list,
    ) -> ArtifactInfo:
        """Upload JSON data to S3.

        Args:
            dataset_id: Dataset identifier
            path: Relative path (e.g., "annotations.json")
            data: JSON-serializable data

        Returns:
            ArtifactInfo with hash and size
        """
        content = json.dumps(data, indent=2).encode("utf-8")
        return self.upload_bytes(dataset_id, path, content, "application/json")

    def create_manifest(
        self,
        dataset_id: str,
        version: str,
        annotations_info: ArtifactInfo,
        image_infos: list[ArtifactInfo],
        stats: dict,
    ) -> DatasetManifest:
        """Create a dataset manifest.

        Args:
            dataset_id: Dataset identifier
            version: Dataset version string
            annotations_info: Info about annotations.json
            image_infos: List of info about uploaded images
            stats: Dataset statistics

        Returns:
            DatasetManifest object
        """
        total_image_size = sum(info.size_bytes for info in image_infos)

        return DatasetManifest(
            dataset_id=dataset_id,
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            storage={
                "backend": self.backend,
                "bucket": self.bucket,
                "prefix": f"{self.prefix}/{dataset_id}/",
                "endpoint": self.endpoint,
            },
            artifacts={
                "annotations": annotations_info.to_dict(),
                "images": {
                    "count": len(image_infos),
                    "total_size_bytes": total_image_size,
                    "files": [info.to_dict() for info in image_infos],
                },
            },
            stats=stats,
        )

    def write_manifest_to_kb(
        self,
        manifest: DatasetManifest,
        kb_path: Path,
    ) -> Path:
        """Write manifest to KB directory.

        Args:
            manifest: Dataset manifest
            kb_path: Path to KB dataset directory

        Returns:
            Path to written manifest file
        """
        kb_path.mkdir(parents=True, exist_ok=True)
        manifest_path = kb_path / "manifest.json"
        manifest_path.write_text(manifest.to_json())
        return manifest_path

    def verify_upload(
        self,
        dataset_id: str,
        path: str,
        expected_hash: str,
    ) -> bool:
        """Verify an uploaded file by re-downloading and hashing.

        Args:
            dataset_id: Dataset identifier
            path: Relative path within dataset
            expected_hash: Expected SHA-256 hash

        Returns:
            True if verification passes
        """
        client = self._get_client()
        key = self._get_s3_key(dataset_id, path)

        try:
            response = client.get_object(self.bucket, key)
            content = response.read()
            actual_hash = self._hash_content(content)
            return actual_hash == expected_hash
        except S3Error:
            return False
        finally:
            response.close()
            response.release_conn()
