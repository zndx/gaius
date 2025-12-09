# Embeddings & Point Clouds

## What Are Embeddings?

Embeddings are learned vector representations that encode semantic relationships as geometric relationships. Two items that are "similar" in meaning have embedding vectors that are "close" in space.

```
"pension fund"     → [0.23, -0.41, 0.88, ...]  (1536 dims)
"retirement plan"  → [0.25, -0.39, 0.86, ...]  (nearby)
"pizza recipe"     → [-0.67, 0.12, -0.33, ...] (distant)
```

Modern embedding models (text-embedding-3-small, etc.) produce vectors where:
- **Cosine similarity** measures semantic relatedness
- **Euclidean distance** measures conceptual separation
- **Clusters** emerge naturally from semantic categories

## Point Clouds in Gaius

When multiple embeddings are collected—agent utterances, domain entities, document fragments—they form a **point cloud** in embedding space.

```python
# Each agent utterance becomes a point
cloud = []
for agent in swarm:
    response = await agent.analyze(task)
    embedding = embedder.embed(response)
    cloud.append(embedding)

# Cloud shape: (n_utterances, embedding_dim)
```

This point cloud is the raw material for both:
1. **Grid projection** (what you see)
2. **Topological analysis** (what the math reveals)

## Projection Methods

High-dimensional clouds must be compressed for visualization. Common methods:

### PCA (Principal Component Analysis)
Finds the axes of maximum variance. Fast, deterministic, but linear—may miss curved structure.

```python
from sklearn.decomposition import PCA
pca = PCA(n_components=2)
projected = pca.fit_transform(cloud)
```

### UMAP (Uniform Manifold Approximation)
Preserves local neighborhood structure. Better for clusters, but non-deterministic.

### Custom Projections
Domain-specific projections can encode prior knowledge. For pension analysis:
- X-axis: Risk (low → high)
- Y-axis: Time horizon (short → long)

## Mapping to the Grid

Once projected to 2D, coordinates are scaled to [0, 18] and discretized:

```python
# Normalize to [0, 1]
x_norm = (projected[:, 0] - projected[:, 0].min()) / (projected[:, 0].ptp() + 1e-8)
y_norm = (projected[:, 1] - projected[:, 1].min()) / (projected[:, 1].ptp() + 1e-8)

# Scale to grid
x_grid = np.clip((x_norm * 18).astype(int), 0, 18)
y_grid = np.clip((y_norm * 18).astype(int), 0, 18)
```

Multiple points may map to the same grid cell. This is handled by:
- **Latest-wins**: Most recent point displayed
- **Color mixing**: Combined representation
- **Intensity**: Brighter = more points

## Semantic Distance on the Grid

Grid distance roughly corresponds to semantic distance—but the projection is lossy. Two points adjacent on the grid are likely related; two points distant are likely unrelated. But edge cases exist.

The grid offers **intuition**, not **precision**. For exact similarity queries, consult the underlying embeddings directly.

## Temporal Dynamics

As new data arrives (agent responses, user queries, domain events), the point cloud evolves:

```
t=0: Initial cloud from seed data
t=1: + First swarm round utterances
t=2: + User query embeddings
t=3: + Second swarm round...
```

The grid animates this evolution. Watch clusters form, dissolve, migrate. These dynamics reveal how understanding develops over time.

## Vector Memory Integration

All embeddings are stored in the Vector Memory system, enabling:

- **Retrieval**: "Find utterances similar to X"
- **Scene graphs**: Build edges from cosine similarity
- **History**: Track the trajectory of specific agents/entities

See [Vector Memory](../architecture/memory.md) for implementation details.
