# Gaius

A terminal interface for navigating graph-oriented data domains. Projects high-dimensional embeddings onto a 19×19 grid.

![Gaius TUI](docs/current/src/img/risk_md.png)

## Overview

Gaius renders knowledge bases and document collections as spatial layouts, using topological data analysis to identify structural patterns. The interface combines a Go board metaphor with orthographic projections and multi-agent analysis.

Named after Gaius Plinius Secundus (Pliny the Elder).

## Philosophy

The Gaius Project deliberately supports continuous agent collaboration at every level. Dynamic agent interaction spans all components: from knowledge base analysis with local SLM swarms, to operations-oriented agents powered by special purpose models (Orchestrator-8B, Magma-8B), to periodic content-informed reasoning and reflection.

This extends to long-term codebase development itself, in collaboration with Claude Code. This is a deliberate departure from the traditional paradigm where software is developed to a point release, then packaged for end users. Gaius is intended to be cloned, not packaged—engineered to provide a foundation for agent collaboration in any knowledge domain, such that the codebase and model suite can be adaptively co-developed *in situ* through Rapid Agent Systems Engineering (RASE).

Central to RASE is *intrinsic verifiability*: the operational environment itself serves as the verification oracle, enabling autonomous capability development without external labeling dependencies.

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- PostgreSQL 16
- Qdrant vector database

**Platform-specific:**
- **macOS (Apple Silicon)**: exo + MLX for local inference
- **Linux (NVIDIA)**: vLLM + optillm for local inference

## Installation

```bash
git clone https://github.com/zndx/gaius.git
cd gaius

# Using devenv (recommended)
devenv shell

# Or with uv
uv sync --extra search --extra tda --extra inference
```

## Onboarding

Gaius supports two platform configurations:

| Platform | Local Inference | Heavy Workloads |
|----------|-----------------|-----------------|
| **MLX** (MacBook) | exo + MLX models | Cerebras, xAI, Bytez APIs |
| **CUDA** (Tinybox) | vLLM + optillm | Local GPU cluster |

### Step 1: Platform Detection

Gaius auto-detects your platform, or you can set it explicitly:

```bash
# Auto-detect (default)
unset GAIUS_PLATFORM

# Force MLX mode (Apple Silicon)
export GAIUS_PLATFORM=mlx

# Force CUDA mode (NVIDIA GPUs)
export GAIUS_PLATFORM=cuda
```

### Step 2: Local Inference Setup

#### Apple Silicon (MLX Platform)

Install [exo](https://github.com/exo-explore/exo) for local MLX inference:

```bash
# Clone and install exo
git clone https://github.com/exo-explore/exo.git
cd exo
pip install -e .

# Optimize GPU memory allocation (recommended)
./configure_mlx.sh

# Start exo (runs on http://localhost:52415)
python -m exo
```

**Requirements:**
- macOS 14.0 (Sonoma) or later
- Apple Silicon (M1/M2/M3/M4)
- Native ARM Python (`python -c "import platform; print(platform.processor())"` should print `arm`)

**Verify exo is running:**
```bash
curl http://localhost:52415/v1/models
```

#### Linux (CUDA Platform)

Use devenv to manage vLLM and optillm:

```bash
# Start all services (PostgreSQL, Qdrant, vLLM, optillm)
devenv processes up

# Or start individually
devenv tasks run vllm:start
devenv tasks run optillm:start
```

### Step 3: Remote API Keys

For heavy workloads (reasoning, orchestration, thinking), Gaius uses external APIs. This preserves MacBook battery while providing access to frontier models.

#### Cerebras (GLM-4.7 for orchestration + thinking)

1. Go to [cloud.cerebras.ai](https://cloud.cerebras.ai) and create an account
2. Click **API Keys** in the left sidebar
3. Click **Generate API Key** and copy it immediately

```bash
export CEREBRAS_API_KEY="your-key-here"
```

**Why Cerebras?** Extremely fast inference speeds with GLM-4.7's interleaved thinking capability.

#### xAI (Grok 4.1 for reasoning)

1. Go to [console.x.ai](https://console.x.ai) and sign in (Google, X/Twitter, or email)
2. Navigate to **API Keys** in the left sidebar
3. Click **Create API Key**, configure permissions, and copy it

```bash
export XAI_API_KEY="xai-your-key-here"
```

**Why xAI?** Grok 4.1 Fast offers a **2 million token** context window with chain-of-thought reasoning.

#### Bytez (Mistral 7B for fast-remote fallback)

1. Go to [bytez.com/api](https://bytez.com/api) and create an account
2. Copy your API key from the dashboard

```bash
export BYTEZ_API_KEY="your-key-here"
```

**Why Bytez?** Provides the same Mistral-7B-Instruct model used on CUDA, ensuring consistent behavior across platforms. Useful when local MLX is busy.

### Step 4: Environment Configuration

Create a `.env` file or add to your shell profile:

```bash
# Database (required)
export DATABASE_URL="postgres://localhost:5438/zndx_gaius?sslmode=disable"

# Platform (optional, auto-detected)
export GAIUS_PLATFORM=mlx

# Remote APIs (MLX platform)
export CEREBRAS_API_KEY="your-cerebras-key"
export XAI_API_KEY="xai-your-xai-key"
export BYTEZ_API_KEY="your-bytez-key"

# Local inference (optional overrides)
export EXO_API_URL="http://localhost:52415/v1"  # Default exo endpoint
```

### Step 5: Verify Setup

```bash
# Check platform detection
uv run gaius-cli --cmd "/state" --format json | jq '.platform'

# Check endpoint status
uv run gaius-cli --cmd "/gpu status" --format json

# Run health diagnostics
uv run gaius-cli --cmd "/health"
```

### MLX Agent Summary

| Agent | Model | Backend | Purpose |
|-------|-------|---------|---------|
| `fast` | Ministral-3-3B | exo (local) | Quick responses |
| `fast-remote` | Mistral-7B | Bytez | Fallback when local busy |
| `instruct-local` | Ministral-3-8B | exo (local) | Moderate tasks |
| `orchestrator` | GLM-4.7 | Cerebras | Request routing |
| `reasoning` | Grok 4.1 Fast | xAI | Deep analysis (2M context) |
| `thinking` | GLM-4.7 | Cerebras | Extended reasoning |
| Swarm (7 agents) | Qwen3-1.7B | exo (local) | CLT-ready evolution |

## Configuration

Uses HOCON configuration with environment variable overrides. See `config/agents-mlx.conf` for MLX platform settings and `config/agents-cuda.conf` for CUDA.

```bash
# Required
export DATABASE_URL="postgres://localhost:5438/zndx_gaius?sslmode=disable"

# Optional
export GAIUS_OFFLINE="false"
```

See `config/base.conf` for full configuration options.

### Security: gRPC Gateway Architecture

Gaius enforces a **secure-by-default** inference architecture. All inference requests route through the gRPC engine, which serves as the control plane for:

- Authentication and authorization
- Audit logging
- Resource management and rate limiting

All clients (TUI, CLI, MCP) connect to the engine via gRPC. The engine must be running for any client to function.

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

### Global Navigation

| Key | Action |
|-----|--------|
| `hjkl` | Navigate grid cursor |
| `g` | Cycle center panels (Graph → Think → Evolve → Observe) |
| `v` | Cycle view modes |
| `o` | Cycle overlays |
| `[` | Toggle left panel (FileTree) |
| `]` | Toggle right panel (Info) |
| `\` | Toggle both side panels |
| `/` | Enter command mode |
| `?` | Show help |
| `q` | Quit |

### FileTree (Left Panel)

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate tree items |
| `Enter` | Open selected file |
| `Space` | Expand/collapse folder |
| `G` | Jump to last item (expands folders to find deepest leaf) |
| `Ctrl-F` | Page down (half page) |
| `Ctrl-BB` | Page up (half page) — requires double-press, known bug |

### Editor Panel (Normal Mode)

Vim-style modal editing for KB files.

| Key | Action |
|-----|--------|
| `i` | Insert at cursor |
| `I` | Insert at line beginning |
| `a` | Append after cursor |
| `A` | Append at line end |
| `o` | Open line below |
| `O` | Open line above |
| `ESC` | Exit insert mode → normal mode |
| `:q` | Close editor |
| `:wq` | Save and close (auto-saves, so same as :q) |
| `:<number>` | Go to line number (e.g., `:42`) |
| `:mv <path>` | Move file to path |
| `:rename [name]` | Move to scratch with optional name |

### Editor Panel (Navigation)

Works in both normal and insert modes.

| Key | Action |
|-----|--------|
| `↑` `↓` `←` `→` | Scroll viewport (browser-style) |
| `Ctrl-F` | Page down |
| `Ctrl-B` | Page up |
| `G` | Jump to end of document |
| `hjkl` | Pass through to main grid (normal mode only) |

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
| `/ambient status` | Show ambient workload daemon status |
| `/ambient start` | Start ambient background processing |
| `/ambient stop` | Stop ambient background processing |
| `/ambient buffer` | Export buffered content to zettelkasten note |
| `/gpu status` | Show GPU endpoint status |
| `/health` | Run health diagnostics |
| `/health fix <svc>` | Auto-remediate unhealthy service |

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
