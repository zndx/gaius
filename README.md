# Gaius

A terminal interface for navigating graph-oriented data domains. Projects high-dimensional embeddings onto a 19×19 grid.

![Gaius TUI](docs/current/src/img/risk_md.png)

## Overview

Gaius renders knowledge bases and document collections as spatial layouts, using topological data analysis to identify structural patterns. The interface combines a Go board metaphor with orthographic projections and multi-agent analysis.

Named after Gaius Plinius Secundus (Pliny the Elder).

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- PostgreSQL 16
- Qdrant vector database
- Optional: vLLM + optillm for local inference

## Installation

```bash
git clone https://github.com/zndx/gaius.git
cd gaius

# Using devenv (recommended)
devenv shell

# Or with uv
uv sync --extra search --extra tda --extra inference
```

## Configuration

Uses HOCON configuration with environment variable overrides.

```bash
# Required
export DATABASE_URL="postgres://localhost:5438/zndx_gaius?sslmode=disable"

# Optional inference
export OPTILLM_API_KEY="sk-optillm"
export GAIUS_OFFLINE="false"
```

See `config/base.conf` for full configuration options.

### Security: gRPC Gateway Architecture

Gaius enforces a **secure-by-default** inference architecture. All inference requests route through the gRPC engine, which serves as the control plane for:

- Authentication and authorization
- Audit logging
- Resource management and rate limiting

**Direct HTTP access to optillm/vLLM is disabled by default.** The TUI and CLI will fail to start if the gRPC engine is unavailable.

For development and debugging, fallbacks can be explicitly enabled:

```bash
# Enable direct HTTP fallbacks (dev/debug only)
export GAIUS_ALLOW_FALLBACKS=true
```

When fallbacks are enabled, a warning is logged:
```
FALLBACK: Using direct HTTP to optillm/vLLM - bypasses gRPC auth/authz.
This is enabled via GAIUS_ALLOW_FALLBACKS=true (dev/debug mode).
```

**Production deployments should never set `GAIUS_ALLOW_FALLBACKS=true`**. The gRPC engine provides the security boundary for enterprise operations.

## Usage

```bash
# Run database migrations
dbmate -d db/migrations up

# Start TUI
uv run gaius

# CLI mode
uv run gaius-cli --cmd "/state" --format json
```

## Key Bindings

| Key | Action |
|-----|--------|
| `hjkl` | Navigate grid |
| `v` | Cycle view modes |
| `o` | Cycle overlays |
| `g` | Toggle center panel (Graph/Think) |
| `[` `]` | Toggle side panels |
| `/` | Command input |
| `?` | Help |

## Commands

| Command | Description |
|---------|-------------|
| `/search <query>` | Search KB files and content |
| `/research <topic>` | Web search + LLM synthesis to KB |
| `/explain [pos]` | Explain grid position with differential geometry (saves to KB) |
| `/domain <name>` | Set domain focus |
| `/swarm [domain]` | Run multi-agent analysis |
| `/summary` | Generate daily summary |
| `/activity` | View activity log |
| `/tda` | Show topological features |
| `/reindex` | Refresh embeddings |

## Layout

```
┌─────────┬──────────────┬───────┬─────────┬──────────┐
│ Agents  │              │ Embed │ Graph/  │   Info   │
│ ─────── │  19×19 Grid  │  9×9  │ Think   │          │
│ Files   │              ├───────┤         │          │
│         │              │  Iso  │         │          │
│         │              │  9×9  │         │          │
│         ├──────────────┴───────┴─────────┤          │
│         │         Content / Edit         │          │
├─────────┴────────────────────────────────┴──────────┤
│ / Command                                           │
└─────────────────────────────────────────────────────┘
```

## Features

**Grid Visualization**
- KB entries projected onto 19×19 board via UMAP
- View modes: Go, Theta, Swarm
- Overlays: Risk, H1/H2 homology, Agents, Temporal

**Orthographic Mini-Grids (9×9)**
- **Embed view**: Cosine similarity spotlight around cursor document
- **Iso view**: Ricci curvature elevation map (boundaries vs interiors)
- Unicode block visualization (█▓▒░·) for spatial intuition

**Differential Geometry**
- Ricci curvature computation on semantic manifold
- Visual interpretation: bright Embed + low Iso = cluster core
- `/explain` generates LLM interpretations saved as KB notes
- Captures mini-grid snapshots in zettelkasten format

**Multi-Agent Analysis**
- 7 specialized agents (Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary)
- Parallel execution with consensus synthesis

**Knowledge Base**
- Zettelkasten-style organization
- Wikilink support (`[[links]]`)
- Markdown rendering

**Topological Analysis**
- Persistent homology computation
- H0 (components), H1 (loops), H2 (voids)
- Visual overlay on grid

## Architecture

```
src/gaius/
├── app.py              # TUI application
├── cli.py              # Non-interactive CLI
├── mcp_server.py       # MCP server for Claude Code integration
├── core/
│   ├── config.py       # HOCON configuration
│   ├── state.py        # Application state
│   ├── projection.py   # UMAP grid projection
│   ├── tda.py          # Topological data analysis
│   ├── geometry.py     # Ricci curvature computation
│   ├── minigrids.py    # 9×9 orthographic views
│   └── kb_capture.py   # Zettelkasten note generation
├── agents/             # Swarm roles and orchestration
├── inference/          # LLM client, synthesis, embeddings
├── widgets/            # Grid, panels, command input
└── awareness/          # Situational reports
```

## MCP Server

Gaius includes an MCP server for integration with Claude Code and other MCP clients.

```bash
# Run MCP server
uv run gaius-mcp
```

**Key Tools:**
- `search_kb`, `read_kb`, `create_kb` - Knowledge base operations
- `explain_grid_position` - Differential geometry explanation with KB capture
- `run_swarm` - Multi-agent analysis
- `semantic_search` - Vector similarity search
- `research_topic` - Web search + LLM synthesis

See `src/gaius/mcp_server.py` for full tool list.

## Development

```bash
uv run gaius              # Run TUI
uv run pytest             # Run tests
mdbook build docs         # Build documentation
```

## License

Apache License 2.0

Copyright 2025 Ryan Hill and Zndx Limited
