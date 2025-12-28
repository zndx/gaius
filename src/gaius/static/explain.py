"""Contextual explanations for grid state and overlays."""

from ..core.state import ViewMode, OverlayMode


def get_view_explanation(view_mode: ViewMode) -> str:
    """Get explanation for the current view mode."""
    explanations = {
        ViewMode.GO: """**Go View**: Strategic territory visualization.
Black and white stones represent competing positions or allocations.
Influence radiates from stone positions, creating territories.""",

        ViewMode.THETA: """**Theta View**: Information density heatmap.
Theta waves (4-8 Hz) facilitate memory consolidation - the transfer
of information from short-term to long-term storage.
Color intensity shows knowledge density. Brighter cells indicate
higher document concentration in the UMAP projection.""",

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
- H1 cycles (red !): Loops in the knowledge graph - connected concepts
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
    # Quadrant analysis (topological/semantic interpretation)
    if x < 6 and y < 6:
        quadrant = "Upper-left quadrant: Sparse embedding region, high exploration value."
    elif x >= 13 and y < 6:
        quadrant = "Upper-right quadrant: Semantic periphery, potential knowledge gap."
    elif x < 6 and y >= 13:
        quadrant = "Lower-left quadrant: Boundary region, possible H1 cycle participation."
    elif x >= 13 and y >= 13:
        quadrant = "Lower-right quadrant: Transition zone, negative curvature likely."
    elif 6 <= x <= 12 and 6 <= y <= 12:
        quadrant = "Central region: High-density knowledge cluster."
    else:
        quadrant = "Edge region: Semantic boundary, exploration target."

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
