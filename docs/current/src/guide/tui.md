# The TUI

Gaius renders a full terminal interface built on the Textual framework. The interface draws inspiration from Bloomberg Terminal (information density), Plan 9's Acme (everything is a file), and CAD orthographic views (multiple synchronized projections).

Launch the TUI with:

```bash
uv run gaius
```

## Five Components

The interface is composed of five primary widgets:

### MainGrid

The 19x19 grid occupies the center of the screen. It is the primary workspace -- a spatial representation of high-dimensional data projected onto a Go board layout via UMAP (cosine metric, k=15, min_dist=0.1). Grid positions correspond to embedded data points, and the cursor (`✛`) indicates your current focus.

Three **view modes** (cycled with `v`):

| Mode | What it shows |
|------|---------------|
| **Go** | Entity positions as stones on a standard Go board with star points (hoshi) |
| **Theta** | Information density view -- temporal knowledge consolidation state |
| **Swarm** | Agent positions and cluster dynamics during multi-agent analysis |

Four **overlay modes** (cycled with `o`) layer additional information:

| Overlay | What it reveals |
|---------|----------------|
| **Topology** | H0/H1/H2 persistent homology features -- death loops (`⚠`) mark persistent 1-cycles |
| **Geometry** | Ollivier-Ricci curvature heatmap -- positive (cluster interior) vs. negative (boundary) |
| **Dynamics** | Gradient vector field showing direction of semantic change |
| **Agents** | Agent positions colored by role (Leader, Risk, Optimizer, etc.) |

### MiniGridPanel

Three 9x9 orthographic projections update as you move the cursor:

| View | Content | Visualization |
|------|---------|---------------|
| **Embed** | Local cosine-similarity neighborhood around the cursor | Density shading (`█▓▒░·`) |
| **Iso** | Scalar field rendered as elevation map via IDW interpolation (power=2) | Height-mapped shading |
| **Temporal** | Time-series evolution of the cursor's neighborhood | Change over time |

The Iso view cycles through four scalar fields (curvature κ, total persistence π, complexity σ, boundary participation β) each revealing different aspects of the local topological structure.

### FileTree (Left Panel)

The left panel presents a Plan 9-inspired file tree where knowledge base entries, agents, and system state are navigated as a directory structure. Agents appear as files under `/agents/`, and KB entries are organized by domain. Toggle visibility with `[`.

### ContentPanel (Right Panel)

The right panel displays detailed content for the currently selected item: file contents, agent output, position context, health reports, or command results. It is the primary output area for slash commands. Toggle visibility with `]`.

### CommandInput (Bottom Bar)

The bottom command bar accepts slash commands. Press `/` to focus it, type a command (e.g., `health`, `evolve status`, `gpu status`), and press Enter. Press Escape to cancel. The command bar supports history navigation with up/down arrows and tab completion.

## Layout Flexibility

Toggle panels to adjust the layout to your task:

- **Full layout**: all panels visible -- maximum context
- **Grid-focused**: press `\` to hide both panels -- maximum grid space
- **Research mode**: hide left panel with `[` -- more room for content output
- **Navigation mode**: hide right panel with `]` -- focus on the file tree and grid

### Center Auxiliary Panel

The center panel cycles through five modes:

| Mode | Content |
|------|---------|
| **Graph** | Wiki-link graph visualization of KB connections |
| **Think** | Reasoning traces and agent thinking during inference |
| **Evolution** | Evolution daemon monitoring (agent improvement cycles) |
| **Observe** | Operational health metrics from Prometheus and engine |
| **None** | Hidden -- maximizes main grid space |

## Density Shading

Scalar values map to block characters for high-bandwidth visual perception:

| Symbol | Value range | Meaning |
|--------|------------|---------|
| `█` | > 0.8 | High intensity |
| `▓` | 0.6 -- 0.8 | Medium-high |
| `▒` | 0.4 -- 0.6 | Medium |
| `░` | 0.2 -- 0.4 | Low |
| `·` | 0.05 -- 0.2 | Minimal |

This vocabulary is consistent across the MainGrid, MiniGrids, and overlays.

## Design Principles

The TUI is keyboard-first. Every action is reachable without a mouse. Information density is high by design -- the interface shows as much relevant data as possible without requiring navigation to separate screens. Modes and overlays let you shift perspective without losing your place.

The visual vocabulary is consistent: the same shading characters mean the same intensities everywhere. Death loops (`⚠`) always indicate persistent H1 features. Agent colors are stable across sessions.
