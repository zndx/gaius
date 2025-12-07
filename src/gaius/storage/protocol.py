"""Storage protocol definition extending deepagents BackendProtocol.

This module defines the StorageBackend protocol that all storage implementations
must follow. It extends deepagents' BackendProtocol with Gaius-specific operations
while maintaining compatibility with the LangChain agent ecosystem.

The design allows:
1. Direct use with deepagents' CompositeBackend for path-based routing
2. Migration path to Cloudera Agent Studio's artifact storage
3. Pluggable backends (filesystem, Minio, S3, etc.)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

# Re-export deepagents types for convenience
from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileOperationError,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)

__all__ = [
    # Re-exported from deepagents
    "BackendProtocol",
    "EditResult",
    "FileDownloadResponse",
    "FileInfo",
    "FileOperationError",
    "FileUploadResponse",
    "GrepMatch",
    "WriteResult",
    # Gaius-specific
    "StorageBackend",
    "StorageConfig",
    "KBDocument",
]


@dataclass
class StorageConfig:
    """Configuration for storage backends.

    Attributes:
        backend_type: Type of backend ("filesystem", "minio", "agent_studio")
        root: Root path or bucket for storage
        endpoint: Endpoint URL for remote backends (Minio, S3)
        access_key: Access key for authenticated backends
        secret_key: Secret key for authenticated backends
        region: Region for S3-compatible backends
        secure: Use HTTPS for remote connections
    """

    backend_type: str = "filesystem"
    root: str = "build/dev"
    endpoint: str = ""
    access_key: str = ""
    secret_key: str = ""
    region: str = ""
    secure: bool = True

    # Gaius-specific settings
    allowed_dirs: tuple[str, ...] = ("archive", "current", "scratch")
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300


@dataclass
class KBDocument:
    """A knowledge base document with metadata.

    Used for iterating over documents in the KB for indexing.
    """

    path: str  # Relative path within KB (e.g., "current/topics/kudu.md")
    content: str
    title: str = ""
    modified_at: str = ""
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class StorageBackend(BackendProtocol, Protocol):
    """Extended storage protocol for Gaius KB operations.

    Extends deepagents' BackendProtocol with KB-specific operations:
    - Document iteration for indexing
    - Metadata extraction
    - Content streaming for large files

    All deepagents BackendProtocol methods are inherited:
    - ls_info, read, write, edit
    - glob_info, grep_raw
    - upload_files, download_files

    Implementations:
    - FilesystemStorage: Local filesystem (default)
    - MinioStorage: Minio/S3 object storage
    - AgentStudioStorage: Cloudera Agent Studio integration
    """

    @property
    def config(self) -> StorageConfig:
        """Get the storage configuration."""
        ...

    def iter_documents(
        self,
        extensions: tuple[str, ...] = (".md",),
    ) -> Iterator[KBDocument]:
        """Iterate over all documents in the KB.

        Used for indexing operations. Yields documents from allowed
        directories with the specified extensions.

        Args:
            extensions: File extensions to include (default: markdown only)

        Yields:
            KBDocument objects for each matching file
        """
        ...

    def get_document(self, path: str) -> KBDocument | None:
        """Get a single document with metadata.

        Args:
            path: Relative path within KB (e.g., "current/topics/kudu.md")

        Returns:
            KBDocument if found, None otherwise
        """
        ...

    def document_exists(self, path: str) -> bool:
        """Check if a document exists.

        Args:
            path: Relative path within KB

        Returns:
            True if document exists
        """
        ...

    def get_stats(self) -> dict:
        """Get storage statistics.

        Returns:
            Dict with keys like:
            - total_documents: int
            - total_size_bytes: int
            - by_directory: dict[str, int]
        """
        ...
