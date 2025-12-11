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


async def save_swarm_to_kb(
    domain: str,
    context: str,
    results: dict[str, dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    """Save swarm results to KB as a Zettelkasten note.

    Saves to: current/agents/swarm/{date}/{timestamp}_{domain}.md

    This is called by SchedulerProxy.run_swarm() so all swarm invocations
    (CLI, TUI, MCP) consistently persist results to KB.

    Args:
        domain: Analysis domain
        context: Additional context
        results: Raw agent results dict
        summary: Summary statistics

    Returns:
        Relative path to saved file (e.g., "current/agents/swarm/2025-12-09/223537_pension.md")
    """
    # Create path with zettelkasten naming
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H%M%S")

    # Sanitize domain for filename
    safe_domain = "".join(c if c.isalnum() or c in "-_" else "_" for c in domain[:30])
    safe_domain = safe_domain.strip() or "analysis"

    # Use relative path for storage backend
    rel_path = f"current/agents/swarm/{today}/{timestamp}_{safe_domain}.md"

    # Build comprehensive markdown document
    lines = [
        f"# Swarm Analysis: {domain}",
        "",
        f"**Created**: {datetime.now().isoformat()}",
        f"**Domain**: {domain}",
    ]

    if context:
        lines.extend([f"**Context**: {context}", ""])
    else:
        lines.append("")

    # Summary section
    lines.extend([
        "## Summary",
        "",
        f"- **Agents**: {summary.get('total', 0)} ({summary.get('completed', 0)} completed, {summary.get('failed', 0)} failed)",
        f"- **Total Tokens**: {summary.get('total_tokens', 0)}",
        f"- **Total Latency**: {summary.get('total_latency_ms', 0)}ms",
        "",
    ])

    # Agent responses - ordered by role importance
    role_order = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]
    ordered_results = []
    for role in role_order:
        if role in results:
            ordered_results.append((role, results[role]))
    # Add any roles not in the standard order
    for role, result in results.items():
        if role not in role_order:
            ordered_results.append((role, result))

    lines.append("## Agent Responses")
    lines.append("")

    for role_name, result in ordered_results:
        status = result.get("status", "unknown")
        status_icon = "+" if status == "completed" else "-"
        model = result.get("model", "unknown")
        endpoint = result.get("endpoint", "unknown")
        latency = result.get("latency_ms", 0)

        lines.extend([
            f"### {status_icon} {role_name}",
            "",
            f"*Model*: `{model}` | *Endpoint*: `{endpoint}` | *Latency*: {latency}ms",
            "",
        ])

        content = result.get("content", "")
        if content:
            lines.extend([content, ""])
        elif result.get("error"):
            lines.extend([f"**Error**: {result['error']}", ""])
        else:
            lines.extend(["*No response*", ""])

    # Footer
    lines.extend([
        "---",
        "",
        "*Generated by swarm analysis via gRPC engine*",
    ])

    content = "\n".join(lines)

    # Ensure parent directory exists via storage backend
    backend = get_storage_backend()
    kb_root = Path(backend.config.root).resolve()
    save_dir = kb_root / "current" / "agents" / "swarm" / today
    save_dir.mkdir(parents=True, exist_ok=True)

    # Write the file
    result = backend.write(rel_path, content)
    if result.error:
        raise RuntimeError(f"Failed to save swarm to KB: {result.error}")

    return rel_path


def save_swarm_results(results: dict[str, dict[str, Any]], domain: str) -> str:
    """Save swarm results to KB (sync wrapper for gRPC servicer).

    This is the simple 2-arg version called by gaius_servicer.py.
    Delegates to save_swarm_to_kb with computed summary.

    Args:
        results: Raw agent results dict {role_name: {content, status, ...}}
        domain: Analysis domain

    Returns:
        Relative path to saved file
    """
    import asyncio

    # Compute summary from results
    total = len(results)
    completed = sum(1 for r in results.values() if r.get("status") == "completed")
    failed = total - completed
    total_tokens = sum(
        r.get("input_tokens", 0) + r.get("output_tokens", 0)
        for r in results.values()
    )
    total_latency = sum(r.get("latency_ms", 0) for r in results.values())

    summary = {
        "total": total,
        "completed": completed,
        "failed": failed,
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency,
    }

    # Run the async function
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            save_swarm_to_kb(domain=domain, context="", results=results, summary=summary)
        )
    finally:
        loop.close()
