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
        elif self.state.view_mode == ViewMode.THETA:
            self._render_theta_mode(grid)
        elif self.state.view_mode == ViewMode.SWARM:
            self._render_swarm_mode(grid)

        # Overlays (new 4-category system)
        if self.state.overlay_mode == OverlayMode.TOPOLOGY:
            self._render_topology(grid)
        elif self.state.overlay_mode == OverlayMode.GEOMETRY:
            self._render_geometry(grid)
        elif self.state.overlay_mode == OverlayMode.DYNAMICS:
            self._render_dynamics(grid)
        elif self.state.overlay_mode == OverlayMode.AGENTS:
            self._render_agents(grid)

        # Tenuki annotations sit on the curvature field (visited + last jump)
        self._render_tenuki(grid)

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

    def _render_theta_mode(self, grid: list) -> None:
        """Render information density (theta view) with attention targets.

        Theta waves (4-8 Hz) facilitate memory consolidation - the transfer
        of information from short-term to long-term storage. This view shows
        information density as a heatmap, revealing regions of high vs low
        knowledge accumulation.

        When ThetaAgent provides attention targets (from AttentionSchema),
        they are overlaid on the density map:
        - Focus target: bright_yellow marker
        - High salience periphery: cyan markers
        - Low salience periphery: dim markers
        """
        # Render density heatmap
        if self.state.allocations:
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

        # Overlay ThetaAgent attention targets (AST schema visualization)
        if self.state.theta_targets:
            for target_id, x, y, color in self.state.theta_targets:
                if 0 <= x < 19 and 0 <= y < 19:
                    # Use different markers based on color (salience level)
                    if color == "bright_yellow":
                        grid[y][x] = ("◉", f"bold {color}")  # Focus target
                    elif color == "cyan":
                        grid[y][x] = ("◎", color)  # High salience
                    else:
                        grid[y][x] = ("○", color)  # Low salience

    def _render_swarm_mode(self, grid: list) -> None:
        """Render swarm agent positions with exploration traces.

        Traces show the agent's recent exploration trajectory:
        - Current position: solid circle (●)
        - t-1 position: medium dot (◉)
        - t-2 position: small dot (○)
        - t-3 position: dim dot (·)

        This visualizes NVAR-style time-delay dynamics, showing where
        each agent has been exploring in semantic space.
        """
        # First, render traces (so current positions render on top)
        if self.state.agent_traces:
            self._render_traces(grid)

        # Then render current agent positions
        for name, x, y, color in self.state.agent_positions:
            if 0 <= x < 19 and 0 <= y < 19:
                grid[y][x] = ("●", f"bold {color}")

    def _render_traces(self, grid: list) -> None:
        """Render agent exploration traces.

        Each trace shows recent positions with fading intensity:
        - Position 0 (current): rendered by _render_swarm_mode
        - Position 1 (t-1): medium marker
        - Position 2 (t-2): small marker
        - Position 3+ (older): dim marker

        Traces are colored to match their agent's color.
        """
        # Build agent color lookup from current positions
        agent_colors: dict[str, str] = {}
        for name, x, y, color in self.state.agent_positions:
            agent_colors[name] = color

        # Unicode markers for trace points (newest to oldest)
        trace_markers = ["◉", "○", "·"]  # t-1, t-2, t-3+

        for agent_name, positions in self.state.agent_traces.items():
            # Skip first position (rendered as current by _render_swarm_mode)
            trace_positions = positions[1:] if len(positions) > 1 else []

            # Get agent color (default to white if not found)
            color = agent_colors.get(agent_name, "white")

            for i, (x, y) in enumerate(trace_positions):
                if 0 <= x < 19 and 0 <= y < 19:
                    # Don't overwrite current agent positions
                    current_char, current_style = grid[y][x]
                    if current_char == "●":
                        continue  # Don't overwrite current positions

                    # Select marker based on age
                    marker_idx = min(i, len(trace_markers) - 1)
                    marker = trace_markers[marker_idx]

                    # Fade style based on age
                    if i == 0:
                        style = color  # t-1: normal color
                    elif i == 1:
                        style = f"dim {color}"  # t-2: dimmed
                    else:
                        style = "dim"  # t-3+: very dim

                    grid[y][x] = (marker, style)

    def _render_topology(self, grid: list) -> None:
        """Render TOPOLOGY overlay: H0/H1/H2 persistent homology features.

        Shows H1 cycles (loops) and H2 voids (cavities) as bounding boxes.
        """
        # H1 cycles (1-cycles/loops) - red edges
        for x1, y1, x2, y2 in self.state.h1_cycles:
            for y in range(y1, y2 + 1):
                for x in range(x1, x2 + 1):
                    if 0 <= x < 19 and 0 <= y < 19:
                        # Only mark edges of the bounding box
                        if x == x1 or x == x2 or y == y1 or y == y2:
                            grid[y][x] = ("!", "bold red on dark_red")

        # H2 voids (2-voids/cavities) - magenta diamonds
        for x1, y1, x2, y2 in self.state.h2_voids:
            for y in range(y1, y2 + 1):
                for x in range(x1, x2 + 1):
                    if 0 <= x < 19 and 0 <= y < 19:
                        # Only mark edges of the bounding box
                        if x == x1 or x == x2 or y == y1 or y == y2:
                            grid[y][x] = ("◇", "bold magenta on dark_magenta")

    def _render_geometry(self, grid: list) -> None:
        """Render GEOMETRY overlay: Ricci curvature heatmap.

        Curvature reveals semantic boundaries (turbulence/complexity):
        - Negative curvature (red) = boundaries, bridge points
        - Positive curvature (blue) = cluster interiors
        - Flat (white) = uniform regions
        """
        if not self.state.curvature_map:
            return

        for y in range(19):
            for x in range(19):
                if y < len(self.state.curvature_map) and x < len(self.state.curvature_map[y]):
                    κ = self.state.curvature_map[y][x]

                    # Map curvature to visualization
                    # Negative κ = boundaries (high complexity, like turbulent diatoms)
                    # Positive κ = interiors (low complexity, like calm water)
                    if κ < -0.3:
                        grid[y][x] = ("█", "bold red")      # Strong boundary
                    elif κ < -0.1:
                        grid[y][x] = ("▓", "red")           # Weak boundary
                    elif κ < 0:
                        grid[y][x] = ("▒", "yellow")        # Slight boundary
                    elif κ > 0.3:
                        grid[y][x] = ("█", "bold blue")     # Strong interior
                    elif κ > 0.1:
                        grid[y][x] = ("▓", "blue")          # Weak interior
                    elif κ > 0:
                        grid[y][x] = ("▒", "cyan")          # Slight interior
                    # else κ ≈ 0: keep as-is (flat geometry)

    def _render_dynamics(self, grid: list) -> None:
        """Render DYNAMICS overlay: gradient vector field + divergence.

        Shows direction of semantic change (gradient arrows) and
        sources/sinks (divergence intensity).
        """
        if not self.state.gradient_field:
            return

        # Unicode arrows for 8 directions
        arrows = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"]

        for entry in self.state.gradient_field:
            if len(entry) != 4:
                continue
            x, y, gx, gy = entry

            if not (0 <= x < 19 and 0 <= y < 19):
                continue

            # Compute gradient direction and magnitude
            import math
            magnitude = math.sqrt(gx**2 + gy**2)

            if magnitude < 0.01:
                # Nearly zero gradient = stable point
                grid[y][x] = ("·", "dim white")
                continue

            # Map angle to arrow direction
            angle = math.atan2(gy, gx)
            arrow_idx = int((angle + math.pi) / (2 * math.pi / 8)) % 8
            arrow = arrows[arrow_idx]

            # Color by magnitude (green = moderate, bright green = strong)
            if magnitude > 0.5:
                grid[y][x] = (arrow, "bright_green")
            elif magnitude > 0.2:
                grid[y][x] = (arrow, "green")
            else:
                grid[y][x] = (arrow, "dark_green")

    def _render_agents(self, grid: list) -> None:
        """Render agent positions as overlay."""
        for name, x, y, color in self.state.agent_positions:
            if 0 <= x < 19 and 0 <= y < 19:
                grid[y][x] = ("◆", color)

    def _render_tenuki(self, grid: list) -> None:
        """Annotate tenuki: visited cells and the last strategic jump.

        These marks live on the same board as the Ricci heatmap so a
        tenuki is readable as a move *on* the curvature field.
        """
        target = self.state.tenuki_target
        for x, y in self.state.tenuki_visited:
            if not (0 <= x < 19 and 0 <= y < 19):
                continue
            if target is not None and (x, y) == target:
                continue
            ch, _style = grid[y][x]
            if ch in (".", "·", "+", " "):
                grid[y][x] = ("∘", "dim magenta")

        if target is not None:
            tx, ty = target
            if 0 <= tx < 19 and 0 <= ty < 19:
                grid[ty][tx] = ("☆", "bold magenta")

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
