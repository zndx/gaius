"""Minio/S3 storage backend for object storage.

This backend stores KB documents in Minio or S3-compatible object storage,
providing durable, scalable storage suitable for production deployments.

Configuration via environment variables:
    GAIUS_KB_BACKEND=minio
    GAIUS_KB_ENDPOINT=localhost:9010
    GAIUS_KB_ACCESS_KEY=minioadmin
    GAIUS_KB_SECRET_KEY=minioadmin
    GAIUS_KB_BUCKET=zndx-gaius
    GAIUS_KB_SECURE=false  # Use http instead of https for local dev
"""

import io
import os
from datetime import datetime, timezone
from typing import Iterator

from deepagents.backends.protocol import (
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)

from .protocol import KBDocument, StorageBackend, StorageConfig

# Deferred import for faster module load time
_minio_client = None


def _get_minio():
    """Get minio client class (deferred import for faster startup)."""
    global _minio_client
    if _minio_client is None:
        from minio import Minio
        _minio_client = Minio
    return _minio_client


class MinioStorage:
    """Minio/S3 object storage backend.

    Stores KB documents in an S3-compatible object store. Objects are stored
    with keys matching the KB path structure (e.g., "current/topics/kudu.md").

    This backend implements both the deepagents BackendProtocol and Gaius
    StorageBackend extensions for full compatibility.

    Example:
        config = StorageConfig(
            backend_type="minio",
            endpoint="localhost:9010",
            access_key="minioadmin",
            secret_key="minioadmin",
            root="zndx-gaius",  # bucket name
            secure=False,
        )
        storage = MinioStorage(config)
        for doc in storage.iter_documents():
            print(doc.path, doc.title)
    """

    def __init__(self, config: StorageConfig):
        """Initialize Minio storage.

        Args:
            config: Storage configuration with endpoint, credentials, and bucket.
        """
        self._config = config

        Minio = _get_minio()
        self._client = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
        )
        self._bucket = config.root

        # Ensure bucket exists
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    @property
    def config(self) -> StorageConfig:
        """Get the storage configuration."""
        return self._config

    # =========================================================================
    # Deepagents BackendProtocol implementation
    # =========================================================================

    def ls_info(self, path: str) -> list[FileInfo]:
        """List objects in a prefix (directory-like listing)."""
        # Normalize path to prefix
        prefix = path.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        if prefix == "/":
            prefix = ""

        results: list[FileInfo] = []
        seen_dirs: set[str] = set()

        objects = self._client.list_objects(
            self._bucket,
            prefix=prefix,
            recursive=False,
        )

        for obj in objects:
            name = obj.object_name
            if obj.is_dir:
                # Directory marker
                dir_name = name.rstrip("/").split("/")[-1]
                if dir_name not in seen_dirs:
                    seen_dirs.add(dir_name)
                    results.append(
                        FileInfo(
                            path=f"/{name}",
                            is_dir=True,
                            size=0,
                            modified_at="",
                        )
                    )
            else:
                # Regular object
                results.append(
                    FileInfo(
                        path=f"/{name}",
                        is_dir=False,
                        size=obj.size or 0,
                        modified_at=obj.last_modified.isoformat()
                        if obj.last_modified
                        else "",
                    )
                )

        return results

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read object content with line numbers."""
        key = file_path.lstrip("/")

        try:
            response = self._client.get_object(self._bucket, key)
            content = response.read().decode("utf-8")
            response.close()
            response.release_conn()

            # Format with line numbers like deepagents
            lines = content.split("\n")
            start = offset
            end = min(offset + limit, len(lines))

            formatted_lines = []
            for i, line in enumerate(lines[start:end], start=start + 1):
                formatted_lines.append(f"{i:6d}\t{line}")

            return "\n".join(formatted_lines)

        except Exception as e:
            return f"Error reading {file_path}: {e}"

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for pattern in objects."""
        import re

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        matches: list[GrepMatch] = []
        prefix = path.lstrip("/") if path else ""

        objects = self._client.list_objects(
            self._bucket,
            prefix=prefix,
            recursive=True,
        )

        for obj in objects:
            if obj.is_dir:
                continue

            # Apply glob filter if specified
            if glob:
                import fnmatch

                if not fnmatch.fnmatch(obj.object_name, glob.lstrip("/")):
                    continue

            try:
                response = self._client.get_object(self._bucket, obj.object_name)
                content = response.read().decode("utf-8")
                response.close()
                response.release_conn()

                for line_num, line in enumerate(content.split("\n"), start=1):
                    if regex.search(line):
                        matches.append(
                            GrepMatch(
                                path=f"/{obj.object_name}",
                                line=line_num,
                                text=line[:200],  # Truncate long lines
                            )
                        )
            except Exception:
                continue

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find objects matching glob pattern."""
        import fnmatch

        prefix = path.lstrip("/")
        results: list[FileInfo] = []

        objects = self._client.list_objects(
            self._bucket,
            prefix=prefix,
            recursive=True,
        )

        for obj in objects:
            if obj.is_dir:
                continue

            # Match against the full path or just filename depending on pattern
            name = obj.object_name
            if fnmatch.fnmatch(name, pattern.lstrip("/")) or fnmatch.fnmatch(
                name.split("/")[-1], pattern.lstrip("/")
            ):
                results.append(
                    FileInfo(
                        path=f"/{name}",
                        is_dir=False,
                        size=obj.size or 0,
                        modified_at=obj.last_modified.isoformat()
                        if obj.last_modified
                        else "",
                    )
                )

        return results

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create or overwrite an object."""
        key = file_path.lstrip("/")

        try:
            data = content.encode("utf-8")
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type="text/markdown",
            )
            return WriteResult(path=file_path, error=None, files_update=None)
        except Exception as e:
            return WriteResult(error=str(e))

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit an object by replacing text."""
        key = file_path.lstrip("/")

        try:
            # Read current content
            response = self._client.get_object(self._bucket, key)
            content = response.read().decode("utf-8")
            response.close()
            response.release_conn()

            # Perform replacement
            if replace_all:
                occurrences = content.count(old_string)
                new_content = content.replace(old_string, new_string)
            else:
                occurrences = 1 if old_string in content else 0
                new_content = content.replace(old_string, new_string, 1)

            if occurrences == 0:
                return EditResult(error=f"String not found: {old_string[:50]}")

            # Write back
            data = new_content.encode("utf-8")
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type="text/markdown",
            )

            return EditResult(
                path=file_path,
                error=None,
                files_update=None,
                occurrences=occurrences,
            )

        except Exception as e:
            return EditResult(error=str(e))

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple objects."""
        results: list[FileUploadResponse] = []

        for path, content in files:
            key = path.lstrip("/")
            try:
                self._client.put_object(
                    self._bucket,
                    key,
                    io.BytesIO(content),
                    length=len(content),
                )
                results.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=path, error="permission_denied"))

        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple objects."""
        results: list[FileDownloadResponse] = []

        for path in paths:
            key = path.lstrip("/")
            try:
                response = self._client.get_object(self._bucket, key)
                content = response.read()
                response.close()
                response.release_conn()
                results.append(FileDownloadResponse(path=path, content=content))
            except Exception:
                results.append(
                    FileDownloadResponse(path=path, content=None, error="file_not_found")
                )

        return results

    # =========================================================================
    # Gaius KB-specific operations
    # =========================================================================

    def iter_documents(
        self,
        extensions: tuple[str, ...] = (".md",),
    ) -> Iterator[KBDocument]:
        """Iterate over all documents in the KB."""
        for dir_name in self._config.allowed_dirs:
            objects = self._client.list_objects(
                self._bucket,
                prefix=f"{dir_name}/",
                recursive=True,
            )

            for obj in objects:
                if obj.is_dir:
                    continue

                # Check extension
                if not any(obj.object_name.endswith(ext) for ext in extensions):
                    continue

                try:
                    response = self._client.get_object(self._bucket, obj.object_name)
                    content = response.read().decode("utf-8")
                    response.close()
                    response.release_conn()

                    yield KBDocument(
                        path=obj.object_name,
                        content=content,
                        title=self._extract_title(
                            content, obj.object_name.split("/")[-1].rsplit(".", 1)[0]
                        ),
                        modified_at=obj.last_modified.isoformat()
                        if obj.last_modified
                        else "",
                        metadata={
                            "size_bytes": obj.size or 0,
                            "directory": dir_name,
                            "etag": obj.etag,
                        },
                    )
                except Exception:
                    continue

    def get_document(self, path: str) -> KBDocument | None:
        """Get a single document with metadata."""
        key = path.lstrip("/")

        try:
            # Get object stat for metadata
            stat = self._client.stat_object(self._bucket, key)

            # Get content
            response = self._client.get_object(self._bucket, key)
            content = response.read().decode("utf-8")
            response.close()
            response.release_conn()

            return KBDocument(
                path=path,
                content=content,
                title=self._extract_title(content, key.split("/")[-1].rsplit(".", 1)[0]),
                modified_at=stat.last_modified.isoformat() if stat.last_modified else "",
                metadata={
                    "size_bytes": stat.size or 0,
                    "directory": path.split("/")[0] if "/" in path else "",
                    "etag": stat.etag,
                },
            )
        except Exception:
            return None

    def document_exists(self, path: str) -> bool:
        """Check if a document exists."""
        key = path.lstrip("/")
        try:
            self._client.stat_object(self._bucket, key)
            return True
        except Exception:
            return False

    def get_stats(self) -> dict:
        """Get storage statistics."""
        total_documents = 0
        total_size_bytes = 0
        by_directory: dict[str, dict[str, int]] = {}
        stats: dict[str, object] = {
            "backend_type": "minio",
            "endpoint": self._config.endpoint,
            "bucket": self._bucket,
        }

        for dir_name in self._config.allowed_dirs:
            dir_count = 0
            dir_size = 0

            objects = self._client.list_objects(
                self._bucket,
                prefix=f"{dir_name}/",
                recursive=True,
            )

            for obj in objects:
                if not obj.is_dir and obj.object_name.endswith(".md"):
                    dir_count += 1
                    dir_size += obj.size or 0

            by_directory[dir_name] = {
                "documents": dir_count,
                "size_bytes": dir_size,
            }
            total_documents += dir_count
            total_size_bytes += dir_size

        stats["total_documents"] = total_documents
        stats["total_size_bytes"] = total_size_bytes
        stats["by_directory"] = by_directory
        return stats

    def _extract_title(self, content: str, fallback: str) -> str:
        """Extract title from markdown heading."""
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                return line[2:].strip()
        return fallback.replace("-", " ").replace("_", " ").title()
