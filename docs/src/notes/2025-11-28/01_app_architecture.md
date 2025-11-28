# App Architecture Redesign

**Date**: 2025-11-28
**Session**: TUI consolidation and panel layout

## Layout Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [Status] Mode: pension │ Overlay: h1 │ Domain: asset allocation │ K10   │
├─────────┬───────────────────────────────────────────────┬───────────────┤
│ FILES   │  ┌─────────┬─────────┐                        │ CONTENT       │
│         │  │ 9×9 TOP │ 9×9 ISO │  ← Orthographic        │               │
│ /current│  │ (H1/H2) │ (3D)    │     projections        │ Selected file │
│ /scratch│  ├─────────┼─────────┤                        │ or agent      │
│ /archive│  │         │ 9×9     │                        │ output        │
│         │  │  19×19  │ RIGHT   │                        │               │
│ AGENTS  │  │  MAIN   │ (embed) │                        │               │
│         │  │  GRID   ├─────────┤                        │               │
│ Leader  │  │         │ 9×9     │                        │               │
│ Risk    │  │    ✛    │ BOTTOM  │                        │               │
│ Optim   │  │         │ (time)  │                        │               │
│ ...     │  └─────────┴─────────┘                        │               │
├─────────┴───────────────────────────────────────────────┴───────────────┤
│ > /analyze K10                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Panel System

### Left Panel (FileTree)
- Toggleable with `[` or `\`
- Tree view of KB structure:
  - `/current/projects/`
  - `/current/content/`
  - `/scratch/<iso-date>/`
  - `/archive/<quarter>/`
- Agents listed as virtual files
- Plan 9 inspired: everything is a file

### Main Area (GridView)
- Central 19×19 grid
- Orthographic mini-grids (9×9):
  - **Top**: Higher-dimensional projection (H1/H2 features)
  - **Right**: Embedding space neighborhood
  - **Bottom**: Temporal evolution
  - **ISO** (top-right): Isometric 3D projection
- Mini-grids update based on cursor position

### Right Panel (ContentView)
- Toggleable with `]` or `\`
- Shows selected file content
- Shows agent output during swarm
- Markdown rendering for .md files

### Bottom (CommandInput)
- Always visible
- `/` enters command mode
- History with up/down
- Completion with Tab

## Go Concepts

### Tenuki (手抜き)
"Playing elsewhere" - the decision to ignore local situations for bigger plays.

In Gaius:
- `t` key for tenuki: jump cursor to point of highest strategic interest
- Visual indicator when local area is "settled" vs "urgent"
- Agents can suggest tenuki moves

### Joseki / Fuseki
Standard opening patterns. In Gaius:
- Saved cursor sequences for common workflows
- Domain-specific "opening" patterns

## KB Structure

```
/current/           # Active work (manual organization)
├── projects/       # Project directories
│   └── gaius/
└── content/        # Reference content
    └── domains/

/scratch/           # Zettelkasten (auto-organized)
├── 2025-11-28/
│   ├── 1732816800.md  # Unix timestamp
│   └── 1732820400.md
└── 2025-11-29/

/archive/           # Quarterly archives
├── 2025Q4/
│   ├── projects/   # Migrated from /current
│   ├── scratch/    # Migrated from /scratch
│   └── attachments/  # Binary files (images, PDFs)
└── 2025Q3/
```

## Command Mode

Non-interactive mode for testing and scripting:

```bash
# Execute command sequence
uv run python -m gaius.cli --cmd "/domain pension" --cmd "/round" --cmd "/export"

# Pipe commands
echo "/info K10" | uv run python -m gaius.cli

# Output to stdout
uv run python -m gaius.cli --cmd "/analyze" --format json
```

## Module Structure

```
src/gaius/
├── __init__.py
├── app.py              # Main TUI application
├── cli.py              # Command-line interface (non-interactive)
├── widgets/
│   ├── __init__.py
│   ├── grid.py         # Main 19×19 grid
│   ├── minigrid.py     # 9×9 orthographic views
│   ├── filetree.py     # Left panel file browser
│   ├── content.py      # Right panel content viewer
│   └── command.py      # Bottom command input
├── core/
│   ├── __init__.py
│   ├── state.py        # Application state
│   ├── projection.py   # Grid projection logic
│   └── kb.py           # Knowledge base operations
├── agents/
│   ├── __init__.py
│   └── swarm.py        # Agent definitions
└── static/
    └── test_data.py    # Static test data for UI development
```

## Static Test Data

For UI development without live agents:

```python
TEST_DATA = {
    "grid": {
        "black": [(3,3), (15,15), (10,10)],
        "white": [(4,4), (14,14), (9,9)],
        "alloc": [[random 0-100 for 19x19]],
    },
    "agents": [
        {"name": "Leader", "pos": (10, 10), "last": "Recommend defensive..."},
        {"name": "Risk", "pos": (5, 5), "last": "Elevated risk in..."},
        ...
    ],
    "files": {
        "/current/projects/gaius": ["README.md", "notes/"],
        "/scratch/2025-11-28": ["1732816800.md"],
    },
    "death_loops": [(4,4,6,6), (12,12,14,14)],  # Bounding boxes
}
```

## CSS Architecture

Use Textual CSS properly:
- Component-scoped styles
- CSS variables for theming
- Responsive layout with fr units
- Proper docking for panels
