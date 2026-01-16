"""Graph view widget for visualizing wiki-link and action link relationships.

Uses a force-directed spring placement algorithm on a 19×19 borderless grid.
"""

from pathlib import Path
import math
import random

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from textual import events
from rich.text import Text

from ..core.links import parse_wikilinks, parse_action_links, LinkGraph


class GraphView(Widget, can_focus=True):
    """Displays wiki-links and action links as a force-directed graph on a 19×19 grid.

    The current note is placed at center (9,9). Connected nodes are
    positioned using spring-based force-directed placement:
    - Edges act as springs (attractive force)
    - All nodes repel each other (repulsive force)
    - Iterate until stable layout

    Node types:
    - Current file (yellow ◉)
    - Forward wiki-links (green ○)
    - Backlinks (cyan ●)
    - Action links (magenta ◇) - slash command links

    Navigation:
    - Arrow keys: Move between nodes
    - Enter: Open selected node's file or execute action
    """

    class NodeSelected(Message):
        """Emitted when Enter is pressed on a node."""
        def __init__(self, filepath: str) -> None:
            self.filepath = filepath
            super().__init__()

    class ActionSelected(Message):
        """Emitted when Enter is pressed on an action link node."""
        def __init__(self, command: str) -> None:
            self.command = command
            super().__init__()

    class NodeHighlighted(Message):
        """Emitted when cursor moves to a new node."""
        def __init__(
            self,
            node_type: str,
            filepath: str | None = None,
            command: str | None = None,
        ) -> None:
            self.node_type = node_type
            self.filepath = filepath
            self.command = command
            super().__init__()

    DEFAULT_CSS = """
    GraphView {
        width: 40;
        height: 21;
        padding: 0;
        overflow: hidden;
    }

    GraphView.hidden {
        display: none;
    }
    """

    GRID_SIZE = 19
    CENTER = 9
    ITERATIONS = 50
    SPRING_K = 0.3      # Spring constant (attraction)
    REPULSION_K = 2.0   # Repulsion constant
    DAMPING = 0.85      # Velocity damping
    MIN_DIST = 1.5      # Minimum distance between nodes

    # Maximum nodes to display (excluding current)
    MAX_FORWARD = 12
    MAX_BACK = 12
    MAX_ACTIONS = 8  # Action links shown on right side

    current_file: reactive[str | None] = reactive(None)
    selected_node: reactive[str | None] = reactive(None)  # Currently selected node ID

    def __init__(
        self,
        kb_root: str = "build/dev",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.kb_root = Path(kb_root)
        self._graph = LinkGraph()
        # Node positions: {node_id: (x, y)}
        self._positions: dict[str, tuple[float, float]] = {}
        # Edges: [(from_id, to_id), ...]
        self._edges: list[tuple[str, str]] = []
        # Node metadata
        self._graph_nodes: dict[str, dict] = {}  # {id: {name, type, ...}}
        self._current_id: str | None = None
        # Overflow counts
        self._total_forward: int = 0
        self._total_back: int = 0
        self._total_actions: int = 0

    def update_for_file(self, filepath: str | None) -> None:
        """Update the graph view for a given file."""
        self.current_file = filepath
        self._build_local_graph(filepath)
        self._run_layout()
        self.refresh()

    def _build_local_graph(self, filepath: str | None) -> None:
        """Build a local subgraph centered on the given file."""
        self._graph_nodes.clear()
        self._edges.clear()
        self._positions.clear()
        self._current_id = None
        self._total_forward = 0
        self._total_back = 0
        self._total_actions = 0

        if not filepath:
            return

        path = Path(filepath)
        if not path.exists():
            return

        # Current node at center
        self._current_id = "current"
        self._graph_nodes["current"] = {
            "name": self._display_name(filepath),
            "type": "current",
            "path": filepath,
        }
        self._positions["current"] = (float(self.CENTER), float(self.CENTER))

        # Parse forward links and action links from current file
        try:
            content = path.read_text()
            forward_links = parse_wikilinks(content)
            action_links = parse_action_links(content)
        except Exception:
            forward_links = []
            action_links = []

        self._total_forward = len(forward_links)
        displayed_forward = forward_links[:self.MAX_FORWARD]

        # Add forward link nodes - spread in lower half (below center)
        for i, link in enumerate(displayed_forward):
            node_id = f"fwd_{i}"
            # Resolve link to full path with .md extension
            link_path = str(self.kb_root / f"{link}.md")
            self._graph_nodes[node_id] = {
                "name": self._display_name(link),
                "type": "forward",
                "path": link_path,
            }
            # Position forward links below center, spread in arc
            count = len(displayed_forward)
            angle = math.pi/2 + (math.pi * (i + 0.5) / max(count, 1)) - math.pi/2
            radius = 3 + (i % 3)  # Stagger radii for density
            x = self.CENTER + radius * math.cos(angle)
            y = self.CENTER + radius * math.sin(angle)
            self._positions[node_id] = (x, y)
            self._edges.append(("current", node_id))

        # Get backlinks from graph
        all_backlinks = list(self._graph.get_backlinks(filepath))
        self._total_back = len(all_backlinks)
        displayed_back = all_backlinks[:self.MAX_BACK]

        # Add backlink nodes - spread in upper half (above center)
        for i, bl in enumerate(displayed_back):
            node_id = f"back_{i}"
            self._graph_nodes[node_id] = {
                "name": self._display_name(bl),
                "type": "backlink",
                "path": bl,
            }
            # Position backlinks above center, spread in arc
            count = len(displayed_back)
            angle = -math.pi/2 + (math.pi * (i + 0.5) / max(count, 1)) - math.pi/2
            radius = 3 + (i % 3)  # Stagger radii for density
            x = self.CENTER + radius * math.cos(angle)
            y = self.CENTER + radius * math.sin(angle)
            self._positions[node_id] = (x, y)
            self._edges.append((node_id, "current"))

        # Add action link nodes - spread on right side
        self._total_actions = len(action_links)
        displayed_actions = action_links[:self.MAX_ACTIONS]

        for i, action in enumerate(displayed_actions):
            node_id = f"action_{i}"
            self._graph_nodes[node_id] = {
                "name": action.display_name,
                "type": "action",
                "command": action.command,  # Full command for execution
            }
            # Position action links to the right of center, vertical spread
            count = len(displayed_actions)
            # Spread vertically from top to bottom on right side
            y_offset = (i - (count - 1) / 2) * 1.5
            radius = 4 + (i % 2)  # Stagger radii
            x = self.CENTER + radius
            y = self.CENTER + y_offset
            self._positions[node_id] = (x, y)
            self._edges.append(("current", node_id))

    def _run_layout(self) -> None:
        """Run force-directed layout algorithm."""
        if len(self._graph_nodes) <= 1:
            return

        # Velocities for each node
        velocities: dict[str, tuple[float, float]] = {
            nid: (0.0, 0.0) for nid in self._graph_nodes
        }

        for _ in range(self.ITERATIONS):
            forces: dict[str, tuple[float, float]] = {
                nid: (0.0, 0.0) for nid in self._graph_nodes
            }

            # Repulsive forces between all pairs
            node_ids = list(self._graph_nodes.keys())
            for i, n1 in enumerate(node_ids):
                for n2 in node_ids[i + 1:]:
                    x1, y1 = self._positions[n1]
                    x2, y2 = self._positions[n2]
                    dx = x2 - x1
                    dy = y2 - y1
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist < self.MIN_DIST:
                        dist = self.MIN_DIST

                    # Repulsive force (inverse square)
                    force = self.REPULSION_K / (dist * dist)
                    fx = force * dx / dist
                    fy = force * dy / dist

                    # Apply to both nodes (opposite directions)
                    f1x, f1y = forces[n1]
                    f2x, f2y = forces[n2]
                    forces[n1] = (f1x - fx, f1y - fy)
                    forces[n2] = (f2x + fx, f2y + fy)

            # Attractive forces along edges (spring)
            for n1, n2 in self._edges:
                if n1 not in self._positions or n2 not in self._positions:
                    continue
                x1, y1 = self._positions[n1]
                x2, y2 = self._positions[n2]
                dx = x2 - x1
                dy = y2 - y1
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 0.1:
                    continue

                # Spring force (proportional to distance)
                force = self.SPRING_K * dist
                fx = force * dx / dist
                fy = force * dy / dist

                f1x, f1y = forces[n1]
                f2x, f2y = forces[n2]
                forces[n1] = (f1x + fx, f1y + fy)
                forces[n2] = (f2x - fx, f2y - fy)

            # Center gravity - pull nodes toward center
            for nid in node_ids:
                if nid == "current":
                    continue  # Keep current at center
                x, y = self._positions[nid]
                dx = self.CENTER - x
                dy = self.CENTER - y
                fx, fy = forces[nid]
                forces[nid] = (fx + dx * 0.05, fy + dy * 0.05)

            # Update velocities and positions
            for nid in node_ids:
                if nid == "current":
                    continue  # Current stays at center

                fx, fy = forces[nid]
                vx, vy = velocities[nid]

                # Update velocity with damping
                vx = (vx + fx) * self.DAMPING
                vy = (vy + fy) * self.DAMPING
                velocities[nid] = (vx, vy)

                # Update position
                x, y = self._positions[nid]
                x = max(1, min(self.GRID_SIZE - 2, x + vx))
                y = max(1, min(self.GRID_SIZE - 2, y + vy))
                self._positions[nid] = (x, y)

    def _display_name(self, path: str) -> str:
        """Convert a path to a short display name."""
        p = Path(path)
        name = p.stem if p.suffix == ".md" else p.name
        if len(name) > 10:
            return name[:8] + ".."
        return name

    def render(self) -> Text:
        """Render the 19×19 force-directed graph."""
        # Initialize empty grid (using 2 chars per cell for aspect ratio)
        grid: list[list[str]] = [
            ["· " for _ in range(self.GRID_SIZE)]
            for _ in range(self.GRID_SIZE)
        ]
        styles: list[list[str]] = [
            ["dim" for _ in range(self.GRID_SIZE)]
            for _ in range(self.GRID_SIZE)
        ]

        # Draw edges first (as paths between nodes)
        for n1, n2 in self._edges:
            if n1 in self._positions and n2 in self._positions:
                self._draw_edge(grid, styles, n1, n2)

        # Draw nodes on top
        for nid, info in self._graph_nodes.items():
            if nid not in self._positions:
                continue
            x, y = self._positions[nid]
            gx, gy = int(round(x)), int(round(y))
            if 0 <= gx < self.GRID_SIZE and 0 <= gy < self.GRID_SIZE:
                is_selected = (nid == self.selected_node)
                if info["type"] == "current":
                    grid[gy][gx] = "◆ " if is_selected else "◉ "
                    styles[gy][gx] = "bold reverse yellow" if is_selected else "bold yellow"
                elif info["type"] == "forward":
                    grid[gy][gx] = "◆ " if is_selected else "○ "
                    styles[gy][gx] = "bold reverse green" if is_selected else "green"
                elif info["type"] == "backlink":
                    grid[gy][gx] = "◆ " if is_selected else "● "
                    styles[gy][gx] = "bold reverse cyan" if is_selected else "cyan"
                elif info["type"] == "action":
                    grid[gy][gx] = "◆ " if is_selected else "◇ "
                    styles[gy][gx] = "bold reverse magenta" if is_selected else "magenta"

        # Build output text
        text = Text()

        # Title row with counts (highlight when focused)
        back_count = sum(1 for n in self._graph_nodes if "back" in n)
        fwd_count = sum(1 for n in self._graph_nodes if "fwd" in n)
        action_count = sum(1 for n in self._graph_nodes if "action" in n)
        title_style = "bold reverse green" if self.has_focus else "bold dim"
        text.append("  Link Graph ", style=title_style)
        text.append(f"●{self._total_back}", style="cyan")
        text.append(" ", style="dim")
        text.append(f"○{self._total_forward}", style="green")
        if self._total_actions > 0:
            text.append(" ", style="dim")
            text.append(f"◇{self._total_actions}", style="magenta")
        text.append("\n")

        for row in range(self.GRID_SIZE):
            for col in range(self.GRID_SIZE):
                text.append(grid[row][col], style=styles[row][col])
            text.append("\n")

        return text

    def _draw_edge(
        self,
        grid: list[list[str]],
        styles: list[list[str]],
        n1: str,
        n2: str,
    ) -> None:
        """Draw an edge between two nodes using Bresenham-like stepping."""
        x1, y1 = self._positions[n1]
        x2, y2 = self._positions[n2]

        # Simple line drawing
        steps = max(abs(x2 - x1), abs(y2 - y1))
        if steps < 2:
            return

        for i in range(1, int(steps)):
            t = i / steps
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            gx, gy = int(round(x)), int(round(y))

            if 0 <= gx < self.GRID_SIZE and 0 <= gy < self.GRID_SIZE:
                # Don't overwrite nodes
                if grid[gy][gx] in ("· ", "╌ ", "│ ", "─ "):
                    # Determine line character based on direction
                    dx = x2 - x1
                    dy = y2 - y1
                    if abs(dx) > abs(dy) * 2:
                        grid[gy][gx] = "─ "
                    elif abs(dy) > abs(dx) * 2:
                        grid[gy][gx] = "│ "
                    else:
                        grid[gy][gx] = "╌ "
                    styles[gy][gx] = "dim blue"

    def scan_kb(self) -> None:
        """Scan the KB to build the link graph."""
        self._graph = LinkGraph()

        # Scan all .md files in KB
        for md_file in self.kb_root.rglob("*.md"):
            try:
                content = md_file.read_text()
                self._graph.update_file(str(md_file), content, self.kb_root)
            except Exception:
                continue

    def toggle(self) -> None:
        """Toggle visibility."""
        self.toggle_class("hidden")

    def on_focus(self) -> None:
        """Refresh when gaining focus to update title highlight."""
        self.refresh()

    def on_blur(self) -> None:
        """Refresh when losing focus to update title highlight."""
        self.refresh()

    def on_key(self, event: events.Key) -> None:
        """Handle arrow key navigation and Enter for selection."""
        if event.key in ("up", "down", "left", "right"):
            self._move_cursor(event.key)
            event.stop()
            event.prevent_default()
        elif event.key == "enter":
            if self.selected_node and self.selected_node in self._graph_nodes:
                info = self._graph_nodes[self.selected_node]
                if info["type"] == "action" and "command" in info:
                    # Emit action command for execution
                    self.post_message(self.ActionSelected(info["command"]))
                elif "path" in info:
                    self.post_message(self.NodeSelected(info["path"]))
            event.stop()
            event.prevent_default()

    def _move_cursor(self, direction: str) -> None:
        """Move selection to nearest node in given direction."""
        # If no node selected, select center node
        if not self.selected_node or self.selected_node not in self._positions:
            if self._current_id:
                self.selected_node = self._current_id
                # Emit highlight message for initial selection
                if self.selected_node in self._graph_nodes:
                    info = self._graph_nodes[self.selected_node]
                    self.post_message(self.NodeHighlighted(
                        node_type=info["type"],
                        filepath=info.get("path"),
                        command=info.get("command"),
                    ))
                self.refresh()
            return

        cx, cy = self._positions[self.selected_node]
        candidates: list[tuple[float, str]] = []

        for node_id, (nx, ny) in self._positions.items():
            if node_id == self.selected_node:
                continue

            # Filter by direction
            if direction == "up" and ny >= cy:
                continue
            if direction == "down" and ny <= cy:
                continue
            if direction == "left" and nx >= cx:
                continue
            if direction == "right" and nx <= cx:
                continue

            # Calculate Manhattan distance
            dist = abs(nx - cx) + abs(ny - cy)
            candidates.append((dist, node_id))

        if candidates:
            candidates.sort()
            self.selected_node = candidates[0][1]
            self.refresh()

        # Always emit highlight message for current selection (even if no movement)
        if self.selected_node in self._graph_nodes:
            info = self._graph_nodes[self.selected_node]
            self.post_message(self.NodeHighlighted(
                node_type=info["type"],
                filepath=info.get("path"),
                command=info.get("command"),
            ))

    def select_node_by_path(self, filepath: str) -> None:
        """Select a node by its file path (for sync with FileTree)."""
        for node_id, info in self._graph_nodes.items():
            if info.get("path") == filepath:
                self.selected_node = node_id
                # Emit highlight message for the selected node
                self.post_message(self.NodeHighlighted(
                    node_type=info["type"],
                    filepath=info.get("path"),
                    command=info.get("command"),
                ))
                self.refresh()
                return
