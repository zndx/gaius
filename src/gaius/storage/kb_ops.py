"""KB operations using storage abstraction.

High-level KB operations that use the StorageBackend abstraction.
These functions are used by MCP server, CLI, and TUI for KB access.

All KB operations go through this module to ensure:
- Consistent behavior across all interfaces
- Storage backend independence (filesystem, minio, agent studio)
- Proper error handling and validation
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .factory import get_storage_backend
from .protocol import StorageBackend, StorageConfig

# Allowed directories for KB operations
ALLOWED_DIRS = ("archive", "current", "scratch")


@dataclass
class SearchResult:
    """KB search result."""
    path: str
    match_type: str  # "filename" or "content"
    preview: str


@dataclass
class KBEntry:
    """KB entry with metadata."""
    path: str
    content: str
    size: int
    modified: float


def _get_kb_root() -> Path:
    """Get KB root path from config (resolved to absolute)."""
    backend = get_storage_backend()
    return Path(backend.config.root).resolve()


def _validate_path(path: str) -> tuple[bool, str]:
    """Validate KB path is within allowed directories.

    Returns:
        (is_valid, error_message) tuple
    """
    # Normalize path
    path = path.lstrip("/")

    # Must start with allowed directory
    parts = path.split("/")
    if not parts or parts[0] not in ALLOWED_DIRS:
        return False, f"Path must start with one of: {', '.join(ALLOWED_DIRS)}"

    # No parent directory traversal
    if ".." in parts:
        return False, "Path cannot contain '..'"

    return True, ""


async def search_kb(query: str, max_results: int = 10) -> list[SearchResult]:
    """Search KB for matching files.

    Searches file names and content for the query string.

    Args:
        query: Search query
        max_results: Maximum number of results to return

    Returns:
        List of SearchResult objects
    """
    backend = get_storage_backend()
    results: list[SearchResult] = []
    query_lower = query.lower()

    for doc in backend.iter_documents(extensions=(".md",)):
        # Check filename
        filename = doc.path.split("/")[-1]
        if query_lower in filename.lower():
            results.append(SearchResult(
                path=doc.path,
                match_type="filename",
                preview=filename,
            ))
            if len(results) >= max_results:
                break
            continue

        # Check content
        content_lower = doc.content.lower()
        if query_lower in content_lower:
            # Get preview around match
            idx = content_lower.find(query_lower)
            start = max(0, idx - 50)
            end = min(len(doc.content), idx + len(query) + 50)
            preview = doc.content[start:end].replace("\n", " ")
            if start > 0:
                preview = "..." + preview
            if end < len(doc.content):
                preview = preview + "..."

            results.append(SearchResult(
                path=doc.path,
                match_type="content",
                preview=preview,
            ))

            if len(results) >= max_results:
                break

    return results


async def read_kb(path: str) -> KBEntry | None:
    """Read a KB entry by path.

    Args:
        path: Relative path like "current/topics/kudu.md"

    Returns:
        KBEntry if found, None otherwise
    """
    is_valid, error = _validate_path(path)
    if not is_valid:
        return None

    backend = get_storage_backend()
    doc = backend.get_document(path)

    if doc is None:
        return None

    # Get modification time from metadata or use current time
    try:
        modified = datetime.fromisoformat(doc.modified_at).timestamp()
    except (ValueError, TypeError):
        modified = datetime.now().timestamp()

    return KBEntry(
        path=doc.path,
        content=doc.content,
        size=len(doc.content),
        modified=modified,
    )


async def create_kb(path: str, content: str) -> dict[str, Any]:
    """Create a new KB entry.

    Args:
        path: Relative path like "current/topics/new_topic.md"
        content: Markdown content for the entry

    Returns:
        Dict with success status and path or error
    """
    is_valid, error = _validate_path(path)
    if not is_valid:
        return {"error": error}

    backend = get_storage_backend()

    # Check if file already exists
    if backend.document_exists(path):
        return {"error": f"File already exists: {path}"}

    # Write the file (use relative path - leading / treated as absolute by backend)
    result = backend.write(path, content)

    if result.error:
        return {"error": result.error}

    return {
        "success": True,
        "path": path,
        "size": len(content),
    }


async def update_kb(path: str, content: str) -> dict[str, Any]:
    """Update an existing KB entry.

    Args:
        path: Relative path to the entry
        content: New markdown content

    Returns:
        Dict with success status and metadata or error
    """
    is_valid, error = _validate_path(path)
    if not is_valid:
        return {"error": error}

    backend = get_storage_backend()

    # Check if file exists
    if not backend.document_exists(path):
        return {"error": f"File not found: {path}"}

    # Get old content for delta calculation
    old_doc = backend.get_document(path)
    old_size = len(old_doc.content) if old_doc else 0
    old_content = old_doc.content if old_doc else ""

    # Use edit to replace all content (deepagents write doesn't allow overwrite)
    # Replace entire old content with new content
    result = backend.edit(path, old_content, content)

    if result.error:
        return {"error": result.error}

    return {
        "success": True,
        "path": path,
        "old_size": old_size,
        "new_size": len(content),
        "delta": len(content) - old_size,
    }


async def delete_kb(path: str) -> dict[str, Any]:
    """Delete a KB entry.

    Args:
        path: Relative path to delete

    Returns:
        Dict with success status or error
    """
    is_valid, error = _validate_path(path)
    if not is_valid:
        return {"error": error}

    backend = get_storage_backend()

    # Check if file exists
    if not backend.document_exists(path):
        return {"error": f"File not found: {path}"}

    # For filesystem backend, we need to use Path operations
    # This is a limitation of the deepagents BackendProtocol which doesn't have delete
    # TODO: Add delete to StorageBackend protocol
    try:
        kb_root = _get_kb_root()
        full_path = kb_root / path
        full_path.unlink()
        return {"success": True, "path": path}
    except Exception as e:
        return {"error": str(e)}


async def list_kb(directory: str = "") -> dict[str, Any]:
    """List KB entries in a directory.

    Args:
        directory: Subdirectory to list (default: list all allowed dirs)

    Returns:
        Dict with entries list or error
    """
    backend = get_storage_backend()

    if directory:
        is_valid, error = _validate_path(directory)
        if not is_valid:
            return {"error": error}

        # List specific directory (no leading slash for deepagents backend)
        infos = backend.ls_info(directory)
        kb_root = str(_get_kb_root())
        entries = []
        for info in infos:
            # Convert absolute path to relative
            abs_path = info["path"].rstrip("/")
            if abs_path.startswith(kb_root):
                rel_path = abs_path[len(kb_root):].lstrip("/")
            else:
                rel_path = abs_path.lstrip("/")
            entries.append({
                "path": rel_path,
                "is_dir": info.get("is_dir", False),
                "size": info.get("size", 0),
            })
        return {"directory": directory, "entries": entries}
    else:
        # List all allowed directories (no leading slash for deepagents backend)
        all_entries = []
        kb_root = str(_get_kb_root())
        for allowed_dir in ALLOWED_DIRS:
            infos = backend.ls_info(allowed_dir)
            for info in infos:
                # Convert absolute path to relative
                abs_path = info["path"].rstrip("/")
                if abs_path.startswith(kb_root):
                    rel_path = abs_path[len(kb_root):].lstrip("/")
                else:
                    rel_path = abs_path.lstrip("/")
                all_entries.append({
                    "path": rel_path,
                    "is_dir": info.get("is_dir", False),
                    "size": info.get("size", 0),
                })

        return {"entries": all_entries}


async def get_kb_stats() -> dict[str, Any]:
    """Get KB statistics.

    Returns:
        Dict with document counts and sizes by directory
    """
    backend = get_storage_backend()
    return backend.get_stats()
