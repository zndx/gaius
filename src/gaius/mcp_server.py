"""Gaius MCP Server.

Exposes Gaius capabilities to Claude Code and other MCP clients:
- KB operations (search, read, create, update, delete)
- Local inference via optillm
- Web search via Brave API
- Research and KB population

Usage:
    # Start the server
    uv run gaius-mcp

    # Configure in Claude Code's .mcp.json:
    {
      "mcpServers": {
        "gaius": {
          "command": "uv",
          "args": ["run", "gaius-mcp"],
          "env": {
            "BRAVE_API_KEY": "..."
          }
        }
      }
    }
"""

import json
import os
from datetime import datetime
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None

# KB root (relative to cwd or absolute)
KB_ROOT = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
ALLOWED_DIRS = ("archive", "current", "scratch")


def ensure_mcp():
    """Raise helpful error if MCP not installed."""
    if not MCP_AVAILABLE:
        raise ImportError("mcp package required. Install with: uv sync --extra mcp")


def get_kb_root() -> Path:
    """Get the KB root directory."""
    root = KB_ROOT
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def validate_kb_path(path: str) -> Path:
    """Validate that a path is within the allowed KB structure.

    Args:
        path: Relative path like "current/topics/kudu.md"

    Returns:
        Absolute path to the file

    Raises:
        ValueError: If path is outside allowed directories
    """
    kb_root = get_kb_root()

    # Handle both relative and absolute paths
    p = Path(path)
    if p.is_absolute():
        # Check if it's under kb_root
        try:
            p.relative_to(kb_root)
            full_path = p
        except ValueError:
            raise ValueError(f"Path {path} is outside KB root {kb_root}")
    else:
        full_path = kb_root / p

    # Ensure the path is in an allowed directory
    parts = full_path.relative_to(kb_root).parts
    if not parts or parts[0] not in ALLOWED_DIRS:
        raise ValueError(
            f"Path must be under one of: {', '.join(ALLOWED_DIRS)}. Got: {path}"
        )

    return full_path


def create_server() -> "FastMCP":
    """Create and configure the MCP server."""
    ensure_mcp()

    server = FastMCP("gaius")

    # --- KB Operations ---

    @server.tool()
    async def search_kb(query: str, max_results: int = 10) -> str:
        """Search the Gaius knowledge base.

        Searches file names and content for the query string.

        Args:
            query: Search query
            max_results: Maximum number of results to return
        """
        kb_root = get_kb_root()
        results = []

        for allowed_dir in ALLOWED_DIRS:
            dir_path = kb_root / allowed_dir
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                # Check filename
                if query.lower() in md_file.name.lower():
                    rel_path = md_file.relative_to(kb_root)
                    results.append(
                        {
                            "path": str(rel_path),
                            "match": "filename",
                            "preview": md_file.name,
                        }
                    )
                    continue

                # Check content
                try:
                    content = md_file.read_text()
                    if query.lower() in content.lower():
                        # Get preview around match
                        idx = content.lower().find(query.lower())
                        start = max(0, idx - 50)
                        end = min(len(content), idx + len(query) + 50)
                        preview = content[start:end].replace("\n", " ")
                        if start > 0:
                            preview = "..." + preview
                        if end < len(content):
                            preview = preview + "..."

                        rel_path = md_file.relative_to(kb_root)
                        results.append(
                            {
                                "path": str(rel_path),
                                "match": "content",
                                "preview": preview,
                            }
                        )
                except Exception:
                    continue

                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        return json.dumps({"results": results, "total": len(results)}, indent=2)

    @server.tool()
    async def read_kb(path: str) -> str:
        """Read a KB entry by path.

        Args:
            path: Relative path like "current/topics/kudu.md"
        """
        full_path = validate_kb_path(path)
        if not full_path.exists():
            return json.dumps({"error": f"File not found: {path}"})

        content = full_path.read_text()
        return json.dumps(
            {
                "path": path,
                "content": content,
                "size": len(content),
                "modified": full_path.stat().st_mtime,
            },
            indent=2,
        )

    @server.tool()
    async def create_kb(path: str, content: str) -> str:
        """Create a new KB entry.

        Args:
            path: Relative path like "current/topics/new_topic.md"
            content: Markdown content for the entry
        """
        full_path = validate_kb_path(path)

        if full_path.exists():
            return json.dumps({"error": f"File already exists: {path}"})

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure .md extension
        if not str(full_path).endswith(".md"):
            full_path = Path(str(full_path) + ".md")

        full_path.write_text(content)

        return json.dumps(
            {
                "created": str(full_path.relative_to(get_kb_root())),
                "size": len(content),
            },
            indent=2,
        )

    @server.tool()
    async def update_kb(path: str, content: str) -> str:
        """Update an existing KB entry.

        Args:
            path: Relative path to the entry
            content: New markdown content
        """
        full_path = validate_kb_path(path)

        if not full_path.exists():
            return json.dumps({"error": f"File not found: {path}"})

        old_size = len(full_path.read_text())
        full_path.write_text(content)

        return json.dumps(
            {
                "updated": path,
                "old_size": old_size,
                "new_size": len(content),
            },
            indent=2,
        )

    @server.tool()
    async def delete_kb(path: str) -> str:
        """Delete a KB entry.

        Args:
            path: Relative path to delete
        """
        full_path = validate_kb_path(path)

        if not full_path.exists():
            return json.dumps({"error": f"File not found: {path}"})

        full_path.unlink()

        return json.dumps({"deleted": path}, indent=2)

    @server.tool()
    async def list_kb(directory: str = "") -> str:
        """List KB entries in a directory.

        Args:
            directory: Subdirectory to list (default: list all allowed dirs)
        """
        kb_root = get_kb_root()

        if directory:
            full_path = validate_kb_path(directory)
            if not full_path.is_dir():
                return json.dumps({"error": f"Not a directory: {directory}"})
            dirs_to_list = [full_path]
        else:
            dirs_to_list = [kb_root / d for d in ALLOWED_DIRS if (kb_root / d).exists()]

        entries = []
        for dir_path in dirs_to_list:
            for item in sorted(dir_path.rglob("*.md")):
                rel_path = item.relative_to(kb_root)
                entries.append(
                    {
                        "path": str(rel_path),
                        "size": item.stat().st_size,
                        "modified": item.stat().st_mtime,
                    }
                )

        return json.dumps({"entries": entries, "total": len(entries)}, indent=2)

    # --- Inference Operations ---

    @server.tool()
    async def ask_local(
        question: str,
        technique: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Query local LLM via optillm.

        Args:
            question: The question or prompt
            technique: optillm technique (cot_reflection, bon, moa, etc.) - empty for passthrough
            max_tokens: Maximum tokens to generate
        """
        try:
            from .inference import get_client, Message

            client = get_client()
            result = await client.complete(
                messages=[Message(role="user", content=question)],
                technique=technique or None,
                max_tokens=max_tokens,
            )

            return json.dumps(
                {
                    "response": result.content,
                    "model": result.model,
                    "technique": result.technique,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Search Operations ---

    @server.tool()
    async def web_search(query: str, count: int = 5) -> str:
        """Search the web via Brave API.

        Args:
            query: Search query
            count: Number of results (max 20)
        """
        try:
            from .inference import get_search

            search = get_search()
            results = await search.search(query, count=count)

            return json.dumps(
                {
                    "results": [
                        {
                            "title": r.title,
                            "url": r.url,
                            "snippet": r.snippet,
                            "published": r.published,
                        }
                        for r in results
                    ],
                    "total": len(results),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def research_topic(
        topic: str,
        domain: str = "",
        save_to_kb: bool = True,
    ) -> str:
        """Research a topic using web search and local LLM, optionally saving to KB.

        Args:
            topic: Topic to research
            domain: Domain context (e.g., "Apache Kudu", "pension")
            save_to_kb: Whether to save the result to the KB
        """
        try:
            from .inference import get_client, get_search, Message

            # Search for information
            search = get_search()
            results = await search.search_for_kb(topic, domain or "general", count=5)

            if not results:
                return json.dumps({"error": "No search results found"}, indent=2)

            # Format sources for synthesis
            sources_text = "\n".join(
                f"- [{r['title']}]({r['source']}): {r['summary']}" for r in results
            )

            # Synthesize with local LLM
            client = get_client()
            synthesis_prompt = f"""Topic: {topic}
Domain: {domain or 'general'}

Sources:
{sources_text}

Create a structured markdown note with:
1. Key points and facts
2. Implications or applications
3. Related concepts (as wiki-links using [[concept]] syntax)

Be concise but thorough."""

            synthesis = await client.complete(
                messages=[
                    Message(
                        role="system",
                        content=f"You are a research assistant specializing in {domain or 'general topics'}.",
                    ),
                    Message(role="user", content=synthesis_prompt),
                ],
                technique="cot_reflection",  # Use reflection for better synthesis
                max_tokens=2048,
            )

            # Create KB entry if requested
            kb_path = None
            if save_to_kb:
                today = datetime.now().strftime("%Y-%m-%d")
                timestamp = datetime.now().strftime("%H%M%S")
                safe_topic = topic.replace(" ", "_").replace("/", "-")[:50]
                kb_path = f"scratch/{today}/{timestamp}_{safe_topic}.md"

                content = f"""# {topic}

Created: {datetime.now().isoformat()}
Domain: {domain or 'general'}

---

{synthesis.content}

---

## Sources

{sources_text}
"""
                full_path = validate_kb_path(kb_path)
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

            return json.dumps(
                {
                    "topic": topic,
                    "domain": domain,
                    "synthesis": synthesis.content,
                    "sources": results,
                    "kb_path": kb_path,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- KB Resources ---
    # Expose KB entries as MCP resources for direct browsing

    def _register_kb_resources():
        """Register all KB entries as resources."""
        kb_root = get_kb_root()

        for allowed_dir in ALLOWED_DIRS:
            dir_path = kb_root / allowed_dir
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                rel_path = md_file.relative_to(kb_root)
                uri = f"gaius://kb/{rel_path}"

                # Create a closure to capture the path
                def make_reader(file_path: Path):
                    @server.resource(
                        uri=f"gaius://kb/{file_path.relative_to(kb_root)}",
                        name=file_path.name,
                        description=f"KB entry: {file_path.relative_to(kb_root)}",
                        mime_type="text/markdown",
                    )
                    def read_resource() -> str:
                        if file_path.exists():
                            return file_path.read_text()
                        return f"# Not Found\n\nFile not found: {file_path}"

                    return read_resource

                make_reader(md_file)

    # Register existing KB resources
    _register_kb_resources()

    return server


def main():
    """Entry point for gaius-mcp command."""
    ensure_mcp()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
