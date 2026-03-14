# First Launch

This page describes what you will see when you first start Gaius, and what to try immediately.

## Starting the TUI

From inside a devenv shell with services running:

```bash
uv run gaius
```

The terminal fills with the Gaius interface. At its center is a 19x19 grid -- the MainGrid -- with a cursor marker at position K10.

## What You See

The default layout has three regions:

- **Left panel** -- a FileTree showing the knowledge base as a directory structure
- **Center** -- the 19x19 MainGrid with three 9x9 MiniGrid projections below it
- **Right panel** -- a ContentPanel that shows context for the current selection

The bottom of the screen has a command bar. The cursor appears as a distinct marker on the grid.

## First Steps

**Move the cursor.** Press `h`, `j`, `k`, `l` to move left, down, up, right. The cursor moves across the grid. The MiniGrid projections and ContentPanel update to reflect the new position.

**Check your bearings.** Press `?` to display help in the ContentPanel. This shows the available key bindings and a summary of the current state.

**Cycle the view.** Press `v` to switch between view modes (Go, Theta, Swarm). Each mode renders the grid data differently.

**Cycle overlays.** Press `o` to layer additional information onto the grid: topology, geometry, dynamics, or agent positions.

**Toggle panels.** Press `[` to toggle the left panel, `]` to toggle the right panel, or `\` to toggle both. Hiding panels maximizes grid space.

**Enter a command.** Press `/` to focus the command bar, then type `health` and press Enter. This runs the health diagnostic and displays system status in the ContentPanel.

## First CLI Check

Open a second terminal (also in devenv shell) and try:

```bash
uv run gaius-cli --cmd "/health" --format json
```

This runs the same health check non-interactively and prints JSON output. The CLI and TUI connect to the same engine, so results are identical.

## If Something Looks Wrong

If the grid is empty or services are not responding:

```bash
just restart-clean
```

This performs a full clean restart of all platform services. After it completes, relaunch with `uv run gaius`.

## Next Steps

- **[The TUI](./tui.md)** -- understand the five components of the interface
- **[Navigation](./navigation.md)** -- learn cursor movement and workflow patterns
- **[Key Bindings](./keybindings.md)** -- complete keyboard reference
