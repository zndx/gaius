"""Cloudera Agent Studio storage backend (stub).

This module provides a placeholder for future integration with Cloudera's
Agent Studio artifact storage API. The actual implementation will depend
on the Agent Studio SDK when available.

Agent Studio provides:
- Workflow artifact storage
- Cross-agent data sharing
- Enterprise-grade persistence with HDFS/S3 backends

For now, this serves as documentation of the expected integration pattern.

Migration path:
1. Start with filesystem backend for local development
2. Move to minio backend for production object storage
3. Transition to agent_studio when deploying on Cloudera AI platform

Configuration:
    GAIUS_KB_BACKEND=agent_studio
    GAIUS_AGENT_STUDIO_URL=https://agent-studio.cloudera.local
    GAIUS_AGENT_STUDIO_API_KEY=...
    GAIUS_AGENT_STUDIO_WORKSPACE=default
"""

import os
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


class AgentStudioStorage:
    """Cloudera Agent Studio storage backend.

    This is a placeholder implementation that demonstrates the integration
    pattern. Replace with actual Agent Studio SDK calls when available.

    The Agent Studio API is expected to provide:
    - /artifacts/{workspace}/{path} - CRUD operations on artifacts
    - /artifacts/{workspace}/_list - List artifacts in workspace
    - /artifacts/{workspace}/_search - Search artifact content

    See: https://github.com/cloudera/CAI_STUDIO_AGENT
    """

    def __init__(self, config: StorageConfig):
        """Initialize Agent Studio storage.

        Args:
            config: Storage configuration. The 'root' field is used as
                    the workspace name.
        """
        self._config = config
        self._workspace = config.root or "default"
        self._api_url = os.getenv(
            "GAIUS_AGENT_STUDIO_URL", "http://localhost:8000/api/v1"
        )
        self._api_key = os.getenv("GAIUS_AGENT_STUDIO_API_KEY", "")

        # Placeholder: In actual implementation, create HTTP client here
        self._client = None

    @property
    def config(self) -> StorageConfig:
        """Get the storage configuration."""
        return self._config

    # =========================================================================
    # Deepagents BackendProtocol implementation (stubs)
    # =========================================================================

    def ls_info(self, path: str) -> list[FileInfo]:
        """List artifacts in Agent Studio workspace."""
        # TODO: Implement with Agent Studio SDK
        # Example API: GET /artifacts/{workspace}/_list?prefix={path}
        raise NotImplementedError(
            "Agent Studio backend not yet implemented. "
            "Use 'filesystem' or 'minio' backend for now. "
            "See https://github.com/cloudera/CAI_STUDIO_AGENT for Agent Studio API."
        )

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read artifact content from Agent Studio."""
        # TODO: GET /artifacts/{workspace}/{path}
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search artifacts in Agent Studio workspace."""
        # TODO: POST /artifacts/{workspace}/_search
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find artifacts matching pattern."""
        # TODO: GET /artifacts/{workspace}/_list?glob={pattern}
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create artifact in Agent Studio."""
        # TODO: PUT /artifacts/{workspace}/{path}
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit artifact content."""
        # TODO: PATCH /artifacts/{workspace}/{path}
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple artifacts."""
        # TODO: POST /artifacts/{workspace}/_batch_upload
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple artifacts."""
        # TODO: POST /artifacts/{workspace}/_batch_download
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    # =========================================================================
    # Gaius KB-specific operations (stubs)
    # =========================================================================

    def iter_documents(
        self,
        extensions: tuple[str, ...] = (".md",),
    ) -> Iterator[KBDocument]:
        """Iterate over all documents in Agent Studio workspace."""
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def get_document(self, path: str) -> KBDocument | None:
        """Get a single document from Agent Studio."""
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def document_exists(self, path: str) -> bool:
        """Check if document exists in Agent Studio."""
        raise NotImplementedError("Agent Studio backend not yet implemented.")

    def get_stats(self) -> dict:
        """Get workspace statistics from Agent Studio."""
        return {
            "total_documents": 0,
            "total_size_bytes": 0,
            "by_directory": {},
            "backend_type": "agent_studio",
            "api_url": self._api_url,
            "workspace": self._workspace,
            "status": "not_implemented",
        }


def register_agent_studio_backend() -> None:
    """Register Agent Studio backend with the factory.

    Call this to enable the agent_studio backend type:

        from gaius.storage.agent_studio import register_agent_studio_backend
        register_agent_studio_backend()

        # Now can use:
        # GAIUS_KB_BACKEND=agent_studio
    """
    from .factory import register_backend

    register_backend("agent_studio", lambda config: AgentStudioStorage(config))
