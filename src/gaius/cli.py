"""Gaius CLI - Non-interactive command mode.

Execute commands without starting the TUI. Useful for:
- Testing logic
- Scripting
- Batch operations
- CI/CD pipelines

Usage:
    # Single command
    uv run python -m gaius.cli --cmd "/info K10"

    # Multiple commands
    uv run python -m gaius.cli --cmd "/domain pension" --cmd "/overlay h1"

    # Pipe commands
    echo "/info K10" | uv run python -m gaius.cli

    # Output formats
    uv run python -m gaius.cli --cmd "/info" --format json
    uv run python -m gaius.cli --cmd "/info" --format text
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TextIO

from .core.state import AppState, ViewMode, OverlayMode
from .static import (
    GRID_DATA,
    AGENT_DATA,
    FILE_TREE,
    DEATH_LOOPS,
    TDA_METRICS,
    get_position_hint,
)


class GaiusCLI:
    """Non-interactive command executor."""

    def __init__(self, output: TextIO = sys.stdout, error: TextIO = sys.stderr):
        self.state = AppState()
        self.output = output
        self.error = error
        self.format = "text"
        self._load_test_data()

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        return asyncio.run(coro)

    def _load_test_data(self) -> None:
        """Initialize with static test data."""
        self.state.black_stones = GRID_DATA["black"]
        self.state.white_stones = GRID_DATA["white"]
        self.state.allocations = GRID_DATA["alloc"]
        self.state.death_loops = DEATH_LOOPS
        self.state.tda_entropy = TDA_METRICS["entropy"]

        for agent in AGENT_DATA:
            self.state.agent_positions.append((
                agent["name"],
                agent["pos"][0],
                agent["pos"][1],
                agent["color"],
            ))

    def execute(self, cmd: str) -> dict:
        """Execute a command and return result dict."""
        if cmd.startswith("/"):
            cmd = cmd[1:]

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        result = {"command": command, "args": args, "success": True, "data": {}}

        try:
            if command == "info":
                result["data"] = self._cmd_info(args)
            elif command == "goto":
                result["data"] = self._cmd_goto(args)
            elif command == "domain":
                result["data"] = self._cmd_domain(args)
            elif command == "overlay":
                result["data"] = self._cmd_overlay(args)
            elif command == "view":
                result["data"] = self._cmd_view(args)
            elif command == "state":
                result["data"] = self._cmd_state()
            elif command == "agents":
                result["data"] = self._cmd_agents()
            elif command == "grid":
                result["data"] = self._cmd_grid()
            elif command == "help":
                result["data"] = self._cmd_help()
            # Inference commands (async)
            elif command == "ask":
                result["data"] = self._run_async(self._cmd_ask(args))
            elif command == "search":
                result["data"] = self._run_async(self._cmd_search(args))
            elif command == "research":
                result["data"] = self._run_async(self._cmd_research(args))
            elif command == "technique":
                result["data"] = self._cmd_technique(args)
            elif command == "kb":
                result["data"] = self._cmd_kb(args)
            else:
                result["success"] = False
                result["error"] = f"Unknown command: {command}"
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

        return result

    def _cmd_info(self, args: str) -> dict:
        """Get info about a position."""
        if args:
            x, y = self._parse_coord(args)
        else:
            x, y = self.state.cursor_x, self.state.cursor_y

        hint = get_position_hint(x, y)
        coord = self._coord_string(x, y)

        return {
            "position": coord,
            "x": x,
            "y": y,
            "hint": hint,
            "allocation": self.state.allocations[y][x] if self.state.allocations else None,
            "has_black": (x, y) in self.state.black_stones,
            "has_white": (x, y) in self.state.white_stones,
        }

    def _cmd_goto(self, args: str) -> dict:
        """Move cursor to position."""
        if not args:
            raise ValueError("goto requires a position argument")
        x, y = self._parse_coord(args)
        self.state.cursor_x = x
        self.state.cursor_y = y
        return {"position": self._coord_string(x, y), "x": x, "y": y}

    def _cmd_domain(self, args: str) -> dict:
        """Set or get domain."""
        if args:
            self.state.domain = args
        return {"domain": self.state.domain}

    def _cmd_overlay(self, args: str) -> dict:
        """Set or cycle overlay mode."""
        if args:
            self.state.overlay_mode = OverlayMode(args.lower())
        else:
            self.state.cycle_overlay_mode()
        return {"overlay": self.state.overlay_mode.value}

    def _cmd_view(self, args: str) -> dict:
        """Set or cycle view mode."""
        if args:
            self.state.view_mode = ViewMode(args.lower())
        else:
            self.state.cycle_view_mode()
        return {"view": self.state.view_mode.value}

    def _cmd_state(self) -> dict:
        """Get full state."""
        return {
            "cursor": self._coord_string(self.state.cursor_x, self.state.cursor_y),
            "cursor_x": self.state.cursor_x,
            "cursor_y": self.state.cursor_y,
            "view_mode": self.state.view_mode.value,
            "overlay_mode": self.state.overlay_mode.value,
            "domain": self.state.domain,
            "tda_entropy": self.state.tda_entropy,
            "num_agents": len(self.state.agent_positions),
            "num_death_loops": len(self.state.death_loops),
        }

    def _cmd_agents(self) -> dict:
        """List agents."""
        agents = []
        for name, x, y, color in self.state.agent_positions:
            agents.append({
                "name": name,
                "position": self._coord_string(x, y),
                "x": x,
                "y": y,
                "color": color,
            })
        return {"agents": agents}

    def _cmd_grid(self) -> dict:
        """Get grid representation."""
        grid_str = self._render_grid_ascii()
        return {"grid": grid_str}

    def _cmd_help(self) -> dict:
        """Get help text."""
        return {
            "commands": {
                "info [pos]": "Get info about position (default: cursor)",
                "goto <pos>": "Move cursor to position",
                "domain [name]": "Set or get domain",
                "overlay [mode]": "Set or cycle overlay mode",
                "view [mode]": "Set or cycle view mode",
                "state": "Get full application state",
                "agents": "List all agents",
                "grid": "Get ASCII grid representation",
                "help": "Show this help",
                # Inference commands
                "ask <question>": "Query local LLM (optillm)",
                "search <query>": "Web search via Brave API",
                "research <topic>": "Research topic and save to KB",
                "technique [name]": "Set or show optillm technique",
                "kb <subcommand>": "KB operations (list, read <path>, search <query>)",
            }
        }

    # --- Inference Commands ---

    async def _cmd_ask(self, args: str) -> dict:
        """Query local LLM via optillm."""
        if not args:
            raise ValueError("ask requires a question")

        try:
            from .inference import get_client, Message

            client = get_client()
            result = await client.complete(
                messages=[Message(role="user", content=args)],
            )

            return {
                "response": result.content,
                "model": result.model,
                "technique": result.technique,
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
            }
        except ImportError:
            raise RuntimeError("Inference not available. Run: uv sync --extra inference")

    async def _cmd_search(self, args: str) -> dict:
        """Web search via Brave API."""
        if not args:
            raise ValueError("search requires a query")

        try:
            from .inference import get_search

            search = get_search()
            results = await search.search(args, count=5)

            return {
                "query": args,
                "results": [
                    {"title": r.title, "url": r.url, "snippet": r.snippet[:100]}
                    for r in results
                ],
            }
        except ImportError:
            raise RuntimeError("Search not available. Run: uv sync --extra inference")
        except RuntimeError as e:
            raise RuntimeError(f"Search failed: {e}")

    async def _cmd_research(self, args: str) -> dict:
        """Research topic and save to KB."""
        if not args:
            raise ValueError("research requires a topic")

        try:
            from .inference import get_client, get_search, Message
            from datetime import datetime

            # Search
            search = get_search()
            results = await search.search_for_kb(args, self.state.domain or "general")

            if not results:
                return {"error": "No search results found"}

            # Synthesize
            sources_text = "\n".join(
                f"- [{r['title']}]({r['source']}): {r['summary']}" for r in results
            )

            client = get_client()
            synthesis = await client.complete(
                messages=[
                    Message(
                        role="system",
                        content=f"You are a research assistant for {self.state.domain or 'general topics'}.",
                    ),
                    Message(
                        role="user",
                        content=f"Topic: {args}\n\nSources:\n{sources_text}\n\nCreate a structured note.",
                    ),
                ],
                technique="cot_reflection",
            )

            # Save to KB
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
            today = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().strftime("%H%M%S")
            safe_topic = args.replace(" ", "_").replace("/", "-")[:50]
            kb_path = kb_root / "scratch" / today / f"{timestamp}_{safe_topic}.md"

            kb_path.parent.mkdir(parents=True, exist_ok=True)
            content = f"# {args}\n\nCreated: {datetime.now().isoformat()}\n\n---\n\n{synthesis.content}\n\n---\n\n## Sources\n\n{sources_text}"
            kb_path.write_text(content)

            return {
                "topic": args,
                "saved_to": str(kb_path),
                "sources": len(results),
            }
        except ImportError:
            raise RuntimeError("Inference not available. Run: uv sync --extra inference")

    def _cmd_technique(self, args: str) -> dict:
        """Set or show optillm technique."""
        try:
            from .inference import get_client
            from .inference.config import OptillmTechnique

            client = get_client()

            if args:
                client.set_technique(args)
                return {"technique": args, "status": "set"}
            else:
                return {
                    "current": client.config.optillm_technique.value or "none",
                    "available": [t.value for t in OptillmTechnique if t.value],
                }
        except ImportError:
            raise RuntimeError("Inference not available. Run: uv sync --extra inference")

    def _cmd_kb(self, args: str) -> dict:
        """KB operations."""
        parts = args.split(maxsplit=1)
        subcmd = parts[0] if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        allowed_dirs = ("archive", "current", "scratch")

        if subcmd == "list":
            entries = []
            for d in allowed_dirs:
                dir_path = kb_root / d
                if dir_path.exists():
                    for f in dir_path.rglob("*.md"):
                        entries.append(str(f.relative_to(kb_root)))
            return {"entries": entries, "total": len(entries)}

        elif subcmd == "read":
            if not subargs:
                raise ValueError("kb read requires a path")
            path = kb_root / subargs
            if not path.exists():
                return {"error": f"Not found: {subargs}"}
            return {"path": subargs, "content": path.read_text()}

        elif subcmd == "search":
            if not subargs:
                raise ValueError("kb search requires a query")
            results = []
            for d in allowed_dirs:
                dir_path = kb_root / d
                if not dir_path.exists():
                    continue
                for f in dir_path.rglob("*.md"):
                    if subargs.lower() in f.name.lower():
                        results.append(str(f.relative_to(kb_root)))
                    elif subargs.lower() in f.read_text().lower():
                        results.append(str(f.relative_to(kb_root)))
            return {"query": subargs, "results": results}

        else:
            return {"error": f"Unknown kb subcommand: {subcmd}"}

    def _parse_coord(self, coord: str) -> tuple[int, int]:
        """Parse coordinate string like 'K10' to (x, y)."""
        coord = coord.strip().upper()
        if len(coord) < 2:
            raise ValueError(f"Invalid coordinate: {coord}")

        col = coord[0]
        row_str = coord[1:]

        # Handle 'I' skip
        if col >= 'J':
            x = ord(col) - ord('A') - 1
        else:
            x = ord(col) - ord('A')

        if not (0 <= x < 19):
            raise ValueError(f"Invalid column: {col}")

        try:
            row = int(row_str)
        except ValueError:
            raise ValueError(f"Invalid row: {row_str}")

        y = 19 - row
        if not (0 <= y < 19):
            raise ValueError(f"Invalid row: {row}")

        return x, y

    def _coord_string(self, x: int, y: int) -> str:
        """Convert x, y to coordinate string."""
        col = chr(65 + x + (1 if x >= 8 else 0))
        row = 19 - y
        return f"{col}{row}"

    def _render_grid_ascii(self) -> str:
        """Render simple ASCII grid."""
        lines = []
        for y in range(19):
            row = []
            for x in range(19):
                if (x, y) == (self.state.cursor_x, self.state.cursor_y):
                    row.append("X")
                elif (x, y) in self.state.black_stones:
                    row.append("#")
                elif (x, y) in self.state.white_stones:
                    row.append("O")
                else:
                    row.append(".")
            lines.append(f"{19-y:2} " + " ".join(row))
        lines.append("   " + " ".join(chr(65+i) if i < 8 else chr(66+i) for i in range(19)))
        return "\n".join(lines)

    def format_output(self, result: dict) -> str:
        """Format result based on output format."""
        if self.format == "json":
            return json.dumps(result, indent=2)
        else:
            # Text format
            if not result["success"]:
                return f"Error: {result.get('error', 'Unknown error')}"

            data = result["data"]
            if not data:
                return "OK"

            lines = []
            for key, value in data.items():
                if isinstance(value, dict):
                    lines.append(f"{key}:")
                    for k, v in value.items():
                        lines.append(f"  {k}: {v}")
                elif isinstance(value, list):
                    lines.append(f"{key}:")
                    for item in value:
                        if isinstance(item, dict):
                            lines.append(f"  - {item}")
                        else:
                            lines.append(f"  - {item}")
                else:
                    lines.append(f"{key}: {value}")
            return "\n".join(lines)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Gaius CLI - Non-interactive command mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m gaius.cli --cmd "/info K10"
  uv run python -m gaius.cli --cmd "/domain pension" --cmd "/state"
  echo "/info" | uv run python -m gaius.cli
        """
    )
    parser.add_argument(
        "--cmd", "-c",
        action="append",
        dest="commands",
        help="Command to execute (can be repeated)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )

    args = parser.parse_args()

    cli = GaiusCLI()
    cli.format = args.format

    commands = args.commands or []

    # Read from stdin if no commands and stdin is not a tty
    if not commands and not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if line:
                commands.append(line)

    if not commands:
        parser.print_help()
        sys.exit(1)

    exit_code = 0
    for cmd in commands:
        result = cli.execute(cmd)
        output = cli.format_output(result)
        print(output)
        if not result["success"]:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
