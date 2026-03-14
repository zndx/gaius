"""Card visualization data extraction from embedding geometry.

Extracts mathematical features per card by computing differential geometry
(Ollivier-Ricci curvature, gradient fields) and persistent homology
(Betti numbers, persistence diagrams) on collection embedding spaces.

These features parameterize the procedural Blender scene:
  curvature  → glass IOR + amber↔blue color mix
  persistence → recursion depth / nesting levels
  complexity  → surface detail / subdivision
  boundary    → glass transparency / edge glow
  local_betti → toroidal loops (b1), void chambers (b2)
  gradient    → light position bias (warm→cool)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CardVizData:
    """Mathematical features for a single card's visualization.

    All float fields are normalized to [0, 1] for direct use as
    Blender custom property inputs.
    """

    card_id: str
    collection_id: str
    title: str

    # Differential geometry (from GeometryComputer)
    curvature: float = 0.5          # Ollivier-Ricci, normalized
    gradient_direction: tuple[float, float] = (0.0, 0.0)  # 2D unit vector

    # Topology (from TDAComputer / IsoFeatureComputer)
    persistence: float = 0.5        # Total persistence, normalized
    complexity: float = 0.5         # Token embedding variance, normalized
    boundary: float = 0.5           # H1 cocycle contribution, normalized

    # Local Betti numbers (from ripser on k-NN neighborhood)
    b0: int = 1                     # Connected components
    b1: int = 0                     # Toroidal loops
    b2: int = 0                     # Void chambers

    # Persistence diagram (for ring radii / nesting structure)
    persistence_diagram: list[list[float]] = field(default_factory=list)

    # Neighbor distances (for scale reference)
    mean_neighbor_distance: float = 0.0

    # Collection-level context
    collection_size: int = 0
    card_index: int = 0

    def to_json(self, path: Path) -> None:
        """Serialize to JSON file for Blender script consumption."""
        data = asdict(self)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def from_json(cls, path: Path) -> CardVizData:
        """Deserialize from JSON file."""
        with open(path) as f:
            data = json.load(f)
        # Convert gradient_direction from list back to tuple
        if isinstance(data.get("gradient_direction"), list):
            data["gradient_direction"] = tuple(data["gradient_direction"])
        return cls(**data)


def _normalize(values: np.ndarray) -> np.ndarray:
    """Normalize array to [0, 1] range."""
    if len(values) == 0:
        return values
    min_val = np.min(values)
    max_val = np.max(values)
    if max_val - min_val < 1e-10:
        return np.full_like(values, 0.5)
    return (values - min_val) / (max_val - min_val)


async def extract_card_viz_data(
    pool: Any,
    card_id: str,
    device: str | None = None,
) -> CardVizData:
    """Extract mathematical visualization features for a card.

    Pipeline:
    1. Look up card metadata from DB
    2. Embed card titles via Nomic model
    3. Compute geometry (curvature, gradients) via GeometryComputer
    4. Compute topology (Betti numbers, persistence) via TDAComputer
    5. Extract the card's index-specific values

    Args:
        pool: asyncpg connection pool
        card_id: Card ID to extract features for

    Returns:
        CardVizData with all fields populated

    Raises:
        RuntimeError: If card not found or embeddings unavailable
            (#VIZ.00000004.NOGEODATA)
    """
    # 1. Get card metadata
    row = await pool.fetchrow(
        """
        SELECT c.card_id, c.collection_id, c.title, c.kb_path,
               col.slug AS collection_slug
        FROM collections.cards c
        JOIN collections.collections col ON c.collection_id = col.collection_id
        WHERE c.card_id = $1
        """,
        card_id,
    )
    if not row:
        raise RuntimeError(
            f"Card {card_id} not found.\n"
            "  #VIZ.00000004.NOGEODATA\n"
            "  Check: SELECT card_id FROM collections.cards WHERE card_id = $1"
        )

    title = row["title"]
    collection_id = row["collection_id"]
    collection_slug = row["collection_slug"]

    # 2. Get all card kb_paths in same collection for embedding lookup
    sibling_rows = await pool.fetch(
        """
        SELECT card_id, title, kb_path
        FROM collections.cards
        WHERE collection_id = $1 AND status = 'published'
        ORDER BY sequence NULLS LAST, card_id
        """,
        collection_id,
    )

    if len(sibling_rows) < 3:
        raise RuntimeError(
            f"Collection {collection_slug} has fewer than 3 published cards "
            f"({len(sibling_rows)}). Need at least 3 for meaningful geometry.\n"
            "  #VIZ.00000004.NOGEODATA"
        )

    # 3. Retrieve embeddings by embedding summary text (or titles as fallback)
    embeddings, card_index = await _fetch_collection_embeddings(
        card_id=card_id,
        sibling_rows=sibling_rows,
        pool=pool,
        device=device,
    )

    if embeddings is None or len(embeddings) < 3:
        raise RuntimeError(
            f"Could not retrieve sufficient embeddings for collection {collection_slug}.\n"
            "  #VIZ.00000004.NOGEODATA\n"
            "  Try: uv run gaius-cli --cmd '/health fix qdrant'"
        )

    n = len(embeddings)
    logger.info(
        f"Computing viz features for card {card_id} "
        f"(index {card_index}/{n} in {collection_slug})"
    )

    # 4. Compute geometry
    from gaius.core.geometry import GeometryComputer

    geo = GeometryComputer(k_neighbors=min(15, n - 1))
    geo_features = await geo.compute_features(embeddings)

    # 5. Compute topology
    from gaius.core.tda import TDAComputer

    tda = TDAComputer(max_dimension=2)
    tda_features = tda.compute(embeddings)

    # 6. Compute iso features (normalized curvature, persistence, etc.)
    curvatures_norm = _normalize(geo_features.curvatures)
    risk_scores = np.array(tda_features.risk_scores) if tda_features.risk_scores else np.zeros(n)

    # Per-card values
    curvature_val = float(curvatures_norm[card_index])

    # Persistence: use total persistence normalized across collection
    interval_persistences = np.array(
        [iv.persistence for iv in tda_features.intervals]
    ) if tda_features.intervals else np.array([0.0])
    total_persistence = float(np.sum(interval_persistences))
    # Normalize to [0,1] using sigmoid-like scaling
    persistence_val = float(np.tanh(total_persistence / max(n, 1)))

    # Complexity from risk scores (local topological instability)
    complexity_val = float(risk_scores[card_index]) if card_index < len(risk_scores) else 0.5

    # Boundary from divergence (absolute value, normalized)
    div_norm = _normalize(np.abs(geo_features.divergence))
    boundary_val = float(div_norm[card_index])

    # Gradient direction (2D unit vector)
    grad = geo_features.gradients[card_index]
    grad_norm = np.linalg.norm(grad)
    if grad_norm > 1e-6:
        g = (grad / grad_norm).tolist()
        grad_unit = (float(g[0]), float(g[1]))
    else:
        grad_unit = (0.0, 1.0)

    # Local Betti numbers from TDA
    b0 = tda_features.h0_count
    b1 = tda_features.h1_count
    b2 = tda_features.h2_count

    # Persistence diagram (finite intervals only)
    diagram = [
        [float(iv.birth), float(iv.death)]
        for iv in tda_features.intervals
        if iv.persistence > 0.01
    ][:20]  # Cap at 20 intervals for Blender

    # Mean neighbor distance for scale
    from sklearn.neighbors import NearestNeighbors
    k_nn = min(5, n - 1)
    nn = NearestNeighbors(n_neighbors=k_nn + 1, metric="cosine")
    nn.fit(embeddings)
    dists, _ = nn.kneighbors(embeddings[card_index:card_index + 1])
    mean_dist = float(np.mean(dists[0, 1:]))

    return CardVizData(
        card_id=card_id,
        collection_id=collection_id,
        title=title,
        curvature=curvature_val,
        gradient_direction=grad_unit,
        persistence=persistence_val,
        complexity=complexity_val,
        boundary=boundary_val,
        b0=b0,
        b1=b1,
        b2=b2,
        persistence_diagram=diagram,
        mean_neighbor_distance=mean_dist,
        collection_size=n,
        card_index=card_index,
    )


async def _fetch_collection_embeddings(
    card_id: str,
    sibling_rows: list[Any],
    pool: Any,
    device: str | None = None,
) -> tuple[np.ndarray | None, int]:
    """Fetch embeddings for all cards in a collection.

    Strategy: embed open_weights summary text (2-3 paragraph local model
    summaries) for richer semantic geometry. Falls back to card titles
    when a card has no open_weights summary yet.

    The summary text produces much more differentiated 768-dim vectors
    than short titles, yielding richer curvature/topology/gradient fields.

    Args:
        card_id: Target card ID
        sibling_rows: All published cards in same collection
        pool: asyncpg connection pool for querying card_summaries

    Returns:
        (embeddings array of shape (n, dim), index of target card)
    """
    from gaius.models.embeddings import get_embeddings

    embedder = get_embeddings(device=device)

    card_ids = [r["card_id"] for r in sibling_rows]
    titles = [r["title"] for r in sibling_rows]

    # Find card index
    try:
        card_index = card_ids.index(card_id)
    except ValueError:
        logger.warning(f"Card {card_id} not in published siblings, using index 0")
        card_index = 0

    # Query open_weights summaries for richer embedding text
    summary_rows = await pool.fetch(
        """
        SELECT card_id, summary_text
        FROM collections.card_summaries
        WHERE card_id = ANY($1::text[]) AND summary_type = 'open_weights'
        """,
        card_ids,
    )
    summary_map = {r["card_id"]: r["summary_text"] for r in summary_rows}

    # Build texts: prefer summary, fall back to title
    texts = []
    summary_count = 0
    for cid, title in zip(card_ids, titles):
        summary = summary_map.get(cid)
        if summary:
            texts.append(summary)
            summary_count += 1
        else:
            texts.append(title)

    logger.info(
        f"Embedding {len(texts)} cards: {summary_count} from summaries, "
        f"{len(texts) - summary_count} from titles"
    )

    # Batch embed
    result = await embedder.embed_texts(texts)
    embeddings = result.vectors  # (n, 768)

    logger.info(
        f"Embedded {len(texts)} cards → {embeddings.shape} "
        f"(target card at index {card_index})"
    )

    return embeddings, card_index
