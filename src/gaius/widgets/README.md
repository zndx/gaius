# Gaius Widgets

Textual-based TUI components for the Gaius spatial intelligence interface.

## Layout

```
┌─────────┬────────────────────────────┬───────────┐
│ Left    │  ┌──────────────┬────────┐ │ Right     │
│ Panel   │  │              │  9×9   │ │ Panel     │
│         │  │    19×19     │ Embed  │ │           │
│ Files/  │  │    Main      ├────────┤ │ Content   │
│ Agents  │  │    Grid      │  9×9   │ │           │
│         │  │              │  Iso   │ │           │
│         │  ├──────────────┴────────┤ │           │
│         │  │◉ RA 12h30m Dec +45° ψ │ │           │
│         │  ├───────────────────────┤ │           │
│         │  │ Note Editor (Ctrl-N)  │ │           │
│         │  └───────────────────────┘ │           │
├─────────┴────────────────────────────┴───────────┤
│ / Command                                         │
└───────────────────────────────────────────────────┘
```

## Module Structure

```
widgets/
├── __init__.py             # Module exports
├── grid.py                 # MainGrid (19×19)
├── minigrid.py             # MiniGrid (9×9)
├── filetree.py             # FileTree navigation
├── content.py              # ContentPanel (right)
├── command.py              # CommandInput (bottom)
├── location.py             # LocationIndicator
├── note_editor.py          # Inline note editing
├── graph_view.py           # Wiki-link graph
├── think_panel.py          # Reasoning traces
├── evolution_panel.py      # Evolution status
├── init_panel.py           # Initialization progress
├── observe_panel.py        # Health metrics
├── splash.py               # Splash screen
└── connection_indicator.py # gRPC status
```

## Core Widgets

### MainGrid (19×19)

The primary Go board grid displaying KB documents:

```python
from gaius.widgets.grid import MainGrid

grid = MainGrid(state=app_state)
```

**Features:**
- Go board coordinate system (A1-T19, skipping I)
- Star points (hoshi) at standard positions
- Document markers (black stones)
- Cursor position with vim-style navigation (hjkl)
- View mode overlays (Topology, Geometry, Dynamics, Agents)

**Rendering:**
```
   A B C D E F G H J K L M N O P Q R S T
19 · · · · · · · · · · · · · · · · · · · 19
18 · · · · · · · · · · · · · · · · · · · 18
...
16 · · · + · · · · · + · · · · · + · · · 16  ← Star points
...
 1 · · · · · · · · · · · · · · · · · · ·  1
   A B C D E F G H J K L M N O P Q R S T
```

### MiniGrid (9×9)

Orthographic projections for detailed analysis:

```python
from gaius.widgets.minigrid import MiniGrid

embed_view = MiniGrid(title="Embed", data=similarity_matrix)
iso_view = MiniGrid(title="Iso", data=curvature_matrix)
```

**Views:**
- **Embed**: Cosine similarity spotlight around cursor
- **Iso**: Ricci curvature elevation map (four modes: κ, π, σ, β)

**Unicode Intensity:**
| Value | Character | Meaning |
|-------|-----------|---------|
| >0.8 | █ | Very high |
| >0.6 | ▓ | High |
| >0.4 | ▒ | Medium |
| >0.2 | ░ | Low |
| >0.05 | · | Minimal |
| ≤0.05 | (space) | None |

### FileTree

Plan 9-inspired file navigation:

```python
from gaius.widgets.filetree import FileTree

tree = FileTree(root_path="build/dev")
```

**Structure:**
```
/agents/
├── leader
├── risk
├── optimizer
└── planner
/files/
├── current/
│   └── topics/
└── scratch/
    └── 2025-12-13/
```

**Events:**
- `FileTreeSelection` - File selected
- `FileTreeHighlight` - Cursor moved

### ContentPanel

Right panel displaying file contents and agent output:

```python
from gaius.widgets.content import ContentPanel

panel = ContentPanel(state=app_state)
```

**Features:**
- Markdown rendering
- Wikilink support (`[[links]]`)
- Agent response display
- Position context

### CommandInput

Claude Code-style slash command input:

```python
from gaius.widgets.command import CommandInput, CommandSubmitted

cmd = CommandInput()
```

**Slash Commands:**
- `/search <query>` - Search KB
- `/domain <name>` - Set domain focus
- `/swarm [domain]` - Run multi-agent analysis
- `/explain [pos]` - Explain grid position
- `/tda` - Show topological features
- `/fmea` - FMEA health summary

**Events:**
- `CommandSubmitted` - Command entered

### LocationIndicator

Celestial-style position display:

```
◉ RA 12h30m Dec +45° ψ=0.85
```

Components:
- Position as RA/Dec (Right Ascension, Declination)
- ψ (psi) = relevance score
- Optional Iso mode indicator (κ/π/σ/β)

## Panel Widgets

### ThinkPanel

Displays reasoning traces from agent operations:

```python
from gaius.widgets.think_panel import ThinkPanel

panel = ThinkPanel()
panel.add_trace(trace)
```

**Trace Structure:**
```
[12:34:56] search "persistent homology"
├── 5 sources consulted
├── cot_reflection technique
└── 1,234 tokens (450ms)
```

### EvolutionPanel

Evolution daemon monitoring:

```python
from gaius.widgets.evolution_panel import EvolutionPanel

panel = EvolutionPanel()
```

**Displays:**
- Current cycle status
- Agent scores
- Improvement trends
- Resource usage

### InitPanel

Initialization progress during startup:

```python
from gaius.widgets.init_panel import InitPanel

panel = InitPanel()
```

**Phases:**
1. TELEMETRY - OpenTelemetry setup
2. BACKENDS - optillm/vLLM controllers
3. ORCHESTRATOR - Endpoint management
4. ENDPOINTS - vLLM startup (~240s for 70B)
5. COMPLETE - Ready

### ObservePanel

Operational health metrics:

```python
from gaius.widgets.observe_panel import ObservePanel

panel = ObservePanel()
```

**Metrics:**
- GPU memory/temperature
- Endpoint health
- Request latency
- Queue depth

### GraphView

Wiki-link graph visualization:

```python
from gaius.widgets.graph_view import GraphView

view = GraphView(links=document_links)
```

**Features:**
- Force-directed layout
- Highlight connected nodes
- Navigate via links

## Key Bindings

| Key | Action |
|-----|--------|
| `hjkl` | Navigate cursor (vim-style) |
| `v` | Cycle view modes (Go → Theta → Swarm) |
| `o` | Cycle overlay modes |
| `i` | Cycle Iso modes (κ → π → σ → β) |
| `g` | Toggle center panel (Graph → Think → Evolution) |
| `[` | Toggle left panel |
| `]` | Toggle right panel |
| `\` | Toggle both panels |
| `/` | Enter command mode |
| `?` | Show help |
| `t` | Tenuki (jump to strategic point) |
| `Ctrl-N` | Open note editor |
| `q` | Quit |

## Reactive State

Widgets react to `AppState` changes:

```python
from gaius.core.state import AppState, ViewMode, OverlayMode

state = AppState()
state.view_mode = ViewMode.SWARM
state.overlay_mode = OverlayMode.TOPOLOGY
state.cursor_x = 9
state.cursor_y = 9
```

**Reactive Properties:**
- `cursor_x`, `cursor_y` - Cursor position
- `view_mode` - Current view
- `overlay_mode` - Active overlay
- `iso_mode` - Iso view mode (κ/π/σ/β)
- `center_panel_mode` - Center panel state

## Styling

CSS-in-Python via Textual:

```python
class MainGrid(Widget):
    DEFAULT_CSS = """
    MainGrid {
        width: 100%;
        height: 100%;
        min-width: 40;
        min-height: 21;
    }
    """
```

**Color Scheme:**
- `$primary` - Main accent
- `$success` - Positive indicators
- `$warning` - Attention needed
- `$error` - Errors/failures
- `dim` - Subtle elements

## See Also

- [Parent README](../README.md) - Module overview
- [Core README](../core/README.md) - State management
- [app.py](../app.py) - Main TUI application
