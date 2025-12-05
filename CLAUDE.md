# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gaius is a CLI-first terminal interface for navigating complex, graph-oriented data domains. Named after Gaius Plinius Secundus (Pliny the Elder), it renders high-dimensional embeddings and topological structures onto a constrained 19×19 grid—transforming abstract complexity into spatial intuition.

## Development Commands

```bash
# Run the TUI application
uv run gaius

# Run the CLI (non-interactive, for testing)
uv run gaius-cli --cmd "/state" --format json

# Build documentation
mdbook build docs

# Build and open documentation
mdbook build docs --open
```

## Module Structure

```
src/gaius/
├── app.py              # Main TUI application (GaiusApp)
├── cli.py              # Non-interactive CLI
├── __main__.py         # Module entry point
├── core/
│   └── state.py        # AppState, ViewMode, OverlayMode
├── widgets/
│   ├── grid.py         # MainGrid (19×19)
│   ├── minigrid.py     # MiniGrid (9×9 orthographic views)
│   ├── filetree.py     # FileTree (KB navigation)
│   ├── content.py      # ContentPanel (right panel)
│   └── command.py      # CommandInput (bottom)
├── static/
│   └── test_data.py    # Static data for UI development
└── agents/             # Agent definitions (planned)
```

## Key Components

**MainGrid**: 19×19 Go board with view modes (Go, Pension, Swarm) and overlays (none, risk, h1, h2, agents, temporal).

**MiniGridPanel**: Three 9×9 orthographic projections that update based on cursor position - CAD-style views showing topology, embeddings, and temporal evolution.

**FileTree**: Plan 9-inspired navigation where agents are represented as files under `/agents/`.

**ContentPanel**: Displays file contents, agent output, and position context.

**CommandInput**: Claude Code-style slash commands with history.

### Key Bindings

- `hjkl`: Navigate cursor (vim-style)
- `v`: Cycle view modes
- `o`: Cycle overlay modes
- `c`: Toggle candidate markers
- `[`/`]`: Toggle left/right panels
- `\`: Toggle both panels
- `/`: Enter command mode
- `?`: Show help
- `t`: Tenuki (jump to strategic point)
- `q`: Quit

## Knowledge Base Structure

Development KB lives under `build/dev/` (gitignored):

```
build/dev/
├── current/            # Active work (manual)
│   ├── projects/
│   └── content/domains/
├── scratch/            # Zettelkasten (by date)
│   └── 2025-11-28/
└── archive/            # Quarterly archives
    └── 2025Q4/attachments/
```

## Dependencies

Core (always): `textual>=0.60.0`

Optional:
- TDA: `numpy`, `scikit-learn`, `giotto-tda` (requires Python 3.11)
- Swarm: `langchain`, `langchain-openai`

Install optional deps: `uv sync --extra tda` or `uv sync --extra swarm`

## Documentation

mdbook documentation in `docs/`. Save work summaries and notes to `docs/notes/$(date --iso-8601)/` with zero-padded numeric prefixes.

## Design Inspirations

- **Go board**: Spatial metaphor, 19×19 grid, tenuki concept
- **Bloomberg Terminal**: Information density, keyboard-first
- **Plan 9 / Acme**: Everything is a file, text as command
- **Claude Code**: Slash commands, conversational interface
- **CAD orthographic views**: Multiple projection views updating together
- Do not rely on fallbacks nor workarounds when testing; all functional aspects of new features must be verified directly.
- We do _not_ fall back to static test data in this application.