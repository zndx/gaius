"""Contextual explanations for grid state and overlays."""

from ..core.state import ViewMode, OverlayMode


def get_view_explanation(view_mode: ViewMode) -> str:
    """Get explanation for the current view mode."""
    explanations = {
        ViewMode.GO: """**Go View**: Strategic territory visualization.
Black and white stones represent competing positions or allocations.
Influence radiates from stone positions, creating territories.""",

        ViewMode.PENSION: """**Pension View**: Asset allocation heatmap.
Color intensity shows allocation weight (0-100%).
Brighter cells indicate higher concentration.
Navigate to explore allocation distribution.""",

        ViewMode.SWARM: """**Swarm View**: Multi-agent activity map.
Agent positions shown with role indicators.
Activity intensity reflects recent agent engagement.
Agents collaborate to analyze the current domain.""",
    }
    return explanations.get(view_mode, "Unknown view mode.")


def get_overlay_explanation(overlay_mode: OverlayMode, x: int, y: int) -> str:
    """Get explanation for the current overlay mode."""
    explanations = {
        OverlayMode.NONE: """**No Overlay**: Raw view without additional analysis layers.""",

        OverlayMode.TOPOLOGY: f"""**Topology Overlay**: Persistent homology features (H0/H1/H2).
- H1 cycles (red ⚠): Loops in the knowledge graph - connected concepts
- H2 voids (magenta ◇): Cavities - missing knowledge or gaps
Position ({x}, {y}) topological significance: {"High" if 4 <= x <= 14 and 4 <= y <= 14 else "Edge region"}
Persistent features reveal stable structural patterns in the data.""",

        OverlayMode.GEOMETRY: f"""**Geometry Overlay**: Ricci curvature heatmap.
- Red regions (κ < 0): Semantic boundaries - meaning changes rapidly
- Blue regions (κ > 0): Semantic interiors - uniform concept clusters
Like turbulent water driving complex diatom colonies, negative curvature
indicates "turbulent" regions where understanding shifts abruptly.
Position ({x}, {y}) is {"a boundary region" if (x + y) % 5 < 2 else "an interior region"}.""",

        OverlayMode.DYNAMICS: f"""**Dynamics Overlay**: Gradient vector field.
Arrows show the direction of semantic change on the manifold.
- Bright arrows: Strong gradient (rapid semantic shift)
- Dim dots: Stable points (semantic equilibria)
Position ({x}, {y}) flow direction indicates {"high gradient" if abs(x - 9) > 5 or abs(y - 9) > 5 else "moderate flow"}.""",

        OverlayMode.AGENTS: f"""**Agents Overlay**: Swarm member positions and states.
Each agent occupies a strategic position based on their role.
Position ({x}, {y}) {"is near an agent" if _near_agent(x, y) else "is unoccupied"}.
Agent roles: Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary.""",
    }
    return explanations.get(overlay_mode, "Unknown overlay mode.")


def _near_agent(x: int, y: int) -> bool:
    """Check if position is near a known agent position."""
    agent_positions = [(10, 10), (5, 5), (14, 8), (8, 14), (12, 4), (6, 12), (16, 16)]
    for ax, ay in agent_positions:
        if abs(x - ax) <= 2 and abs(y - ay) <= 2:
            return True
    return False


def get_position_context(x: int, y: int) -> str:
    """Get contextual explanation for a grid position."""
    # Quadrant analysis
    if x < 6 and y < 6:
        quadrant = "Upper-left quadrant: Conservative/defensive positioning."
    elif x >= 13 and y < 6:
        quadrant = "Upper-right quadrant: Growth-oriented exposure."
    elif x < 6 and y >= 13:
        quadrant = "Lower-left quadrant: Fixed income concentration."
    elif x >= 13 and y >= 13:
        quadrant = "Lower-right quadrant: Alternative investments."
    elif 6 <= x <= 12 and 6 <= y <= 12:
        quadrant = "Central region: Balanced, diversified core."
    else:
        quadrant = "Edge region: Transitional positioning."

    # Corner/star point significance (Go terminology)
    star_points = [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)]
    if (x, y) in star_points:
        star = "\n**Star Point**: Key strategic position with high influence potential."
    elif (x, y) == (9, 9):
        star = "\n**Tengen**: Center of the board - maximum strategic flexibility."
    else:
        star = ""

    return f"{quadrant}{star}"


def get_minigrid_explanation(grid_name: str, x: int, y: int) -> str:
    """Get explanation for what a mini-grid is showing."""
    explanations = {
        "Embed": f"""**Embedding Projection**: Local neighborhood in embedding space.
Shows nearby points projected from high-dimensional representation.
Cursor at ({x}, {y}) - mini-grid shows relative positions of neighbors.""",

        "Iso": f"""**Isometric View**: Orthographic projection of 3D topology.
Reveals depth and layering not visible in 2D.
Height represents data density or feature intensity.""",

        "Time": f"""**Temporal Slice**: Recent history of this region.
Horizontal axis: time steps (left=past, right=present).
Vertical axis: metric values over time.""",
    }
    return explanations.get(grid_name, "Auxiliary projection view.")


def generate_explanation(
    view_mode: ViewMode,
    overlay_mode: OverlayMode,
    x: int,
    y: int,
) -> str:
    """Generate a full contextual explanation for the current state."""
    sections = [
        f"## Position ({x}, {y})",
        "",
        get_position_context(x, y),
        "",
        "---",
        "",
        get_view_explanation(view_mode),
        "",
        "---",
        "",
        get_overlay_explanation(overlay_mode, x, y),
        "",
        "---",
        "",
        "### Mini-Grids",
        get_minigrid_explanation("Embed", x, y),
        "",
        get_minigrid_explanation("Iso", x, y),
    ]
    return "\n".join(sections)
