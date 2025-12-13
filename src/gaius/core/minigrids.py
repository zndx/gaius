"""Real mini-grid data from TDA and UMAP projections.

Generates orthographic projections for the 9×9 mini-grids:
- Embed: Local embedding neighborhood (high-dim → 2D)
- Iso: Isometric projection with TDA-derived elevation (toggleable modes)
- Temporal: Not yet implemented (future: time-series of grid states)

These views provide CAD-style orthographic projections of the knowledge space,
helping users understand the topological structure and semantic neighborhoods.

Iso Modes (toggled via 'i' key):
- Curvature (κ): Semantic boundaries via Ricci curvature
- Persistence (π): Topological complexity from H0+H1+H2
- Complexity (σ): Semantic diversity within documents
- Boundary (β): Documents forming semantic loops
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .projection import GridData
from .state import IsoMode
from .tda import TDAFeatures

if TYPE_CHECKING:
    from .iso_features import IsoFeatures


@dataclass
class MiniGridData:
    """Data for a 9×9 mini-grid view."""

    grid: list[list[float]]  # 9×9 values in [0, 1]
    title: str
    description: str  # What this view represents


def get_embed_view(
    grid_data: GridData,
    cursor_x: int,
    cursor_y: int,
    radius: int = 4,
) -> MiniGridData:
    """Generate Embed view: local embedding neighborhood.

    Shows the semantic density around the cursor position in the original
    high-dimensional embedding space, projected to 2D.

    Args:
        grid_data: Grid projection data with raw embeddings
        cursor_x: Cursor X position (0-18)
        cursor_y: Cursor Y position (0-18)
        radius: Radius around cursor to show (default 4 = 9×9)

    Returns:
        MiniGridData with embedding neighborhood visualization
    """
    # Initialize empty grid
    embed_grid = [[0.0] * 9 for _ in range(9)]

    if grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) == 0:
        return MiniGridData(
            grid=embed_grid,
            title="Embed",
            description="No embedding data available",
        )

    # Find points near cursor in grid space
    cursor_point_idx = grid_data.grid_to_embedding.get((cursor_x, cursor_y))
    if cursor_point_idx is None:
        return MiniGridData(
            grid=embed_grid,
            title="Embed",
            description="No point at cursor position",
        )

    # Get cursor embedding
    cursor_embedding = grid_data.raw_embeddings[cursor_point_idx]

    # Compute similarities to all points in the neighborhood
    neighborhood_indices = []
    for (gx, gy), idx in grid_data.grid_to_embedding.items():
        # Check if in 9×9 neighborhood around cursor
        dx = gx - cursor_x
        dy = gy - cursor_y
        if abs(dx) <= radius and abs(dy) <= radius:
            neighborhood_indices.append((gx, gy, idx))

    # Compute cosine similarities
    for gx, gy, idx in neighborhood_indices:
        embedding = grid_data.raw_embeddings[idx]

        # Cosine similarity
        dot = np.dot(cursor_embedding, embedding)
        norm_cursor = np.linalg.norm(cursor_embedding)
        norm_emb = np.linalg.norm(embedding)

        if norm_cursor > 0 and norm_emb > 0:
            similarity = dot / (norm_cursor * norm_emb)
        else:
            similarity = 0.0

        # Map to mini-grid coordinates (cursor at center = 4, 4)
        mx = 4 + (gx - cursor_x)
        my = 4 + (gy - cursor_y)

        if 0 <= mx < 9 and 0 <= my < 9:
            # Similarity is in [-1, 1], map to [0, 1]
            embed_grid[my][mx] = (similarity + 1) / 2

    return MiniGridData(
        grid=embed_grid,
        title="Embed",
        description=f"Embedding similarity around ({cursor_x}, {cursor_y})",
    )


def get_iso_view(
    grid_data: GridData,
    curvatures: list[float] | None,
    cursor_x: int,
    cursor_y: int,
    radius: int = 4,
    iso_mode: IsoMode = IsoMode.CURVATURE,
    iso_features: "IsoFeatures | None" = None,
) -> MiniGridData:
    """Generate Iso view based on current mode.

    Shows a 3D isometric view where elevation reveals topological structure:

    Modes (toggled via 'i' key):
    - Curvature (κ): Ricci curvature - semantic boundaries
    - Persistence (π): Total persistence - topological complexity
    - Complexity (σ): Token variance - semantic diversity
    - Boundary (β): Cocycle contribution - loop participation

    Uses inverse-distance weighted interpolation to fill gaps between sparse
    data points, creating a continuous elevation surface.

    Args:
        grid_data: Grid projection data
        curvatures: Per-point Ricci curvature values (legacy, used for CURVATURE mode)
        cursor_x: Cursor X position (0-18)
        cursor_y: Cursor Y position (0-18)
        radius: Radius around cursor to show (default 4 = 9×9)
        iso_mode: Which visualization mode to use
        iso_features: Pre-computed IsoFeatures (from TDA on multi-vectors)

    Returns:
        MiniGridData with mode-specific elevation map
    """
    iso_grid = [[0.0] * 9 for _ in range(9)]

    # Mode symbols for display
    mode_symbols = {
        IsoMode.CURVATURE: "κ",
        IsoMode.PERSISTENCE: "π",
        IsoMode.COMPLEXITY: "σ",
        IsoMode.BOUNDARY: "β",
    }
    symbol = mode_symbols.get(iso_mode, "?")

    if grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) == 0:
        return MiniGridData(
            grid=iso_grid,
            title=f"Iso ({symbol})",
            description="No projection data available",
        )

    # Select feature array based on mode
    values = None

    if iso_features is not None:
        # Use pre-computed IsoFeatures
        mode_to_array = {
            IsoMode.CURVATURE: iso_features.curvatures,
            IsoMode.PERSISTENCE: iso_features.persistence,
            IsoMode.COMPLEXITY: iso_features.complexity,
            IsoMode.BOUNDARY: iso_features.boundary,
        }
        values = mode_to_array.get(iso_mode)

    # Fallback to legacy curvatures for CURVATURE mode
    if values is None and iso_mode == IsoMode.CURVATURE and curvatures is not None:
        values = curvatures

    # If still no values, fall back to density visualization
    if values is None or len(values) == 0:
        return _iso_from_density(grid_data, cursor_x, cursor_y, symbol)

    # Collect known values in the 9x9 neighborhood
    # Format: [(mx, my, value), ...]
    known_points = []

    for mx in range(9):
        for my in range(9):
            gx = cursor_x + (mx - 4)
            gy = cursor_y + (my - 4)

            if 0 <= gx < 19 and 0 <= gy < 19:
                point_idx = grid_data.grid_to_embedding.get((gx, gy))

                if point_idx is not None and point_idx < len(values):
                    val = values[point_idx]
                    known_points.append((mx, my, float(val)))

    # If no data points, fall back to density visualization
    if not known_points:
        return _iso_from_density(grid_data, cursor_x, cursor_y, symbol)

    # Compute elevation for each cell using IDW interpolation
    # For curvature mode, invert (negative κ = high elevation)
    invert = (iso_mode == IsoMode.CURVATURE)

    for mx in range(9):
        for my in range(9):
            # Check if we have exact data at this point
            exact_val = None
            for kx, ky, val in known_points:
                if kx == mx and ky == my:
                    exact_val = val
                    break

            if exact_val is not None:
                val = exact_val
            else:
                # Inverse Distance Weighted interpolation
                val = _idw_interpolate(mx, my, known_points)

            # Map value to elevation
            if iso_mode == IsoMode.CURVATURE:
                elevation = _curvature_to_elevation(val)
            else:
                # For normalized [0,1] values, use directly as elevation
                elevation = float(val)
                if invert:
                    elevation = 1.0 - elevation

            iso_grid[my][mx] = elevation

    # Mode-specific descriptions
    descriptions = {
        IsoMode.CURVATURE: "Ricci curvature (boundaries)",
        IsoMode.PERSISTENCE: "Topological complexity",
        IsoMode.COMPLEXITY: "Semantic diversity",
        IsoMode.BOUNDARY: "Loop participation",
    }
    desc = descriptions.get(iso_mode, iso_mode.value)

    return MiniGridData(
        grid=iso_grid,
        title=f"Iso ({symbol})",
        description=f"{desc} around ({cursor_x}, {cursor_y})",
    )


def _idw_interpolate(
    x: int, y: int, known_points: list[tuple[int, int, float]], power: float = 2.0
) -> float:
    """Inverse Distance Weighted interpolation.

    Args:
        x, y: Target coordinates
        known_points: List of (x, y, value) tuples
        power: Distance weighting power (higher = more local)

    Returns:
        Interpolated value
    """
    if not known_points:
        return 0.0

    numerator = 0.0
    denominator = 0.0

    for kx, ky, value in known_points:
        dist = ((x - kx) ** 2 + (y - ky) ** 2) ** 0.5

        if dist < 0.001:  # Essentially zero distance
            return value

        weight = 1.0 / (dist ** power)
        numerator += weight * value
        denominator += weight

    if denominator > 0:
        return numerator / denominator
    return 0.0


def _curvature_to_elevation(κ: float) -> float:
    """Map curvature value to elevation [0, 1].

    Negative κ (boundaries) → high elevation
    Positive κ (interiors) → low elevation
    """
    if κ < -0.3:
        return 0.9  # High peaks (strong boundaries)
    elif κ < 0:
        # Linear map [-0.3, 0] → [0.5, 0.9]
        return 0.5 + (-κ * 1.33)
    elif κ > 0.3:
        return 0.1  # Deep valleys (strong interiors)
    else:
        # Linear map [0, 0.3] → [0.5, 0.1]
        return 0.5 - (κ * 1.33)


def _iso_from_density(
    grid_data: GridData, cursor_x: int, cursor_y: int, symbol: str = "ρ"
) -> MiniGridData:
    """Fallback Iso view using document density when feature data unavailable.

    Uses distance from cursor to nearest documents to create a density-based
    elevation map.

    Args:
        grid_data: Grid projection data
        cursor_x: Cursor X position
        cursor_y: Cursor Y position
        symbol: Mode symbol to display in title (default ρ for density)
    """
    iso_grid = [[0.0] * 9 for _ in range(9)]

    # Collect document positions in neighborhood
    doc_positions = []
    for (gx, gy) in grid_data.grid_to_embedding.keys():
        # Convert to mini-grid coordinates
        mx = 4 + (gx - cursor_x)
        my = 4 + (gy - cursor_y)
        if 0 <= mx < 9 and 0 <= my < 9:
            doc_positions.append((mx, my))

    if not doc_positions:
        return MiniGridData(
            grid=iso_grid,
            title=f"Iso ({symbol})",
            description="No documents in neighborhood",
        )

    # Compute density-based elevation for each cell
    for mx in range(9):
        for my in range(9):
            # Distance to nearest document
            min_dist = 999.0
            for dx, dy in doc_positions:
                dist = ((mx - dx) ** 2 + (my - dy) ** 2) ** 0.5
                min_dist = min(min_dist, dist)

            # Closer to documents = higher elevation
            # Max distance in 9x9 grid is ~11.3
            if min_dist < 0.001:
                elevation = 1.0  # On a document
            else:
                elevation = max(0.0, 1.0 - (min_dist / 6.0))

            iso_grid[my][mx] = elevation

    return MiniGridData(
        grid=iso_grid,
        title=f"Iso ({symbol})",
        description=f"Density fallback around ({cursor_x}, {cursor_y})",
    )


def explain_grid_view(
    grid_data: GridData,
    tda_features: TDAFeatures | None,
    cursor_x: int,
    cursor_y: int,
    view_mode: str,
    overlay_mode: str,
) -> str:
    """Generate natural language explanation of what the user is seeing.

    Uses the local LLM to explain the grid state, mini-grid views, and
    topological features at the cursor position.

    Args:
        grid_data: Grid projection data
        tda_features: TDA features
        cursor_x: Cursor position X
        cursor_y: Cursor position Y
        view_mode: Current view mode (go, theta, swarm)
        overlay_mode: Current overlay (none, risk, h1, h2, etc.)

    Returns:
        Natural language explanation string
    """
    # Build context about the current state
    context_parts = []

    # Overall grid statistics
    context_parts.append(f"Grid coverage: {grid_data.coverage:.1%}")
    context_parts.append(f"Total documents: {grid_data.n_documents}")

    # Cursor position info
    point_idx = grid_data.grid_to_embedding.get((cursor_x, cursor_y))
    if point_idx is not None:
        point = grid_data.points[point_idx]
        context_parts.append(f"At cursor ({cursor_x}, {cursor_y}): {point.title}")
    else:
        context_parts.append(f"Cursor at ({cursor_x}, {cursor_y}): empty cell")

    # TDA features
    if tda_features:
        context_parts.append(f"H0 (components): {tda_features.h0_count}")
        context_parts.append(f"H1 (loops): {tda_features.h1_count}")
        context_parts.append(f"H2 (voids): {tda_features.h2_count}")
        context_parts.append(f"Topological entropy: {tda_features.entropy:.3f}")

        # Risk at cursor
        if point_idx is not None and tda_features.risk_scores:
            if point_idx < len(tda_features.risk_scores):
                risk = tda_features.risk_scores[point_idx]
                context_parts.append(f"Risk score at cursor: {risk:.3f}")

    # View mode info
    context_parts.append(f"View: {view_mode}, Overlay: {overlay_mode}")

    # Build prompt for local LLM
    prompt = f"""You are explaining a 19×19 grid visualization of a knowledge base to a user.

Context:
{chr(10).join('- ' + p for p in context_parts)}

The grid shows documents projected via UMAP from high-dimensional embeddings.
Two mini-grids provide orthographic views:

1. **Embed view**: Shows embedding similarity (cosine) around the cursor.
   Brighter areas = more semantically similar to cursor document.

2. **Iso view**: Shows topological "elevation" using TDA risk scores.
   Higher elevation = more topologically unstable/bridge-like.
   These are critical connection points in the knowledge graph.

Explain in 2-3 sentences:
1. What the Iso view reveals about the information domain structure
2. How the user should interpret high vs low elevation areas
3. What the relationship between grid position and semantic meaning implies

Be concise, spatial, and focused on helping the user understand the topology."""

    # Call local LLM via optillm
    try:
        from ..inference.llm import query_local_llm

        response = query_local_llm(prompt, max_tokens=200)
        return response.strip()

    except Exception as e:
        # Fallback explanation
        return (
            f"The grid shows {grid_data.n_documents} documents projected via UMAP. "
            f"The Iso view shows topological elevation (TDA risk scores) - "
            f"higher areas are bridge points connecting different semantic regions. "
            f"The Embed view shows semantic similarity around the cursor position."
        )


def get_real_minigrid_data(
    grid_data: GridData | None,
    curvatures: list[float] | None,
    cursor_x: int,
    cursor_y: int,
    iso_mode: IsoMode = IsoMode.CURVATURE,
    iso_features: "IsoFeatures | None" = None,
) -> dict[str, "MiniGridData"]:
    """Get real mini-grid data from curvature and UMAP projections.

    Replaces the static test_data.get_minigrid_data() with real data.

    Args:
        grid_data: Grid projection from UMAP
        curvatures: Per-point Ricci curvature values (from GeometryComputer)
        cursor_x: Cursor X (0-18)
        cursor_y: Cursor Y (0-18)
        iso_mode: Current Iso visualization mode
        iso_features: Pre-computed IsoFeatures from TDA

    Returns:
        Dict with "top" (Iso MiniGridData) and "right" (Embed MiniGridData)
    """
    if grid_data is None:
        # Fallback to empty grids
        empty = [[0.0] * 9 for _ in range(9)]
        return {
            "top": MiniGridData(grid=empty, title="Iso", description="No data"),
            "right": MiniGridData(grid=empty, title="Embed", description="No data"),
        }

    # Generate real views
    embed_data = get_embed_view(grid_data, cursor_x, cursor_y)
    iso_data = get_iso_view(
        grid_data, curvatures, cursor_x, cursor_y,
        iso_mode=iso_mode, iso_features=iso_features
    )

    return {
        "right": embed_data,  # Right mini-grid = Embed (MiniGridData)
        "top": iso_data,  # Top/bottom mini-grid = Iso (MiniGridData)
    }
