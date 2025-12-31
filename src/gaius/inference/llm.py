"""LLM interface for explaining grid positions and topological features.

Provides high-level convenience functions that wrap InferenceClient
for specific tasks like explaining curvature, topology, and semantic meaning.
"""

import logging
from dataclasses import dataclass
from typing import Any

from .client import InferenceClient, Message, CompletionResult
from .config import OptillmTechnique

logger = logging.getLogger(__name__)


@dataclass
class ExplanationContext:
    """Context for explaining a grid position."""

    # Grid position
    cursor_x: int
    cursor_y: int

    # Document at position (if any)
    document_title: str | None = None
    document_path: str | None = None

    # Geometric features
    curvature: float | None = None
    gradient_x: float | None = None
    gradient_y: float | None = None
    divergence: float | None = None

    # Topological features
    tda_entropy: float | None = None
    h0_count: int | None = None
    h1_count: int | None = None
    h2_count: int | None = None
    risk_score: float | None = None

    # Grid metadata
    view_mode: str = "go"
    overlay_mode: str = "none"
    grid_coverage: float = 0.0
    total_documents: int = 0

    # Neighborhood info
    nearby_documents: list[str] | None = None

    # Mini-grid data for visual analysis (9x9 float arrays)
    embed_grid: list[list[float]] | None = None
    iso_grid: list[list[float]] | None = None


async def explain_position(
    ctx: ExplanationContext,
    client: InferenceClient | None = None,
    max_tokens: int = 300,
) -> str:
    """Explain what the user is seeing at a grid position.

    Uses the local LLM to provide natural language explanation of:
    - Curvature and what it means semantically (turbulence metaphor)
    - Topological features (cycles, voids, entropy)
    - Document relationships and semantic neighborhoods
    - Strategic significance (why tenuki might target this region)

    Args:
        ctx: Explanation context with position and feature data
        client: InferenceClient instance (creates new one if None)
        max_tokens: Maximum response length

    Returns:
        Natural language explanation string
    """
    # Create client if not provided
    if client is None:
        try:
            client = InferenceClient()
        except ImportError as e:
            raise RuntimeError(
                f"InferenceClient not available: {e}\n"
                "Guru Meditation: #LLM.00000001.NOCLIENT\n"
                "Check: /health endpoints"
            ) from e

    # Build contextual prompt
    prompt = _build_explanation_prompt(ctx)

    try:
        result = await client.complete(
            messages=[Message(role="user", content=prompt)],
            technique=OptillmTechnique.NONE,  # Fast, no complex reasoning needed
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return result.content.strip()

    except Exception as e:
        raise RuntimeError(
            f"LLM explanation failed: {e}\n"
            "Guru Meditation: #LLM.00000002.EXPLAIN\n"
            "Check: /health endpoints"
        ) from e


def _describe_embed_view(embed_grid: list[list[float]]) -> str:
    """Describe the Embed mini-grid in visual terms.

    Analyzes the 9x9 embed grid and returns a visual description
    of the similarity pattern visible to the user.
    """
    if not embed_grid or len(embed_grid) != 9:
        return "No embed data available."

    center = embed_grid[4][4]

    # Compute neighborhood statistics
    surrounding = [
        embed_grid[y][x]
        for y in range(9)
        for x in range(9)
        if not (x == 4 and y == 4)
    ]
    avg = sum(surrounding) / len(surrounding) if surrounding else 0
    variance = sum((v - avg) ** 2 for v in surrounding) / len(surrounding) if surrounding else 0

    # Describe center intensity
    if center > 0.8:
        center_desc = "very bright at center"
    elif center > 0.5:
        center_desc = "moderately bright at center"
    else:
        center_desc = "dim at center"

    # Describe pattern based on statistics
    if variance < 0.02:
        pattern = "uniformly lit across the neighborhood"
        meaning = "documents here share similar semantic distance from each other"
    elif avg < center - 0.2:
        pattern = "brightness fading outward from center"
        meaning = "a semantic focal point - neighbors become progressively less related"
    elif avg > center + 0.1:
        pattern = "brighter around edges than center"
        meaning = "cursor sits at a local similarity minimum - a gap between clusters"
    else:
        # Check for patterns
        bright_count = sum(1 for v in surrounding if v > 0.6)
        if bright_count > 20:
            pattern = "many bright spots scattered across the view"
            meaning = "a dense neighborhood with multiple related documents"
        elif bright_count < 5:
            pattern = "mostly dim with sparse bright points"
            meaning = "sparse territory with few similar documents nearby"
        else:
            pattern = "varied brightness creating a gradient"
            meaning = "transitional zone with mixed semantic relationships"

    return f"The Embed view is {center_desc}, {pattern} - {meaning}."


def _describe_iso_view(iso_grid: list[list[float]]) -> str:
    """Describe the Iso mini-grid as semantic terrain.

    Analyzes the 9x9 iso (curvature) grid and returns a terrain
    description using landscape metaphors.
    """
    if not iso_grid or len(iso_grid) != 9:
        return "No curvature data available."

    center = iso_grid[4][4]

    surrounding = [
        iso_grid[y][x]
        for y in range(9)
        for x in range(9)
        if not (x == 4 and y == 4)
    ]
    avg = sum(surrounding) / len(surrounding) if surrounding else 0

    # Classify terrain based on elevation patterns
    if center > 0.7:
        terrain = "elevated terrain - a peak or ridgeline"
        meaning = "a semantic boundary where distinct topics diverge"
    elif center < 0.3:
        terrain = "low terrain - a valley floor"
        meaning = "deep within a semantic cluster, stable coherent ground"
    elif center > avg + 0.15:
        terrain = "a local rise above surroundings"
        meaning = "approaching a boundary between related topics"
    elif center < avg - 0.15:
        terrain = "a depression below surroundings"
        meaning = "settling into more coherent territory"
    else:
        # Check for gradient patterns
        left_avg = sum(iso_grid[y][x] for y in range(9) for x in range(4)) / 36
        right_avg = sum(iso_grid[y][x] for y in range(9) for x in range(5, 9)) / 36

        if abs(left_avg - right_avg) > 0.15:
            terrain = "a slope transitioning between elevations"
            meaning = "moving between boundary and interior regions"
        else:
            terrain = "relatively flat terrain"
            meaning = "transitional ground with no sharp semantic boundaries nearby"

    return f"The Iso view shows {terrain} - {meaning}."


def _describe_view_relationship(
    embed_grid: list[list[float]] | None,
    iso_grid: list[list[float]] | None,
) -> str:
    """Explain how Embed and Iso views relate at cursor position.

    Correlates both views to provide strategic insight about the
    current location in the knowledge space.
    """
    if not embed_grid or not iso_grid:
        return ""

    embed_center = embed_grid[4][4] if len(embed_grid) == 9 else 0.5
    iso_center = iso_grid[4][4] if len(iso_grid) == 9 else 0.5

    # Four quadrant analysis based on both views
    if embed_center > 0.6 and iso_center < 0.4:
        return (
            "**Bright Embed + low Iso** = You are at the heart of a semantic cluster. "
            "Similar documents surround you in stable territory. "
            "A good base from which to explore outward toward boundaries."
        )
    elif embed_center > 0.6 and iso_center > 0.6:
        return (
            "**Bright Embed + elevated Iso** = A bridge point. "
            "High similarity at a topological boundary suggests two related topics meeting here. "
            "This is a gateway connecting semantic neighborhoods."
        )
    elif embed_center < 0.4 and iso_center < 0.4:
        return (
            "**Dim Embed + low Iso** = Sparse territory. "
            "Few similar documents and flat terrain suggest unexplored space "
            "or a natural gap between topic clusters."
        )
    elif embed_center < 0.4 and iso_center > 0.6:
        return (
            "**Dim Embed + elevated Iso** = A frontier ridge. "
            "This is a major boundary between very different topics. "
            "Moving any direction descends into new semantic territory."
        )
    else:
        return (
            "**Mixed signals** = Transitional territory. "
            "Neither deep in a cluster nor at a sharp boundary. "
            "Good for exploration to discover nearby structure."
        )


def _build_explanation_prompt(ctx: ExplanationContext) -> str:
    """Build a hybrid visual-first + metrics prompt for explaining the grid position.

    Structure:
    1. Visual descriptions of what user SEES in each view
    2. Relationship analysis between views
    3. Geometric and topological metrics for scientific context
    4. Request for synthesis
    """
    parts = [
        "You are explaining a spatial visualization of a knowledge base.",
        "Help the user navigate high-dimensional information through visual metaphor.",
        "",
        "## The Main Grid (19×19)",
        "",
        f"Cursor at position ({ctx.cursor_x}, {ctx.cursor_y}).",
    ]

    # Document info
    if ctx.document_title:
        parts.append(f'Document: "{ctx.document_title}"')
    else:
        parts.append("Empty cell - no document at this position.")

    parts.extend(["", "## Orthographic Views", ""])

    # Visual description of Embed view
    parts.append("### Embed View (semantic similarity)")
    embed_desc = _describe_embed_view(ctx.embed_grid)
    parts.append(embed_desc)
    parts.append("_Brightness indicates how semantically related nearby documents are._")
    parts.append("")

    # Visual description of Iso view
    parts.append("### Iso View (semantic terrain)")
    iso_desc = _describe_iso_view(ctx.iso_grid)
    parts.append(iso_desc)
    parts.append("_Elevation shows topic boundaries (high) vs cluster interiors (low)._")
    parts.append("")

    # Relationship between views
    relationship = _describe_view_relationship(ctx.embed_grid, ctx.iso_grid)
    if relationship:
        parts.extend([
            "## How the Views Relate",
            "",
            relationship,
            "",
        ])

    # Geometric context (metrics for scientific understanding)
    parts.append("## Geometric Context")
    if ctx.curvature is not None:
        κ = ctx.curvature
        if κ < -0.3:
            interp = "STRONG BOUNDARY"
        elif κ < 0:
            interp = "boundary"
        elif κ > 0.3:
            interp = "STRONG INTERIOR"
        elif κ > 0:
            interp = "interior"
        else:
            interp = "flat"
        parts.append(f"- Ricci curvature: κ = {κ:.3f} ({interp})")
    else:
        parts.append("- Ricci curvature: N/A")

    if ctx.gradient_x is not None and ctx.gradient_y is not None:
        import math
        mag = math.sqrt(ctx.gradient_x**2 + ctx.gradient_y**2)
        parts.append(f"- Gradient: ({ctx.gradient_x:.3f}, {ctx.gradient_y:.3f}) magnitude {mag:.3f}")
    else:
        parts.append("- Gradient: N/A")

    if ctx.risk_score is not None:
        if ctx.risk_score > 0.7:
            stability = "critical bridge"
        elif ctx.risk_score > 0.4:
            stability = "connection point"
        else:
            stability = "stable"
        parts.append(f"- Risk score: {ctx.risk_score:.3f} ({stability})")
    else:
        parts.append("- Risk score: N/A")
    parts.append("")

    # Topological context
    parts.append("## Topological Context")
    parts.append(f"- H0: {ctx.h0_count or 0} components | H1: {ctx.h1_count or 0} cycles | H2: {ctx.h2_count or 0} voids")
    if ctx.tda_entropy is not None:
        parts.append(f"- Entropy: {ctx.tda_entropy:.3f}")
    parts.append(f"- Coverage: {ctx.grid_coverage:.1%} of grid ({ctx.total_documents} documents)")
    parts.append("")

    # Nearby documents
    if ctx.nearby_documents:
        parts.append("## Nearby Documents")
        for doc in ctx.nearby_documents[:5]:
            parts.append(f"- {doc}")
        parts.append("")

    # Request
    parts.extend([
        "---",
        "",
        "In 2-3 sentences, explain what the visual patterns reveal:",
        "1. What kind of territory is this (cluster core, boundary, transition zone)?",
        "2. What do the view relationships tell us about this location's significance?",
        "3. What might navigating in different directions discover?",
        "",
        "Use visual, spatial language. Describe what is SEEN, connecting it to the metrics.",
    ])

    return "\n".join(parts)


def _fallback_explanation(ctx: ExplanationContext) -> str:
    """Fallback explanation when LLM is unavailable."""
    parts = [f"Position ({ctx.cursor_x}, {ctx.cursor_y})"]

    if ctx.document_title:
        parts.append(f" - {ctx.document_title}")
    else:
        parts.append(" - Empty cell")

    if ctx.curvature is not None:
        κ = ctx.curvature
        if abs(κ) > 0.3:
            parts.append(
                f" | Curvature κ={κ:.3f} ({'boundary' if κ < 0 else 'interior'}, high magnitude)"
            )
        elif abs(κ) > 0.05:
            parts.append(
                f" | Curvature κ={κ:.3f} ({'boundary' if κ < 0 else 'interior'})"
            )
        else:
            parts.append(f" | Curvature κ≈0 (flat)")

    if ctx.risk_score is not None and ctx.risk_score > 0.5:
        parts.append(f" | Risk={ctx.risk_score:.2f} (topological bridge)")

    return "".join(parts)


def query_local_llm(
    prompt: str,
    max_tokens: int = 200,
    temperature: float = 0.7,
    technique: OptillmTechnique | str | None = None,
) -> str:
    """Simple synchronous wrapper for querying the local LLM.

    This is a convenience function for simple queries. For async code
    or more control, use InferenceClient directly.

    Args:
        prompt: User prompt
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature
        technique: optillm technique (cot_reflection, bon, moa, etc.)

    Returns:
        LLM response as string

    Raises:
        RuntimeError: If LLM is unavailable or request fails
    """
    import asyncio

    async def _async_query():
        try:
            client = InferenceClient()
            result = await client.complete(
                messages=[Message(role="user", content=prompt)],
                technique=technique,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return result.content

        except Exception as e:
            raise RuntimeError(f"LLM query failed: {e}") from e

    # Run async function in sync context
    try:
        return asyncio.run(_async_query())
    except RuntimeError as e:
        # If already in event loop, raise with helpful message
        if "already running" in str(e):
            raise RuntimeError(
                "Cannot use query_local_llm() from async context. "
                "Use InferenceClient.complete() directly instead."
            ) from e
        raise
