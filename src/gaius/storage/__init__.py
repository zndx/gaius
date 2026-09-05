"""Storage abstraction layer for Gaius KB.

Provides a unified interface for file storage that can be backed by:
- Local filesystem (default, for development)
- RustFS/S3 object storage (for production)
- Cloudera Agent Studio (for enterprise deployment)

The abstraction extends deepagents' BackendProtocol to ensure compatibility
with LangChain's agent ecosystem while providing Gaius-specific extensions.

Usage:
    from gaius.storage import get_storage_backend, StorageBackend

    # Get configured backend (from GAIUS_KB_BACKEND env var)
    backend = get_storage_backend()

    # List files
    files = backend.ls_info("/current/topics/")

    # Read file
    content = backend.read("/current/topics/kudu.md")

    # Write file
    result = backend.write("/scratch/2025-12-05/notes.md", "# Notes\\n...")

Database access:
    from gaius.storage.database import get_recent_cycles, get_agent_scores

    cycles = await get_recent_cycles(limit=10)
    scores = await get_agent_scores()

Profile/Domain operations:
    from gaius.storage.profile_ops import (
        list_profiles, get_profile,
        list_domains, get_active_domain, set_active_domain,
        get_profile_context, ProfileContext,
    )

    profiles = await list_profiles()
    context = await get_profile_context("cloudera", "csa")
"""

from .protocol import StorageBackend, StorageConfig, KBDocument
from .filesystem import FilesystemStorage
from .factory import get_storage_backend, register_backend

# Database queries are imported explicitly to avoid asyncpg import at module load
# Use: from gaius.storage.database import get_recent_cycles, ...

__all__ = [
    # Storage
    "StorageBackend",
    "StorageConfig",
    "KBDocument",
    "FilesystemStorage",
    "get_storage_backend",
    "register_backend",
]
