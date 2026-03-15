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

Same mean. Same variance. Same point count. But Cloud A is a filled disk; Cloud B is a ring with a hole. The hole is *topologically* significant — it represents something absent, something that might matter.

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

Features that persist across a wide range of ε are considered *significant* — they reflect genuine structure rather than noise.

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

## Gaius Implementation

The `TDAComputer` (`core/tda.py`) computes persistent homology via ripser on the cosine distance matrix of Nomic 768-dimensional embeddings:

```python
computer = TDAComputer(max_dimension=2, method="rips")
features = computer.compute(embeddings, grid_coords)
```

**Key parameters:**
- Distance metric: cosine (on the original 768-dim embeddings, not projected coordinates)
- Max dimension: 2 (H0, H1, H2)
- Significance threshold: persistence > 0.1 (a heuristic separating signal from noise)
- Subsampling: random sample when point count exceeds `config.tda.max_points` (ripser is O(n³) worst case)

The output `TDAFeatures` contains raw `PersistenceInterval` objects (birth, death, dimension, representative indices) plus grid-projected `BoundingBox` regions for visualization overlays.

## How Gaius Uses Each Dimension

**H0** (connected components): How the collection fragments into clusters at different distance thresholds. The Betti number b₀ counts distinct topological components. In the visualization pipeline, b₀ determines the number of disconnected shape groups.

**H1** (loops / "death loops"): 1-cycles that persist across a range of filtration values indicate circular or cyclic structure — topics that loop back on themselves. In the grid overlay, H1 features appear as `⚠` markers. In the visualization pipeline, b₁ generates toroidal glass rings (0-3 per card).

**H2** (voids): 2-cycles that enclose empty regions — higher-order cavities in the embedding space where no cards exist despite being topologically surrounded. In the visualization pipeline, b₂ generates inverted-normal void spheres (0-2 per card).

## From Topology to Visualization

The persistence diagram feeds directly into the grammar engine's feature-to-rule mapping:

| Topological Feature | Visual Encoding |
|---------------------|----------------|
| Total persistence (normalized via tanh) | Recursion depth (3-7 levels) |
| b₁ count | Toroidal glass ring count |
| b₂ count | Void chamber count |
| Individual persistence intervals | Filament structures — scale encodes lifetime, z-position encodes birth value |
| Persistence entropy | Used for temporal change detection (regime change signals) |

## Entropy as Summary

**Persistence entropy** provides a scalar summary of topological complexity:

- **Low entropy**: Few dominant features (simple structure)
- **High entropy**: Many features of similar persistence (complex, fractal-like)

Gaius tracks entropy over time. Sudden entropy spikes may indicate regime changes in the underlying domain.

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
- ripser documentation: [ripser.scikit-tda.org](https://ripser.scikit-tda.org/)
