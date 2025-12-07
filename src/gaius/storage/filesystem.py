"""Filesystem storage backend for local KB storage.

This is the default backend that stores KB documents on the local filesystem.
It wraps deepagents' FilesystemBackend with Gaius-specific extensions.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import (
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)

from .protocol import KBDocument, StorageBackend, StorageConfig


class FilesystemStorage:
    """Local filesystem storage backend.

    Wraps deepagents' FilesystemBackend with Gaius KB-specific operations.
    Documents are stored under a configurable root directory with subdirectories
    for different content types (current, scratch, archive).

    Example:
        storage = FilesystemStorage(StorageConfig(root="build/dev"))
        for doc in storage.iter_documents():
            print(doc.path, doc.title)
    """

    def __init__(self, config: StorageConfig | None = None):
        """Initialize filesystem storage.

        Args:
            config: Storage configuration. If None, uses defaults with
                    GAIUS_KB_ROOT env var or "build/dev".
        """
        if config is None:
            root = os.getenv("GAIUS_KB_ROOT", "build/dev")
            config = StorageConfig(backend_type="filesystem", root=root)

        self._config = config
        self._root = Path(config.root).resolve()

        # Create deepagents backend for standard operations
        self._backend = FilesystemBackend(
            root_dir=str(self._root),
            virtual_mode=False,  # Use real paths
        )

    @property
    def config(self) -> StorageConfig:
        """Get the storage configuration."""
        return self._config

    # =========================================================================
    # Deepagents BackendProtocol delegation
    # =========================================================================

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories."""
        return self._backend.ls_info(path)

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content with line numbers."""
        return self._backend.read(file_path, offset=offset, limit=limit)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for pattern in files."""
        return self._backend.grep_raw(pattern, path, glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching glob pattern."""
        return self._backend.glob_info(pattern, path)

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create or overwrite a file."""
        return self._backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing text."""
        return self._backend.edit(file_path, old_string, new_string, replace_all)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files."""
        return self._backend.upload_files(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files."""
        return self._backend.download_files(paths)

    # =========================================================================
    # Gaius KB-specific operations
    # =========================================================================

    def iter_documents(
        self,
        extensions: tuple[str, ...] = (".md",),
    ) -> Iterator[KBDocument]:
        """Iterate over all documents in the KB.

        Yields documents from allowed directories (current, scratch, archive)
        with the specified extensions.

        Args:
            extensions: File extensions to include

        Yields:
            KBDocument for each matching file
        """
        for dir_name in self._config.allowed_dirs:
            dir_path = self._root / dir_name
            if not dir_path.exists():
                continue

            for file_path in dir_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if not any(file_path.suffix.lower() == ext for ext in extensions):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")
                    rel_path = str(file_path.relative_to(self._root))
                    stat = file_path.stat()

                    yield KBDocument(
                        path=rel_path,
                        content=content,
                        title=self._extract_title(content, file_path.stem),
                        modified_at=datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        metadata={
                            "size_bytes": stat.st_size,
                            "directory": dir_name,
                            **self._extract_doc_metadata(file_path, content),
                        },
                    )
                except Exception:
                    # Skip files that can't be read
                    continue

    def get_document(self, path: str) -> KBDocument | None:
        """Get a single document with metadata.

        Args:
            path: Relative path within KB (e.g., "current/topics/kudu.md")

        Returns:
            KBDocument if found, None otherwise
        """
        file_path = self._root / path
        if not file_path.exists() or not file_path.is_file():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            stat = file_path.stat()

            return KBDocument(
                path=path,
                content=content,
                title=self._extract_title(content, file_path.stem),
                modified_at=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                metadata={
                    "size_bytes": stat.st_size,
                    "directory": path.split("/")[0] if "/" in path else "",
                    **self._extract_doc_metadata(file_path, content),
                },
            )
        except Exception:
            return None

    def document_exists(self, path: str) -> bool:
        """Check if a document exists."""
        file_path = self._root / path
        return file_path.exists() and file_path.is_file()

    def get_stats(self) -> dict:
        """Get storage statistics."""
        stats = {
            "total_documents": 0,
            "total_size_bytes": 0,
            "by_directory": {},
            "backend_type": "filesystem",
            "root": str(self._root),
        }

        for dir_name in self._config.allowed_dirs:
            dir_path = self._root / dir_name
            if not dir_path.exists():
                continue

            dir_count = 0
            dir_size = 0

            for file_path in dir_path.rglob("*.md"):
                if file_path.is_file():
                    dir_count += 1
                    dir_size += file_path.stat().st_size

            stats["by_directory"][dir_name] = {
                "documents": dir_count,
                "size_bytes": dir_size,
            }
            stats["total_documents"] += dir_count
            stats["total_size_bytes"] += dir_size

        return stats

    def _extract_title(self, content: str, fallback: str) -> str:
        """Extract title from markdown heading."""
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                return line[2:].strip()
        return fallback.replace("-", " ").replace("_", " ").title()

    def _extract_doc_metadata(self, file_path: Path, content: str) -> dict:
        """Extract document metadata including type classification.

        Classifies documents by filename patterns for Qdrant filtering:
        - *_thought_*.md -> doc_type: "thought"
        - *_thoughts.md -> doc_type: "thought"
        - *_explain_*.md -> doc_type: "explanation"
        - *_charter*.md -> doc_type: "charter"
        - everything else -> doc_type: "document"
        """
        metadata = {}

        # Classify by filename pattern
        filename = file_path.stem
        if "_thought_" in filename:
            metadata["doc_type"] = "thought"
            # Extract thought type (e.g., "051920_thought_pattern" -> "pattern")
            parts = filename.split("_thought_")
            if len(parts) > 1:
                metadata["thought_type"] = parts[1]
        elif filename.endswith("_thoughts"):
            metadata["doc_type"] = "thought"
        elif "_explain_" in filename:
            metadata["doc_type"] = "explanation"
        elif "_charter" in filename:
            metadata["doc_type"] = "charter"
        else:
            metadata["doc_type"] = "document"

        # Extract thought_id from frontmatter if present
        if "thought_id:" in content:
            for line in content.split("\n")[:20]:
                if line.startswith("thought_id:"):
                    metadata["thought_id"] = line.split(":", 1)[1].strip()
                    break

        return metadata
