# Embeddings & Point Clouds

## What Are Embeddings?

Embeddings are learned vector representations that encode semantic relationships as geometric relationships. Two items that are "similar" in meaning have embedding vectors that are "close" in space.

```
"pension fund"     → [0.23, -0.41, 0.88, ...]  (768 dims)
"retirement plan"  → [0.25, -0.39, 0.86, ...]  (nearby)
"pizza recipe"     → [-0.67, 0.12, -0.33, ...] (distant)
```

Gaius uses Nomic embeddings (768 dimensions) stored in Qdrant for vector search. The `EmbeddingController` manages a dedicated GPU endpoint for real-time embedding generation.

## Point Clouds in Gaius

When multiple embeddings are collected — knowledge base documents, agent utterances, card content — they form a **point cloud** in 768-dimensional embedding space. This point cloud is the raw material for:

1. **Grid projection** — UMAP reduces 768 dimensions to 2D, then quantized to the 19x19 grid
2. **Topological analysis** — persistent homology on the cosine distance matrix reveals shape
3. **Curvature computation** — Ollivier-Ricci curvature on the k-NN graph reveals semantic boundaries
4. **Visualization** — topology features drive the grammar engine that generates card imagery

## Projection Pipeline

The `GridProjector` (`core/projection.py`) maps embeddings to grid positions:

```
768-dim Nomic embeddings (Qdrant)
    │
    ▼
UMAP (n_neighbors=15, min_dist=0.1, metric=cosine)
    │
    ▼
2D coordinates (continuous)
    │
    ▼
Quantize to [0, 18] integer grid
    │
    ▼
19x19 grid positions (GridPoint objects)
```

UMAP preserves local neighborhood structure — points that are close in 768-dim space remain close on the grid. The projection is necessarily lossy. This is a feature: it forces salience. Points that survive projection and remain distinct are points that matter.

### Multi-Vector Architecture

Gaius uses **ColBERT-Zero** (`lightonai/ColBERT-Zero`) for document retrieval: late-interaction MaxSim over 128-d token vectors. Contrastive pre-training is multi-vector from the start, on public Nomic-embed data (Apache 2.0). Aggregated mean vectors live in Qdrant's `"agg"` field for grid projection. Collection: `gaius_kb_colbert_zero` (not compatible with the retired ColNomic index). Vision/PDF is not this model — that is Qwen3.8-27B.

## Mapping to the Grid

Once projected to 2D, coordinates are normalized and discretized:

```python
# Normalize to [0, 1]
x_norm = (projected[:, 0] - projected[:, 0].min()) / (projected[:, 0].ptp() + 1e-8)
y_norm = (projected[:, 1] - projected[:, 1].min()) / (projected[:, 1].ptp() + 1e-8)

# Scale to grid
x_grid = np.clip((x_norm * 18).astype(int), 0, 18)
y_grid = np.clip((y_norm * 18).astype(int), 0, 18)
```

Multiple points may map to the same grid cell. Collision handling uses latest-wins for display, with density encoded in overlay modes.

## What Topology Sees That Statistics Misses

The same point cloud feeds three mathematical analyses:

| Analysis | What It Reveals | Source |
|----------|-----------------|--------|
| Persistent homology (ripser) | Clusters (H0), loops (H1), voids (H2) in the filtration | `core/tda.py` |
| Ollivier-Ricci curvature | Semantic boundaries (κ < 0) vs cluster interiors (κ > 0) | `core/geometry.py` |
| Gradient fields (∇κ) | Direction of steepest semantic change | `core/geometry.py` |

These analyses operate on the original 768-dimensional embeddings, not the projected 2D coordinates. The grid shows *where* features appear; the topology describes *what* features exist.

## Temporal Dynamics

As new data arrives (agent responses, KB entries, card publications), the point cloud evolves. The `NGRCPredictor` (reservoir computing via NVAR) tracks embedding centroid trajectories and predicts drift:

```
t=0: Initial cloud from seed data
t=1: + First cognition cycle thoughts
t=2: + Article curation cards
t=3: + Agent swarm responses
...
```

The grid animates this evolution. The ThetaAgent monitors drift urgency — when the knowledge base is changing faster than consolidation is linking it, urgency rises and triggers cross-temporal linking.

## Storage

All embeddings are stored in Qdrant with collection schemas that include domain, agent_id, session_id, and timestamp. This enables:

- **Semantic search**: "Find entries similar to X"
- **Temporal analysis**: Track how a domain's embedding distribution shifts over time
- **Agent collaboration**: LatentMAS uses Qdrant as shared working memory (768-dim dense or 20,480-dim CLT sparse)
