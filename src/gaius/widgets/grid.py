"""Main 19x19 grid widget."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text

from ..core.state import AppState, ViewMode, OverlayMode


class MainGrid(Widget):
    """The primary 19x19 Go board grid.

    Not focusable - navigation via hjkl keys works globally.
    """

    DEFAULT_CSS = """
    MainGrid {
        width: 100%;
        height: 100%;
        min-width: 40;
        min-height: 21;
    }
    """

    # Reactive state reference
    cursor_x: reactive[int] = reactive(9)
    cursor_y: reactive[int] = reactive(9)

    def __init__(
        self,
        state: AppState,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state

    def render(self) -> Text:
        """Render the 19x19 grid."""
        text = Text()
        grid = self._build_grid()

        for y in range(19):
            # Row number (right-aligned, 2 chars)
            row_num = 19 - y
            text.append(f"{row_num:2} ", style="dim")

            # Grid cells
            for x in range(19):
                cell, style = grid[y][x]
                text.append(cell, style=style)
                if x < 18:
                    text.append(" ")

            text.append("\n")

        # Column labels
        text.append("   ", style="dim")
        for i in range(19):
            col = chr(65 + i + (1 if i >= 8 else 0))  # Skip 'I'
            text.append(col, style="dim")
            if i < 18:
                text.append(" ", style="dim")

        return text

    def _build_grid(self) -> list[list[tuple[str, str]]]:
        """Build the grid as a 2D array of (char, style) tuples."""
        # Initialize with empty intersections
        grid = [[("·", "dim")] * 19 for _ in range(19)]

        # Star points (hoshi)
        star_points = [
            (3, 3), (3, 9), (3, 15),
            (9, 3), (9, 9), (9, 15),
            (15, 3), (15, 9), (15, 15),
        ]
        for x, y in star_points:
            grid[y][x] = ("+", "dim")

        # View mode content
        if self.state.view_mode == ViewMode.GO:
            self._render_go_mode(grid)
        elif self.state.view_mode == ViewMode.PENSION:
            self._render_pension_mode(grid)
        elif self.state.view_mode == ViewMode.SWARM:
            self._render_swarm_mode(grid)

        # Overlays
        if self.state.overlay_mode == OverlayMode.H1:
            self._render_death_loops(grid)
        elif self.state.overlay_mode == OverlayMode.AGENTS:
            self._render_agents(grid)

        # Candidates (if visible)
        if self.state.show_candidates:
            self._render_candidates(grid)

        # Cursor (always on top)
        cx, cy = self.state.cursor_x, self.state.cursor_y
        grid[cy][cx] = ("✛", "bold yellow")

        return grid

    def _render_go_mode(self, grid: list) -> None:
        """Render Go stones."""
        for x, y in self.state.black_stones:
            if 0 <= x < 19 and 0 <= y < 19:
                grid[y][x] = ("●", "white")
        for x, y in self.state.white_stones:
            if 0 <= x < 19 and 0 <= y < 19:
                grid[y][x] = ("○", "white")

    def _render_pension_mode(self, grid: list) -> None:
        """Render pension allocation density."""
        if not self.state.allocations:
            return
        for y in range(19):
            for x in range(19):
                if y < len(self.state.allocations) and x < len(self.state.allocations[y]):
                    v = self.state.allocations[y][x]
                    if v > 75:
                        grid[y][x] = ("▓", "green")
                    elif v > 50:
                        grid[y][x] = ("▒", "yellow")
                    elif v > 25:
                        grid[y][x] = ("░", "blue")
                    # else keep as empty

    def _render_swarm_mode(self, grid: list) -> None:
        """Render swarm agent positions prominently."""
        for name, x, y, color in self.state.agent_positions:
            if 0 <= x < 19 and 0 <= y < 19:
                grid[y][x] = ("●", f"bold {color}")

    def _render_death_loops(self, grid: list) -> None:
        """Render H1 death loop indicators."""
        for x1, y1, x2, y2 in self.state.death_loops:
            for y in range(y1, y2 + 1):
                for x in range(x1, x2 + 1):
                    if 0 <= x < 19 and 0 <= y < 19:
                        # Only mark edges of the bounding box
                        if x == x1 or x == x2 or y == y1 or y == y2:
                            grid[y][x] = ("⚠", "bold red on dark_red")

    def _render_agents(self, grid: list) -> None:
        """Render agent positions as overlay."""
        for name, x, y, color in self.state.agent_positions:
            if 0 <= x < 19 and 0 <= y < 19:
                grid[y][x] = ("◆", color)

    def _render_candidates(self, grid: list) -> None:
        """Render candidate move markers."""
        for i, (x, y) in enumerate(self.state.candidates[:9]):
            if 0 <= x < 19 and 0 <= y < 19:
                letter = chr(97 + i)  # a-i
                grid[y][x] = (letter, "bold yellow")

    def update_state(self, state: AppState) -> None:
        """Update the state reference and refresh."""
        self.state = state
        self.refresh()
