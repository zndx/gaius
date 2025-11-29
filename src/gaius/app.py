"""Gaius TUI Application.

A CLI-first terminal interface for navigating complex, graph-oriented data domains.
Renders high-dimensional embeddings and topological structures onto a constrained grid.

Usage:
    uv run gaius                    # Pure UI mode
    uv run gaius-cli --cmd "/state" # CLI mode
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, Header, Footer

from .core.state import AppState, ViewMode, OverlayMode
from .widgets.grid import MainGrid
from .widgets.minigrid import MiniGrid
from .widgets.filetree import FileTree
from .widgets.content import ContentPanel
from .widgets.command import CommandInput, CommandSubmitted
from .widgets.location import LocationIndicator
from .widgets.note_editor import NoteEditor
from .widgets.graph_view import GraphView
from .widgets.filetree import FileTreeSelection
from .static import (
    GRID_DATA,
    AGENT_DATA,
    DEATH_LOOPS,
    TDA_METRICS,
    get_minigrid_data,
    get_position_hint,
    generate_explanation,
)


class GaiusApp(App):
    """Gaius: Augmented cognition through spatial visualization."""

    TITLE = "Gaius"
    SUB_TITLE = "Spatial Intelligence Interface"

    CSS = """
    /* ═══════════════════════════════════════════════════════════════════
       GAIUS TUI STYLESHEET

       Layout:
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
       │ Command Input                                     │
       └───────────────────────────────────────────────────┘
       ═══════════════════════════════════════════════════════════════════ */

    Screen {
        background: $surface;
    }

    /* ─────────────────────────────────────────────────────────────────────
       STATUS BAR
       ───────────────────────────────────────────────────────────────────── */
    #status-bar {
        dock: top;
        height: 1;
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
    }

    /* ─────────────────────────────────────────────────────────────────────
       MAIN LAYOUT
       ───────────────────────────────────────────────────────────────────── */
    #main-container {
        width: 100%;
        height: 1fr;
    }

    #main-horizontal {
        width: 100%;
        height: 100%;
    }

    /* ─────────────────────────────────────────────────────────────────────
       LEFT PANEL (Files/Agents)
       ───────────────────────────────────────────────────────────────────── */
    #left-panel {
        width: 24;
        height: 100%;
        background: $surface-darken-1;
        border-right: solid $primary-darken-2;
        overflow: hidden;
    }

    #left-panel.hidden {
        display: none;
    }

    #left-panel-header {
        height: 1;
        background: $primary-darken-3;
        padding: 0 1;
        text-style: bold;
    }

    /* ─────────────────────────────────────────────────────────────────────
       CENTER AREA (Grids)
       ───────────────────────────────────────────────────────────────────── */
    #center-area {
        width: 1fr;
        height: 100%;
        padding: 1;
        overflow: hidden;
    }

    /* Grid row: Main grid + right column of mini-grids */
    #grid-row {
        width: auto;
        height: auto;
        overflow: hidden;
    }

    /* Main 19x19 grid wrapper */
    #main-grid-wrapper {
        width: auto;
        height: auto;
        overflow: hidden;
    }

    MainGrid {
        width: 40;
        height: 21;
        overflow: hidden;
    }

    /* Right column with two stacked mini-grids */
    #right-minigrids {
        width: auto;
        height: auto;
        margin-left: 1;
        overflow: hidden;
    }

    #minigrid-top {
        margin-bottom: 1;
    }

    /* Mini-grid styling */
    MiniGrid {
        width: 21;
        height: 11;
        border: round $primary-darken-2;
        background: $surface-darken-1;
        padding: 0 1;
        overflow: hidden;
    }

    /* Graph view (wiki-link visualization) - 19x19 borderless grid */
    #graph-view {
        width: 40;
        height: 21;
        margin-left: 1;
        background: $surface-darken-1;
        overflow: hidden;
    }

    /* Location indicator below main grid */
    #location-indicator {
        width: 100%;
        height: 1;
        margin-top: 0;
        background: $primary-darken-3;
        color: $text;
    }

    /* Note editor below location indicator */
    #note-editor {
        width: 100%;
        height: 1fr;
        min-height: 5;
        margin-top: 1;
        border: solid $primary-darken-2;
        background: $surface;
    }

    #note-editor TextArea {
        width: 100%;
        height: 100%;
        background: $surface;
    }

    #note-editor.hidden {
        display: none;
    }

    /* ─────────────────────────────────────────────────────────────────────
       RIGHT PANEL (Content)
       ───────────────────────────────────────────────────────────────────── */
    #right-panel {
        width: 32;
        height: 100%;
        background: $surface-darken-1;
        border-left: solid $primary-darken-2;
        overflow: hidden;
    }

    #right-panel.hidden {
        display: none;
    }

    ContentPanel {
        width: 100%;
        height: 100%;
        overflow: hidden auto;
    }

    /* ─────────────────────────────────────────────────────────────────────
       COMMAND INPUT (Bottom)
       ───────────────────────────────────────────────────────────────────── */
    CommandInput {
        dock: bottom;
        height: 3;
        background: $surface-darken-2;
        border-top: solid $primary-darken-2;
        padding: 0 1;
    }

    CommandInput Input {
        background: transparent;
        border: none;
    }

    CommandInput Input:focus {
        border: none;
    }
    """

    BINDINGS = [
        # Navigation
        Binding("h", "move(-1, 0)", "Left", show=False),
        Binding("j", "move(0, 1)", "Down", show=False),
        Binding("k", "move(0, -1)", "Up", show=False),
        Binding("l", "move(1, 0)", "Right", show=False),

        # View controls
        Binding("v", "cycle_view", "View"),
        Binding("o", "cycle_overlay", "Overlay"),
        Binding("c", "toggle_candidates", "Candidates"),

        # Panel controls
        Binding("bracketleft", "toggle_left", "Files", show=False),  # [
        Binding("bracketright", "toggle_right", "Content", show=False),  # ]
        Binding("backslash", "toggle_both", "Panels"),  # \

        # Commands
        Binding("slash", "command_mode", "Command"),
        Binding("question_mark", "show_help", "Help"),

        # Tenuki (play elsewhere - jump to strategic point)
        Binding("t", "tenuki", "Tenuki"),

        # Notes
        Binding("ctrl+n", "new_note", "New Note"),

        # Graph view (wiki-links)
        Binding("g", "toggle_graph", "Graph"),

        # Quit hint (actual quit via /q or /exit command)
        Binding("q", "quit_hint", "Quit", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self._load_test_data()

    def _load_test_data(self) -> None:
        """Initialize with static test data."""
        self.state.black_stones = GRID_DATA["black"]
        self.state.white_stones = GRID_DATA["white"]
        self.state.allocations = GRID_DATA["alloc"]
        self.state.death_loops = DEATH_LOOPS
        self.state.tda_entropy = TDA_METRICS["entropy"]

        # Load agent positions
        for agent in AGENT_DATA:
            self.state.agent_positions.append((
                agent["name"],
                agent["pos"][0],
                agent["pos"][1],
                agent["color"],
            ))

        # Set some candidates
        self.state.candidates = [(3, 3), (15, 15), (10, 10), (5, 14), (14, 5)]

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()

        # Status bar
        yield Static(self._status_text(), id="status-bar")

        # Main container with panels
        with Container(id="main-container"):
            with Horizontal(id="main-horizontal"):
                # Left panel (files/agents)
                with Vertical(id="left-panel"):
                    yield Static("Navigator", id="left-panel-header")
                    yield FileTree(
                        self.state,
                        agents=AGENT_DATA,
                        kb_root="build/dev",
                        id="file-tree",
                    )

                # Center area (main grid + mini-grids in CAD layout)
                with Vertical(id="center-area"):
                    # Grid row: 19x19 main grid + right column of mini-grids
                    with Horizontal(id="grid-row"):
                        # Main 19x19 grid with location indicator below
                        with Vertical(id="main-grid-wrapper"):
                            yield MainGrid(self.state, id="main-grid")
                            yield LocationIndicator(
                                self.state.cursor_x,
                                self.state.cursor_y,
                                id="location-indicator"
                            )

                        # Right column: two stacked 9x9 mini-grids
                        with Vertical(id="right-minigrids"):
                            yield MiniGrid("Embed", id="minigrid-top", classes="right")
                            yield MiniGrid("Iso", id="minigrid-bottom", classes="bottom-right")

                        # Graph view (wiki-links) - hidden by default, 'g' to show
                        yield GraphView(kb_root="build/dev", id="graph-view", classes="hidden")

                    # Note editor below the grids (hidden by default, Ctrl-N to show)
                    yield NoteEditor(id="note-editor", classes="hidden")

                # Right panel (content)
                with Vertical(id="right-panel"):
                    yield ContentPanel(self.state, id="content-panel")

        # Command input
        yield CommandInput(self.state, id="command-input")

        yield Footer()

    def _status_text(self) -> str:
        """Generate status bar text."""
        mode = self.state.view_mode.value.upper()
        overlay = self.state.overlay_mode.value
        coord = self.state.cursor_coord
        domain = self.state.domain[:20] + "..." if len(self.state.domain) > 23 else self.state.domain

        return (
            f"[bold green]{mode}[/] │ "
            f"[yellow]{overlay}[/] │ "
            f"[bold cyan]{coord}[/] │ "
            f"{domain} │ "
            f"[dim]hjkl:move o:overlay v:view /:cmd[/]"
        )

    def _update_status(self) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(self._status_text())

    def _refresh_grid(self) -> None:
        """Refresh the main grid."""
        grid = self.query_one("#main-grid", MainGrid)
        grid.update_state(self.state)

    def _update_minigrids(self) -> None:
        """Update mini-grids based on cursor position."""
        data = get_minigrid_data(self.state.cursor_x, self.state.cursor_y)

        # Update each mini-grid (right column: top and bottom)
        if "right" in data:
            self.query_one("#minigrid-top", MiniGrid).update_data(data["right"])
        if "top" in data:
            self.query_one("#minigrid-bottom", MiniGrid).update_data(data["top"])

    def _update_location(self) -> None:
        """Update the location indicator with current cursor position."""
        indicator = self.query_one("#location-indicator", LocationIndicator)
        indicator.update_position(self.state.cursor_x, self.state.cursor_y)

    def _update_explanation(self) -> None:
        """Update the content panel with contextual explanation."""
        explanation = generate_explanation(
            self.state.view_mode,
            self.state.overlay_mode,
            self.state.cursor_x,
            self.state.cursor_y,
        )
        content = self.query_one("#content-panel", ContentPanel)
        content.show_file("context.md", explanation)

    # ─────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────

    def action_move(self, dx: int, dy: int) -> None:
        """Move cursor by delta."""
        if self.state.move_cursor(dx, dy):
            self._refresh_grid()
            self._update_status()
            self._update_minigrids()
            self._update_location()
            self._update_explanation()

    def action_cycle_view(self) -> None:
        """Cycle through view modes."""
        self.state.cycle_view_mode()
        self._refresh_grid()
        self._update_status()
        self._update_explanation()

    def action_cycle_overlay(self) -> None:
        """Cycle through overlay modes."""
        self.state.cycle_overlay_mode()
        self._refresh_grid()
        self._update_status()
        self._update_explanation()

    def action_toggle_candidates(self) -> None:
        """Toggle candidate markers."""
        self.state.toggle_candidates()
        self._refresh_grid()

    def action_toggle_left(self) -> None:
        """Toggle left panel visibility."""
        panel = self.query_one("#left-panel")
        panel.toggle_class("hidden")

    def action_toggle_right(self) -> None:
        """Toggle right panel visibility."""
        panel = self.query_one("#right-panel")
        panel.toggle_class("hidden")

    def action_toggle_both(self) -> None:
        """Toggle both panels."""
        self.action_toggle_left()
        self.action_toggle_right()

    def action_command_mode(self) -> None:
        """Enter command mode."""
        cmd_input = self.query_one("#command-input", CommandInput)
        cmd_input.enter_command_mode("/")

    def action_show_help(self) -> None:
        """Show help in content panel."""
        content = self.query_one("#content-panel", ContentPanel)
        help_text = """# Gaius Help

## Navigation
- **hjkl**: Move cursor (vim-style)
- **t**: Tenuki (jump to strategic point)

## Views
- **v**: Cycle view modes (Go/Pension/Swarm)
- **o**: Cycle overlays (none/risk/h1/h2/agents/temporal)
- **c**: Toggle candidate markers

## Panels
- **[**: Toggle left panel (files/agents)
- **]**: Toggle right panel (content)
- **\\\\**: Toggle both panels

## Notes (Zettelkasten)
- **Ctrl-N**: Create new scratch note
- Vim-style editing (i/I/A/o/O to insert, ESC for normal)
- **:q** or **:wq**: Close editor
- Auto-saves on every edit
- Notes: build/dev/scratch/{date}/{timestamp}.md
- Wiki-links: [[path/to/note]]

## Graph View
- **g**: Toggle wiki-link graph
- Shows backlinks (what links here)
- Shows forward links (what this links to)

## Commands
- **/**: Enter command mode
- **?**: Show this help

## Common Commands
- `/domain <name>`: Set analysis domain
- `/info`: Show cursor position info
- `/analyze`: Run analysis at cursor
- `/round`: Execute swarm round
- `/q` or `/exit`: Quit Gaius
"""
        content.show_file("help.md", help_text)

    def action_tenuki(self) -> None:
        """Jump to point of highest strategic interest (tenuki).

        In Go, tenuki means 'playing elsewhere' - ignoring the local
        situation for a bigger play. Here we jump to the most interesting
        point based on current analysis.
        """
        # For now, cycle through agent positions
        if self.state.agent_positions:
            # Find the agent we're not currently near
            current = (self.state.cursor_x, self.state.cursor_y)
            best_dist = 0
            best_pos = current

            for name, x, y, color in self.state.agent_positions:
                dist = abs(x - current[0]) + abs(y - current[1])
                if dist > best_dist:
                    best_dist = dist
                    best_pos = (x, y)

            if best_pos != current:
                self.state.cursor_x, self.state.cursor_y = best_pos
                self._refresh_grid()
                self._update_status()
                self._update_minigrids()
                self._update_location()

    def action_new_note(self) -> None:
        """Create a new Zettelkasten note and focus the editor."""
        editor = self.query_one("#note-editor", NoteEditor)

        # Show the editor if hidden
        editor.remove_class("hidden")

        # Create new note with timestamp filename
        filepath = editor.new_note()

        # Refresh the file tree to show new note
        file_tree = self.query_one("#file-tree", FileTree)
        file_tree.refresh_tree()

        # Update graph if visible
        graph = self.query_one("#graph-view", GraphView)
        if not graph.has_class("hidden"):
            graph.update_for_file(filepath)

        # Update status to show we're editing
        self._update_status()

        # Show confirmation in content panel
        content = self.query_one("#content-panel", ContentPanel)
        content.show_file("note.txt", f"New note: {filepath}\n\nVim keys: i=insert, ESC=normal, :q=close")

    def action_toggle_graph(self) -> None:
        """Toggle graph view visibility."""
        graph = self.query_one("#graph-view", GraphView)
        graph.toggle()

        # If showing, scan KB and update for current note
        if not graph.has_class("hidden"):
            graph.scan_kb()
            editor = self.query_one("#note-editor", NoteEditor)
            if editor.current_file:
                graph.update_for_file(editor.current_file)

    def action_quit_hint(self) -> None:
        """Show quit hint instead of immediately quitting."""
        content = self.query_one("#content-panel", ContentPanel)
        content.show_file("quit.txt", "Use /q or /exit to quit Gaius.")

    # ─────────────────────────────────────────────────────────────────────
    # Event Handlers
    # ─────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Initialize on mount."""
        self._refresh_grid()
        self._update_minigrids()
        self._update_explanation()

    def on_command_submitted(self, event: CommandSubmitted) -> None:
        """Handle command submission."""
        cmd = event.command.strip()
        self._execute_command(cmd)

    def on_file_tree_selection(self, event: FileTreeSelection) -> None:
        """Handle file/agent selection from the tree."""
        data = event.data
        content = self.query_one("#content-panel", ContentPanel)
        editor = self.query_one("#note-editor", NoteEditor)
        graph = self.query_one("#graph-view", GraphView)

        if data["type"] == "file":
            filepath = data["path"]
            # Update graph view if visible
            if not graph.has_class("hidden"):
                graph.update_for_file(filepath)

            # Check if it's a scratch note (editable) or other file (view only)
            if "/scratch/" in filepath and filepath.endswith(".md"):
                # Open in editor
                editor.remove_class("hidden")
                editor.open_note(filepath)
            else:
                # Show in content panel (read-only)
                try:
                    from pathlib import Path
                    text = Path(filepath).read_text()
                    content.show_file(Path(filepath).name, text)
                except Exception as e:
                    content.show_file("error.txt", f"Cannot read file: {e}")

        elif data["type"] == "agent":
            # Show agent status in content panel
            agent_info = f"""# Agent: {data['name']}

**Role:** {data.get('role', 'Unknown')}
**Status:** Active

## Last Output
{data.get('last', 'No recent output.')}

---
*Select agent file to interact*
"""
            content.show_file(f"{data['name'].lower()}.md", agent_info)

    def _execute_command(self, cmd: str) -> None:
        """Execute a slash command."""
        content = self.query_one("#content-panel", ContentPanel)

        if cmd.startswith("/"):
            cmd = cmd[1:]

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        if command == "help":
            self.action_show_help()
        elif command == "info":
            hint = get_position_hint(self.state.cursor_x, self.state.cursor_y)
            content.show_position_info(self.state.cursor_x, self.state.cursor_y, hint)
        elif command == "domain":
            if args:
                self.state.domain = args
                self._update_status()
                content.show_file("domain.txt", f"Domain set to: {args}")
        elif command == "overlay":
            if args:
                try:
                    self.state.overlay_mode = OverlayMode(args.lower())
                    self._refresh_grid()
                    self._update_status()
                except ValueError:
                    content.show_file("error.txt", f"Unknown overlay: {args}")
            else:
                self.action_cycle_overlay()
        elif command == "view":
            if args:
                try:
                    self.state.view_mode = ViewMode(args.lower())
                    self._refresh_grid()
                    self._update_status()
                except ValueError:
                    content.show_file("error.txt", f"Unknown view: {args}")
            else:
                self.action_cycle_view()
        elif command in ("quit", "q", "exit"):
            self.exit()
        else:
            content.show_file("error.txt", f"Unknown command: {command}\n\nType /help for available commands.")


def main():
    """Entry point for the Gaius TUI."""
    app = GaiusApp()
    app.run()


if __name__ == "__main__":
    main()
