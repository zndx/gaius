# Getting Started

Gaius is a CLI-first terminal interface for navigating complex, graph-oriented data domains. It renders high-dimensional embeddings and topological structures onto a constrained 19x19 grid, transforming abstract complexity into spatial intuition.

There are three ways to interact with Gaius:

- **TUI** -- a full terminal interface with grid, panels, and keyboard navigation (`uv run gaius`)
- **CLI** -- a non-interactive command runner for scripting and automation (`uv run gaius-cli`)
- **MCP** -- 163 tools exposed to Claude Code and other MCP-compatible clients (`uv run gaius-mcp`)

## Quick Path

If you already have devenv and Nix installed, you can be running in under a minute:

```bash
cd gaius
devenv shell
uv sync
devenv processes up -d
uv run gaius
```

This starts the platform services (PostgreSQL, Qdrant, gRPC engine, NiFi) and launches the TUI. You will see a 19x19 grid with a cursor at the center.

## What to Read Next

If this is your first time:

1. **[Installation](./installation.md)** -- prerequisites and environment setup
2. **[First Launch](./first-launch.md)** -- what happens when you start Gaius and what to try first

Once you are comfortable with the basics:

- **[The TUI](./tui.md)** -- understanding the five interface components
- **[Navigation](./navigation.md)** -- cursor movement, view modes, and workflow patterns
- **[The CLI](./cli.md)** -- non-interactive commands for scripting
- **[MCP Integration](./mcp.md)** -- connecting Gaius to Claude Code

## Three Interfaces, One Engine

All three interfaces communicate with the same gRPC engine on port 50051. A `/health` command run from the CLI produces the same result as the `health_observer_status` MCP tool or pressing `/` and typing `health` in the TUI. Choose the interface that fits your context: TUI for exploration, CLI for automation, MCP for AI-assisted workflows.
