"""Card visualization pipeline: procedural glass structures from topology.

Generates unique glass-plasma images per card driven by differential geometry
(Ollivier-Ricci curvature, persistence homology, gradient fields) computed
on collection embedding manifolds.

Two render paths:
  1. Blender: subprocess with Cycles (legacy)
  2. LuxCore: direct pyluxcore API (preferred -- true spectral glass)

Architecture:
    Card -> Qdrant embeddings -> GeometryComputer + TDAComputer
      -> CardVizData -> grammar engine -> mesh generation
      -> Blender subprocess OR LuxCore direct -> PNG
      -> Upload to R2 -> Update card.image_url -> KV sync

Usage:
    from gaius.viz import render_card_luxcore_async, render_batch

    # Single card via LuxCore
    png_path = await render_card_luxcore_async(viz_data)

    # Batch via Blender (legacy)
    paths = await render_batch(cards, concurrency=4)
"""

from .data import CardVizData, extract_card_viz_data
from .grammar import (
    CORE,
    FILAMENT,
    PETAL,
    SHELL,
    TORUS,
    VOID,
    expand_grammar,
)
from .renderer import (
    CARD_VARIANTS,
    render_batch,
    render_card,
    render_card_luxcore_async,
    render_card_variants,
    render_card_variants_luxcore,
)
from .storage import upload_card_variants, upload_to_r2, upload_variant_to_r2

__all__ = [
    "CARD_VARIANTS",
    "CORE",
    "CardVizData",
    "FILAMENT",
    "PETAL",
    "SHELL",
    "TORUS",
    "VOID",
    "expand_grammar",
    "extract_card_viz_data",
    "render_batch",
    "render_card",
    "render_card_luxcore_async",
    "render_card_variants",
    "render_card_variants_luxcore",
    "upload_card_variants",
    "upload_to_r2",
    "upload_variant_to_r2",
]
