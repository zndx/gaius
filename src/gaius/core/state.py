"""Application state management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ViewMode(Enum):
    """Primary view modes for the grid."""
    GO = "go"
    PENSION = "pension"
    SWARM = "swarm"


class OverlayMode(Enum):
    """Overlay modes for additional visualization layers.

    NEW DESIGN (differential geometry):
    - TOPOLOGY: H0/H1/H2 persistent homology features
    - GEOMETRY: Curvature heatmap (semantic boundaries)
    - DYNAMICS: Gradient vector field (semantic change direction)
    - AGENTS: Agent positions (unchanged)
    """
    NONE = "none"
    TOPOLOGY = "topology"  # H0/H1/H2 (components, loops, voids)
    GEOMETRY = "geometry"  # Curvature (boundaries vs interiors)
    DYNAMICS = "dynamics"  # Gradient field + divergence
    AGENTS = "agents"


class CenterPanelMode(Enum):
    """Mode for the center auxiliary panel (graph area).

    Cycles: GRAPH → THINK → NONE → GRAPH
    """
    GRAPH = "graph"   # Wiki-link graph visualization
    THINK = "think"   # Reasoning traces and agent thinking
    NONE = "none"     # Hidden (more space for main grid)


@dataclass
class BackgroundTask:
    """A background task with status tracking.

    Used for long-running operations that shouldn't block UI startup.
    """
    id: str             # Unique task identifier
    name: str           # Display name (e.g., "Loading KB embeddings")
    status: str         # "pending", "running", "completed", "failed"
    progress: float = 0.0  # 0-1 progress indicator
    message: str = ""   # Current status message
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class ReasoningTrace:
    """A captured reasoning trace from agent/inference operations.

    Used to populate the ThinkPanel with condensed reasoning history.
    """
    timestamp: datetime
    operation: str      # "search", "synthesis", "inference", "swarm"
    query: str          # What was being processed
    summary: str        # Condensed summary of the reasoning
    tokens: int = 0     # Token count if applicable
    sources: int = 0    # Number of sources consulted
    technique: str = "" # optillm technique used (e.g., "cot_reflection")
    duration_ms: int = 0  # Operation duration
    full_trace: str = ""  # Full reasoning text (may be truncated)


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

    # TDA state (topology)
    h1_cycles: list = field(default_factory=list)  # H1 bounding boxes (1-cycles/loops)
    h2_voids: list = field(default_factory=list)   # H2 bounding boxes (2-voids/cavities)
    risk_map: list = field(default_factory=list)   # 19x19 risk values (0-1) [legacy]
    tda_entropy: float = 0.0

    # Geometry state (curvature, gradients)
    curvature_map: list = field(default_factory=list)  # 19x19 Ricci curvature values (for grid overlay)
    curvatures_raw: list = field(default_factory=list)  # Per-point curvature list (for Iso view)
    gradient_field: list = field(default_factory=list)  # List of (x, y, gx, gy) gradient vectors
    divergence_map: list = field(default_factory=list)  # 19x19 divergence values
    tenuki_visited: set = field(default_factory=set)    # Set of (x, y) positions visited by tenuki

    # Agent positions (list of (name, x, y, color))
    agent_positions: list = field(default_factory=list)

    # Center panel mode (graph/think/none)
    center_panel_mode: CenterPanelMode = CenterPanelMode.GRAPH

    # Think mode state
    active_reasoning: Optional[str] = None  # Current reasoning being displayed
    reasoning_traces: list = field(default_factory=list)  # History of ReasoningTrace
    background_tasks: list = field(default_factory=list)  # BackgroundTask instances

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

    def cycle_center_panel_mode(self) -> CenterPanelMode:
        """Cycle through center panel modes: GRAPH → THINK → NONE → GRAPH."""
        modes = [CenterPanelMode.GRAPH, CenterPanelMode.THINK, CenterPanelMode.NONE]
        idx = modes.index(self.center_panel_mode)
        self.center_panel_mode = modes[(idx + 1) % len(modes)]
        return self.center_panel_mode

    def add_reasoning_trace(self, trace: ReasoningTrace) -> None:
        """Add a reasoning trace to history (max 50 entries)."""
        self.reasoning_traces.append(trace)
        # Keep only last 50 traces
        if len(self.reasoning_traces) > 50:
            self.reasoning_traces = self.reasoning_traces[-50:]

    def set_active_reasoning(self, text: str | None) -> None:
        """Set the current active reasoning text."""
        self.active_reasoning = text

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
