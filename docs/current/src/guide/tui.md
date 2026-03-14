# The TUI

Gaius renders a full terminal interface built on the Textual framework. The interface draws inspiration from Bloomberg Terminal (information density), Plan 9's Acme (everything is a file), and CAD orthographic views (multiple synchronized projections).

Launch the TUI with:

```bash
uv run gaius
```

## Five Components

The interface is composed of five primary widgets:

### MainGrid

The 19x19 grid occupies the center of the screen. It is the primary workspace -- a spatial representation of high-dimensional data projected onto a Go board layout. Grid positions correspond to embedded data points, and the cursor indicates your current focus.

The grid supports three **view modes** (cycled with `v`): Go, Theta, and Swarm. Each mode changes how the underlying data is rendered. Four **overlay modes** (cycled with `o`) layer additional information on top: topology, geometry, dynamics, and agent positions.

### MiniGridPanel

Below the MainGrid sit three 9x9 orthographic projections. These are CAD-style views that show the data from different angles -- like top, front, and side views of a 3D object. They update automatically as you move the cursor, providing spatial context around your current position.

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

## Design Principles

The TUI is keyboard-first. Every action is reachable without a mouse. Information density is high by design -- the interface shows as much relevant data as possible without requiring navigation to separate screens. Modes and overlays let you shift perspective without losing your place.
