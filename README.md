# Gaius

**Spatial Intelligence Interface** — A CLI-first terminal for navigating complex, graph-oriented data domains.

Named after Gaius Plinius Secundus (Pliny the Elder), Gaius renders high-dimensional embeddings and topological structures onto a constrained 19×19 grid, transforming abstract complexity into spatial intuition.

```
┌─────────┬────────────────────────────┬───────────┐
│ Files/  │  ┌──────────────┬────────┐ │ Content   │
│ Agents  │  │              │  9×9   │ │           │
│         │  │    19×19     │ Views  │ │ Context & │
│ KB Nav  │  │    Main      ├────────┤ │ Details   │
│         │  │    Grid      │  Mini  │ │           │
│         │  │              │ Grids  │ │           │
│         │  ├──────────────┴────────┤ │           │
│         │  │ Think Panel / Graph   │ │           │
├─────────┴──┴───────────────────────┴─┴───────────┤
│ / Command Input                                   │
└───────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- PostgreSQL 16 (via devenv or standalone)
- Qdrant vector database
- Optional: vLLM + optillm for local inference

### Installation

```bash
# Clone the repository
git clone https://github.com/zndx/gaius.git
cd gaius

# If using devenv (recommended)
devenv shell

# Or install manually with uv
uv sync --extra search --extra tda --extra inference
```

### Configuration

Gaius uses HOCON configuration with environment variable overrides.

**1. Base configuration** (`config/base.conf`):

```hocon
gaius {
  profile = "default"
  profile = ${?GAIUS_PROFILE}

  kb {
    root = "build/dev"
    root = ${?GAIUS_KB_ROOT}
  }

  database {
    url = "postgres://localhost:5438/zndx_gaius?sslmode=disable"
    url = ${?DATABASE_URL}
  }

  vector_store {
    host = "localhost"
    port = 6339
    collection = "gaius_kb"
  }

  inference {
    backend = "optillm"
    model = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    offline_mode = false
    offline_mode = ${?GAIUS_OFFLINE}
  }
}
```

**2. Environment variables** (`.env` or export):

```bash
# Database
export DATABASE_URL="postgres://localhost:5438/zndx_gaius?sslmode=disable"

# Vector store
export QDRANT_HOST="localhost"
export QDRANT_PORT="6339"

# Inference (for swarm/summary features)
export OPTILLM_API_KEY="sk-optillm"
export GAIUS_OFFLINE="false"  # Set to true to disable LLM fallback

# Profile selection
export GAIUS_PROFILE="default"
```

**3. Profile-specific config** (`config/profiles/myprofile.conf`):

```hocon
gaius {
  profile = "myprofile"

  kb.root = "/path/to/custom/kb"

  swarm {
    enabled = true
    auto_trigger_on_domain = false
  }

  awareness {
    emphasis_hours = 48
  }
}
```

### Run Database Migrations

```bash
dbmate -d db/migrations up
```

### Start Services

```bash
# With devenv (starts postgres, qdrant, minio)
devenv up

# Or manually start each service
```

### Launch Gaius

```bash
# Interactive TUI
uv run gaius

# With specific profile
uv run gaius --profile weathership
```

---

## CLI Commands

Gaius provides a non-interactive CLI for scripting and automation.

### Basic Usage

```bash
# Get application state as JSON
uv run gaius-cli --cmd "/state" --format json

# Execute a command and get output
uv run gaius-cli --cmd "/domain pension allocation"

# Run swarm analysis
uv run gaius-cli --cmd "/swarm distributed systems"

# Get activity summary
uv run gaius-cli --cmd "/activity"

# Generate daily summary
uv run gaius-cli --cmd "/summary"
```

### Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| `/help` | Show help | `/help` |
| `/domain <name>` | Set domain focus | `/domain quantum computing` |
| `/swarm [domain]` | Run swarm analysis | `/swarm` or `/swarm ML ops` |
| `/agents` | Show agent status | `/agents` |
| `/summary` | Generate daily summary | `/summary` |
| `/activity` | Show activity log | `/activity` |
| `/reindex` | Reindex KB embeddings | `/reindex` |
| `/tda` | Show TDA metrics | `/tda` |
| `/view <mode>` | Set view mode | `/view go` or `/view pension` |
| `/overlay <mode>` | Set overlay | `/overlay risk` or `/overlay agents` |
| `/quit` | Exit application | `/quit` |

### Output Formats

```bash
# JSON output (for scripting)
uv run gaius-cli --cmd "/state" --format json

# Plain text (default)
uv run gaius-cli --cmd "/activity"
```

---

## Interactive UI Walkthrough

### Layout Overview

The Gaius TUI is organized into four main areas:

```
┌─────────────────────────────────────────────────────────────┐
│ Status Bar: Profile | Domain | View Mode | Overlay | Time   │
├─────────┬───────────────────────────────────┬───────────────┤
│         │                                   │               │
│  LEFT   │         CENTER AREA               │    RIGHT      │
│  PANEL  │                                   │    PANEL      │
│         │  Main Grid + Mini Grids           │               │
│  Files  │  Think Panel / Graph View         │   Content     │
│  Agents │                                   │               │
│         │                                   │               │
├─────────┴───────────────────────────────────┴───────────────┤
│ / Command Input                                              │
└─────────────────────────────────────────────────────────────┘
```

### 1. Main Grid (19×19)

The central visualization showing your knowledge base projected onto a Go board.

**Grid Elements:**
- **Black stones (●)**: KB entries/documents
- **White stones (○)**: Reference points or anchors
- **Cursor (◆)**: Current position (navigate with hjkl)
- **Star points (·)**: Go board reference markers
- **Candidates (1-5)**: Suggested strategic positions
- **Death loops**: Red rectangles showing topological features (H1)

**View Modes** (cycle with `v`):
- **Go**: Traditional Go board appearance
- **Pension**: Asset allocation visualization
- **Swarm**: Agent activity overlay

**Overlay Modes** (cycle with `o`):
- **None**: Clean board
- **Risk**: Risk heat map
- **H1**: First homology (loops/cycles)
- **H2**: Second homology (voids)
- **Agents**: Agent positions from swarm
- **Temporal**: Time-based coloring

### 2. Mini Grids (9×9)

Two orthographic projection views that update based on cursor position:

**Embedding View** (top right):
- Shows local neighborhood in embedding space
- Updates as you navigate the main grid
- Reveals clustering and similarity

**Isometric View** (bottom right):
- Alternative projection angle
- Shows topological relationships
- Highlights connection patterns

### 3. Left Panel: File Tree / Agents

Toggle visibility with `[` or `\`.

**File Tree Tab:**
```
/
├── current/           # Active work
│   ├── projects/
│   └── domains/
├── scratch/           # Daily notes (Zettelkasten)
│   └── 2025-11-30/
└── archive/           # Historical data
    └── 2025Q4/
```

- Navigate with arrow keys or click
- Press Enter to open file in content panel
- Supports wikilinks (`[[link]]`)
- Create new files by navigating to non-existent paths

**Agents Tab:**
- Shows active swarm agents
- Displays agent positions on grid
- Color-coded by role (Leader=red, Risk=green, etc.)

### 4. Right Panel: Content

Toggle visibility with `]` or `\`.

**Displays:**
- File contents when selected from tree
- Position context and explanations
- Command output and results
- Swarm analysis results
- Daily summaries

**Markdown rendering:**
- Headers, lists, code blocks
- Tables and emphasis
- Syntax highlighting

### 5. Think Panel / Graph View

Located below the main grid, toggles between two modes:

**Think Panel** (`Ctrl+T` or center panel mode):
- Shows reasoning traces from operations
- Displays swarm round summaries
- Token usage and latency metrics
- Operation history

**Graph View**:
- Visual representation of KB structure
- Node connections from wikilinks
- Cluster visualization

### 6. Command Input

Access with `/` key. Supports:

**Navigation:**
```
/domain <name>     Set domain focus
/view <mode>       Change view mode
/overlay <mode>    Change overlay
```

**Analysis:**
```
/swarm [domain]    Run 7-agent swarm analysis
/tda               Show topological features
/reindex           Refresh embeddings
```

**Awareness:**
```
/summary           Generate daily summary
/activity          View activity log
```

**Utility:**
```
/help              Show help
/quit              Exit application
```

### 7. Key Bindings Reference

#### Navigation
| Key | Action |
|-----|--------|
| `h` | Move cursor left |
| `j` | Move cursor down |
| `k` | Move cursor up |
| `l` | Move cursor right |
| `t` | Tenuki - jump to strategic point |

#### View Controls
| Key | Action |
|-----|--------|
| `v` | Cycle view modes (go → pension → swarm) |
| `o` | Cycle overlay modes |
| `c` | Toggle candidate markers |
| `[` | Toggle left panel |
| `]` | Toggle right panel |
| `\` | Toggle both panels |

#### Commands
| Key | Action |
|-----|--------|
| `/` | Enter command mode |
| `?` | Show help |
| `q` | Quit |

#### Note Editing
| Key | Action |
|-----|--------|
| `Ctrl+N` | Open note editor |
| `Ctrl+S` | Save note (in editor) |
| `Escape` | Close editor |

---

## Features Deep Dive

### Swarm Analysis

The DeepAgents swarm runs 7 specialized agents in parallel:

| Agent | Role | Behavior |
|-------|------|----------|
| **Leader** | Strategic oversight | Central position, synthesizes consensus |
| **Risk** | Threat identification | Peripheral scanning, conservative |
| **Optimizer** | Opportunity seeking | Random exploration, aggressive |
| **Planner** | Long-term trajectory | Central focus, methodical |
| **Critic** | Assumption challenging | Edge positions, high temperature |
| **Executor** | Action simulation | Random, implementation focus |
| **Adversary** | Plan breaking | Peripheral, stress testing |

**Run swarm:**
```
/swarm                          # Analyze current domain
/swarm quantum error correction # Analyze specific domain
```

**View results:**
- Agent positions appear on grid with color coding
- Consensus summary in content panel
- Token usage in think panel

### Situational Awareness

On startup, Gaius generates a situational awareness report:

**Time Horizons:**
- **Emphasis** (24h): Urgent items, recent activity
- **Tactical** (7d): Short-term planning
- **Strategic** (90d): Medium-term trends
- **Secular** (365d): Long-term patterns

**Activity Tracking:**
- Queries and searches
- Domain changes
- Swarm runs with token counts
- KB entry creation

### Daily Summary

Generate an AI-synthesized summary of the day:

```
/summary
```

**Includes:**
- Activity metrics (queries, swarm runs, tokens)
- Key KB entries created
- AI-generated insights
- Recommended focus for tomorrow

Summaries are saved to:
- Database (`daily_summaries` table)
- KB scratch (`build/dev/scratch/YYYY-MM-DD/daily-summary.md`)

### Topological Data Analysis (TDA)

Gaius computes persistent homology features:

**H0 (Components):** Connected clusters in your KB
**H1 (Loops):** Cyclical relationships, "death loops"
**H2 (Voids):** Higher-dimensional cavities

```
/tda                # Show TDA metrics
/overlay h1         # Visualize loops on grid
```

---

## Configuration Reference

### Full HOCON Schema

```hocon
gaius {
  # Application identity
  app {
    name = "Gaius"
    version = "0.2.0"
    subtitle = "Spatial Intelligence Interface"
  }

  # Active profile
  profile = "default"
  profile = ${?GAIUS_PROFILE}

  # Knowledge Base paths
  kb {
    root = "build/dev"
    current = ${gaius.kb.root}/current
    scratch = ${gaius.kb.root}/scratch
    archive = ${gaius.kb.root}/archive
  }

  # Database
  database {
    url = "postgres://localhost:5438/zndx_gaius?sslmode=disable"
    pool_size = 10
  }

  # Vector store (Qdrant)
  vector_store {
    host = "localhost"
    port = 6339
    collection = "gaius_kb"
    embedding_model = "all-MiniLM-L6-v2"
  }

  # Inference
  inference {
    backend = "optillm"  # optillm, vllm, openai
    model = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    fallback_model = "gpt-4o-mini"
    offline_mode = false
    timeout = 60
    max_tokens = 2048

    optillm {
      url = "http://localhost:8080/v1"
      api_key = "sk-optillm"
      technique = ""
    }

    vllm {
      url = "http://localhost:8088/v1"
    }

    phase_models {
      exploration = ${gaius.inference.model}
      synthesis = ${gaius.inference.model}
      evaluation = "claude-sonnet-4-20250514"
    }
  }

  # Search
  search {
    hybrid {
      bm25_weight = 0.3
      vector_weight = 0.7
    }
    max_results = 20
  }

  # Worker pool
  workers {
    pool_size = 4
    poll_interval = 30
    job_timeout = 300
  }

  # Swarm agents
  swarm {
    enabled = true
    auto_trigger_on_domain = true
    roles = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]
  }

  # TDA
  tda {
    enabled = true
    compute_interval_minutes = 60
    projection_method = "umap"
  }

  # UI state
  ui {
    left_panel_visible = true
    right_panel_visible = true
    view_mode = "go"
    overlay_mode = "none"
    center_panel_mode = "graph"
  }

  # Startup
  startup {
    commands = []
    show_situational = true
  }

  # Awareness horizons
  awareness {
    emphasis_hours = 24
    default_horizon_days = 7
    strategic_horizon_days = 90
    secular_horizon_days = 365
  }

  # Telemetry
  telemetry {
    enabled = false
    exporter = "console"
    endpoint = "http://localhost:4317"
    service_name = "gaius"
  }
}
```

---

## Architecture

```
src/gaius/
├── app.py              # Main TUI application
├── cli.py              # Non-interactive CLI
├── core/
│   ├── config.py       # HOCON configuration
│   ├── state.py        # Application state
│   ├── activity.py     # Activity tracking
│   ├── projection.py   # Embedding → grid projection
│   ├── tda.py          # Topological data analysis
│   └── telemetry.py    # OpenTelemetry integration
├── awareness/
│   └── situational.py  # Startup reports
├── agents/
│   ├── roles.py        # 7 agent role definitions
│   ├── swarm.py        # Swarm orchestration
│   └── daily_summary.py # Daily summary agent
├── inference/
│   ├── client.py       # Unified inference client
│   ├── router.py       # Phase-based model routing
│   └── synthesis.py    # Zettelkasten synthesis
├── widgets/
│   ├── grid.py         # 19×19 main grid
│   ├── minigrid.py     # 9×9 orthographic views
│   ├── filetree.py     # KB navigation
│   ├── content.py      # Content display
│   ├── think_panel.py  # Reasoning traces
│   └── command.py      # Command input
└── workers/
    └── processing/     # Background workers
```

---

## Development

```bash
# Run the TUI
uv run gaius

# Run tests
uv run pytest

# Build documentation
mdbook build docs

# Type checking
uv run mypy src/gaius
```

---

## Inspirations

- **Go board**: Spatial metaphor, 19×19 grid, tenuki concept
- **Bloomberg Terminal**: Information density, keyboard-first
- **Plan 9 / Acme**: Everything is a file, text as command
- **Claude Code**: Slash commands, conversational interface
- **CAD orthographic views**: Multiple projection views

---

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

Copyright 2025 Ryan Hill and Zndx Limited

---

*"Turn any complex strategic domain into spatial intuition."*
