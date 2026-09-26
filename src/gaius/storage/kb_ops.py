from __future__ import annotations

"""KB operations using storage abstraction.

High-level KB operations that use the StorageBackend abstraction.
These functions are used by MCP server, CLI, and TUI for KB access.

All KB operations go through this module to ensure:
- Consistent behavior across all interfaces
- Storage backend independence (filesystem, rustfs, agent studio)
- Proper error handling and validation
"""

import heapq
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .factory import get_storage_backend
from .protocol import StorageBackend, StorageConfig

# Allowed directories for KB operations
ALLOWED_DIRS = ("archive", "current", "scratch")

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.-]{2,}")
_STOP = frozenset({
    "a", "an", "the", "of", "on", "in", "and", "or", "to", "for",
    "with", "from", "by", "at", "is", "it", "as", "be", "this", "that",
})


def query_tokens(query: str) -> list[str]:
    """Content words. The whole question is not one required phrase."""
    seen: list[str] = []
    for raw in _TOKEN.findall((query or "").lower()):
        if raw in _STOP or raw in seen:
            continue
        seen.append(raw)
    return seen


def _title_blob(path: str, content: str) -> str:
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    name = name.replace("-", " ").replace("_", " ")
    heading = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            break
    return f"{heading} {name}".lower()


def document_rank_key(path: str, content: str, query: str) -> tuple[int, int, int, int] | None:
    """Higher is a better hit. None means the file does not match.

    Title coverage beats a scratch note that merely shares more body words.
    A source under ``current/content`` beats an agenda brief. An exact
    phrase still wins over a partial one when titles tie.
    """
    tokens = query_tokens(query)
    phrase = " ".join((query or "").lower().split())
    low = content.lower()
    title = _title_blob(path, content)
    title_hits = sum(1 for token in tokens if token in title)
    body_hits = sum(1 for token in tokens if token in low)
    phrase_hit = 1 if phrase and len(phrase) > 3 and phrase in low else 0
    if title_hits == 0 and body_hits == 0 and not phrase_hit:
        return None
    if "/content/" in f"/{path}":
        kind = 2
    elif path.startswith("scratch/"):
        kind = 0
    else:
        kind = 1
    return (title_hits, phrase_hit, kind, body_hits)


def _preview(content: str, query: str) -> str:
    low = content.lower()
    tokens = query_tokens(query)
    idx = -1
    for token in tokens:
        found = low.find(token)
        if found >= 0 and (idx < 0 or found < idx):
            idx = found
    if idx < 0:
        idx = 0
    start = max(0, idx - 50)
    end = min(len(content), idx + 80)
    preview = content[start:end].replace("\n", " ")
    if start > 0:
        preview = "..." + preview
    if end < len(content):
        preview = preview + "..."
    return preview


def rank_documents(
    docs: list[tuple[str, str]],
    query: str,
    max_results: int,
) -> list[SearchResult]:
    """Best ``max_results`` documents. ``docs`` are ``(path, content)``."""
    n = max(1, int(max_results or 1))
    heap: list[tuple[tuple[int, int, int, int], str, str]] = []
    for path, content in docs:
        key = document_rank_key(path, content, query)
        if key is None:
            continue
        title_hits = key[0]
        preview = _preview(content, query)
        match = "filename" if title_hits else "content"
        item = (key, path, match + "\0" + preview)
        if len(heap) < n:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    ranked = sorted(heap, reverse=True)
    out: list[SearchResult] = []
    for _key, path, packed in ranked:
        match, preview = packed.split("\0", 1)
        out.append(SearchResult(path=path, match_type=match, preview=preview))
    return out


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


def get_kb_root() -> Path:
    """Get KB root path from config (resolved to absolute).

    Public API for getting the KB root path.
    """
    return _get_kb_root()


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
    n = max(1, int(max_results or 1))
    heap: list[tuple[tuple[int, int, int, int], str, str]] = []
    for doc in backend.iter_documents(extensions=(".md",)):
        key = document_rank_key(doc.path, doc.content, query)
        if key is None:
            continue
        match = "filename" if key[0] else "content"
        item = (key, doc.path, match + "\0" + _preview(doc.content, query))
        if len(heap) < n:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    out: list[SearchResult] = []
    for _key, path, packed in sorted(heap, reverse=True):
        match, preview = packed.split("\0", 1)
        out.append(SearchResult(path=path, match_type=match, preview=preview))
    return out


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
    domain: str | None,
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

    # Sanitize domain for filename (use "open" if None)
    domain_str = domain or "open"
    safe_domain = "".join(c if c.isalnum() or c in "-_" else "_" for c in domain_str[:30])
    safe_domain = safe_domain.strip() or "analysis"

    # Use relative path for storage backend
    rel_path = f"current/agents/swarm/{today}/{timestamp}_{safe_domain}.md"

    # Build comprehensive markdown document
    lines = [
        f"# Swarm Analysis: {domain_str}",
        "",
        f"**Created**: {datetime.now().isoformat()}",
        f"**Domain**: {domain_str}",
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


def save_swarm_results(results: dict[str, dict[str, Any]], domain: str | None) -> str:
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
