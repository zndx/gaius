"""Real mini-grid data from TDA and UMAP projections.

Generates orthographic projections for the 9×9 mini-grids:
- Embed: Local embedding neighborhood (high-dim → 2D)
- Iso: Isometric projection with TDA-derived elevation
- Temporal: Not yet implemented (future: time-series of grid states)

These views provide CAD-style orthographic projections of the knowledge space,
helping users understand the topological structure and semantic neighborhoods.
"""

import numpy as np
from dataclasses import dataclass

from .projection import GridData
from .tda import TDAFeatures


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
) -> MiniGridData:
    """Generate Iso view: curvature-based elevation map (biomorphic landscape).

    Shows a 3D isometric view where elevation is Ricci curvature:
    - Negative κ (boundaries) → high peaks (turbulent stream = complex colonies)
    - Positive κ (interiors) → low valleys (calm water = simple cells)
    - Flat κ ≈ 0 → plains (uniform regions)

    This reveals the "turbulence" in the semantic manifold, inspired by
    how environmental randomness drives morphological complexity in diatoms.

    Args:
        grid_data: Grid projection data
        curvatures: Per-point Ricci curvature values (from GeometricFeatures)
        cursor_x: Cursor X position (0-18)
        cursor_y: Cursor Y position (0-18)
        radius: Radius around cursor to show (default 4 = 9×9)

    Returns:
        MiniGridData with curvature elevation map
    """
    # Initialize empty grid
    iso_grid = [[0.0] * 9 for _ in range(9)]

    if grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) == 0:
        return MiniGridData(
            grid=iso_grid,
            title="Iso (κ)",
            description="No projection data available",
        )

    # Compute curvature-based elevation for each mini-grid cell
    for mx in range(9):
        for my in range(9):
            # Map mini-grid coords back to main grid coords
            gx = cursor_x + (mx - 4)
            gy = cursor_y + (my - 4)

            if 0 <= gx < 19 and 0 <= gy < 19:
                # Get point at this grid position
                point_idx = grid_data.grid_to_embedding.get((gx, gy))

                if point_idx is not None and curvatures and point_idx < len(curvatures):
                    # Map curvature to elevation
                    # Negative κ → high (boundaries, "turbulence")
                    # Positive κ → low (interiors, "calm")
                    κ = curvatures[point_idx]

                    if κ < -0.3:
                        elevation = 0.9  # High peaks (strong boundaries)
                    elif κ < 0:
                        # Linear map [-0.3, 0] → [0.5, 0.9]
                        elevation = 0.5 + (-κ * 1.33)
                    elif κ > 0.3:
                        elevation = 0.1  # Deep valleys (strong interiors)
                    else:
                        # Linear map [0, 0.3] → [0.5, 0.1]
                        elevation = 0.5 - (κ * 1.33)

                    iso_grid[my][mx] = elevation
                else:
                    # Empty space or no curvature data
                    iso_grid[my][mx] = 0.0
            else:
                # Out of bounds
                iso_grid[my][mx] = 0.0

    return MiniGridData(
        grid=iso_grid,
        title="Iso (κ)",
        description=f"Curvature elevation (κ) around ({cursor_x}, {cursor_y})",
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
        view_mode: Current view mode (go, pension, swarm)
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
) -> dict[str, list[list[float]]]:
    """Get real mini-grid data from curvature and UMAP projections.

    Replaces the static test_data.get_minigrid_data() with real data.

    Args:
        grid_data: Grid projection from UMAP
        curvatures: Per-point Ricci curvature values (from GeometryComputer)
        cursor_x: Cursor X (0-18)
        cursor_y: Cursor Y (0-18)

    Returns:
        Dict with "top" (Iso) and "right" (Embed) grids
    """
    if grid_data is None:
        # Fallback to empty grids
        empty = [[0.0] * 9 for _ in range(9)]
        return {"top": empty, "right": empty}

    # Generate real views
    embed_data = get_embed_view(grid_data, cursor_x, cursor_y)
    iso_data = get_iso_view(grid_data, curvatures, cursor_x, cursor_y)

    return {
        "right": embed_data.grid,  # Right mini-grid = Embed
        "top": iso_data.grid,  # Top/bottom mini-grid = Iso
    }
