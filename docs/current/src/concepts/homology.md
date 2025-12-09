# Persistent Homology

## Beyond Statistics

Statistics describes the *distribution* of data: mean, variance, correlations. But distributions are blind to *shape*.

Consider two point clouds:

```
Cloud A:          Cloud B:
  ● ●               ●   ●
 ●   ●             ●     ●
●     ●            ●     ●
 ●   ●             ●     ●
  ● ●               ●   ●
```

Same mean. Same variance. Same point count. But Cloud A is a filled disk; Cloud B is a ring with a hole. The hole is *topologically* significant—it represents something absent, something that might matter.

Persistent homology is the mathematics of detecting such shapes.

## The Vietoris-Rips Complex

Given a point cloud, we construct a **simplicial complex** by connecting points within a distance threshold ε:

```
ε = small:     ε = medium:     ε = large:
  ●   ●         ●───●           ●───●
                    │           │╲ ╱│
  ●   ●         ●   ●           ●─╳─●
                                │╱ ╲│
  ●   ●         ●───●           ●───●
```

As ε increases:
- **H0 features** (connected components): Merge as clusters connect
- **H1 features** (loops): Appear when edges close cycles, disappear when interiors fill
- **H2 features** (voids): Appear when surfaces enclose volumes

## Birth and Death

Each topological feature has a **birth** time (the ε at which it appears) and a **death** time (the ε at which it vanishes).

Features that persist across a wide range of ε are considered *significant*—they reflect genuine structure rather than noise.

```
Persistence Diagram:
        death
          │
          │    ● (noise: short-lived)
          │
          │          ● (signal: long-lived)
          │        ●
          │      ●
          └──────────── birth
```

Points far from the diagonal represent persistent features.

## Death Loops (H1)

In Gaius, **H1 features** receive special attention as "death loops." These represent:

- **Cycles in data flow**: Feedback loops, circular dependencies
- **Systemic risks**: Self-reinforcing failure modes
- **Market structures**: Liquidity cycles, regulatory arbitrage loops

When projected onto the grid, death loops appear as `⚠` markers in regions where the underlying embedding space exhibits persistent 1-dimensional holes.

## Practical Application

```python
from gtda.homology import VietorisRipsPersistence
from gtda.diagrams import PersistenceEntropy

# Compute persistence diagrams
vr = VietorisRipsPersistence(homology_dimensions=[0, 1, 2])
diagrams = vr.fit_transform([point_cloud])

# Quantify topological complexity
entropy = PersistenceEntropy()
ent = entropy.fit_transform(diagrams)

# Extract significant H1 features
h1_features = diagrams[0][diagrams[0][:, 0] == 1]
persistent_loops = h1_features[h1_features[:, 2] - h1_features[:, 1] > threshold]
```

## Entropy as Summary

**Persistence entropy** provides a scalar summary of topological complexity:

- **Low entropy**: Few dominant features (simple structure)
- **High entropy**: Many features of similar persistence (complex, fractal-like)

Gaius tracks entropy over time. Sudden entropy spikes may indicate regime changes in your domain.

## Interpreting Grid Overlays

When viewing the H1 overlay:

| Pattern | Interpretation |
|---------|----------------|
| Sparse `⚠` | Few persistent loops; structure is tree-like |
| Clustered `⚠` | Localized cyclic structure; investigate region |
| Uniform `⚠` | Pervasive cyclicity; may indicate noise or genuine complexity |
| Ring of `⚠` | Boundary of a significant void |

## Limitations

Persistent homology reveals shape but not causation. A detected loop could represent:
- A real feedback cycle in your domain
- An artifact of the embedding model
- Noise in the underlying data

Domain expertise is required to interpret topological features. Gaius surfaces the structure; you provide the meaning.

## Further Reading

- *Computational Topology* by Edelsbrunner and Harer
- *Topological Data Analysis* by Carlsson
- giotto-tda documentation: [giotto-ai.github.io](https://giotto-ai.github.io/gtda-docs/)
