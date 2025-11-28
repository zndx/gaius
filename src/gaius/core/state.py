"""Application state management."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ViewMode(Enum):
    """Primary view modes for the grid."""
    GO = "go"
    PENSION = "pension"
    SWARM = "swarm"


class OverlayMode(Enum):
    """Overlay modes for additional visualization layers."""
    NONE = "none"
    RISK = "risk"
    H1 = "h1"      # Death loops
    H2 = "h2"      # Voids
    AGENTS = "agents"
    TEMPORAL = "temporal"


@dataclass
class AppState:
    """Centralized application state."""

    # Cursor position
    cursor_x: int = 9
    cursor_y: int = 9

    # View state
    view_mode: ViewMode = ViewMode.PENSION
    overlay_mode: OverlayMode = OverlayMode.NONE

    # Panel visibility
    left_panel_visible: bool = True
    right_panel_visible: bool = True

    # Grid data
    black_stones: set = field(default_factory=set)
    white_stones: set = field(default_factory=set)
    allocations: list = field(default_factory=list)

    # Candidate positions
    candidates: list = field(default_factory=list)
    show_candidates: bool = False

    # Domain
    domain: str = "pension asset allocation"

    # Selected items
    selected_file: Optional[str] = None
    selected_agent: Optional[str] = None

    # Command history
    command_history: list = field(default_factory=list)
    command_index: int = -1

    # TDA state
    death_loops: list = field(default_factory=list)
    tda_entropy: float = 0.0

    # Agent positions (list of (name, x, y, color))
    agent_positions: list = field(default_factory=list)

    def move_cursor(self, dx: int, dy: int) -> bool:
        """Move cursor by delta, return True if moved."""
        new_x = max(0, min(18, self.cursor_x + dx))
        new_y = max(0, min(18, self.cursor_y + dy))
        if new_x != self.cursor_x or new_y != self.cursor_y:
            self.cursor_x = new_x
            self.cursor_y = new_y
            return True
        return False

    def cycle_view_mode(self) -> ViewMode:
        """Cycle through view modes."""
        modes = list(ViewMode)
        idx = modes.index(self.view_mode)
        self.view_mode = modes[(idx + 1) % len(modes)]
        return self.view_mode

    def cycle_overlay_mode(self) -> OverlayMode:
        """Cycle through overlay modes."""
        modes = list(OverlayMode)
        idx = modes.index(self.overlay_mode)
        self.overlay_mode = modes[(idx + 1) % len(modes)]
        return self.overlay_mode

    def toggle_left_panel(self) -> bool:
        """Toggle left panel visibility."""
        self.left_panel_visible = not self.left_panel_visible
        return self.left_panel_visible

    def toggle_right_panel(self) -> bool:
        """Toggle right panel visibility."""
        self.right_panel_visible = not self.right_panel_visible
        return self.right_panel_visible

    def toggle_candidates(self) -> bool:
        """Toggle candidate display."""
        self.show_candidates = not self.show_candidates
        return self.show_candidates

    def add_command(self, cmd: str) -> None:
        """Add command to history."""
        if cmd and (not self.command_history or self.command_history[-1] != cmd):
            self.command_history.append(cmd)
        self.command_index = len(self.command_history)

    def prev_command(self) -> Optional[str]:
        """Get previous command from history."""
        if self.command_history and self.command_index > 0:
            self.command_index -= 1
            return self.command_history[self.command_index]
        return None

    def next_command(self) -> Optional[str]:
        """Get next command from history."""
        if self.command_index < len(self.command_history) - 1:
            self.command_index += 1
            return self.command_history[self.command_index]
        self.command_index = len(self.command_history)
        return ""

    @property
    def cursor(self) -> tuple[int, int]:
        """Get cursor as tuple."""
        return (self.cursor_x, self.cursor_y)

    @property
    def cursor_coord(self) -> str:
        """Get cursor as Go coordinate string (e.g., 'K10')."""
        col = chr(65 + self.cursor_x + (1 if self.cursor_x >= 8 else 0))  # Skip 'I'
        row = 19 - self.cursor_y
        return f"{col}{row}"
