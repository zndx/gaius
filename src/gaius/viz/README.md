# Procedural Visualization Engine

The `gaius.viz` package generates unique card images by applying a
CFDG-inspired recursive grammar to mathematical features extracted from
collection embedding manifolds. Each card's visualization is deterministic
and grounded in the differential geometry and algebraic topology of its
semantic neighborhood.

## Architecture

```
  Nomic embeddings (768-dim)
          │
          ▼
  ┌─────────────────┐
  │ GeometryComputer │  Ollivier-Ricci curvature, gradient fields,
  │ (core/geometry)  │  divergence on k-NN graph
  └────────┬────────┘
           │
           │   ┌──────────────┐
           ├──►│ TDAComputer  │  Persistent homology via ripser:
           │   │ (core/tda)   │  Betti numbers, persistence diagrams
           │   └──────┬───────┘
           │          │
           ▼          ▼
  ┌──────────────────────────┐
  │      CardVizData         │  Normalized feature vector per card:
  │      (data.py)           │  κ, π, complexity, boundary, b0-b2,
  │                          │  gradient direction, persistence diagram
  └────────────┬─────────────┘
               │
               ▼
  ┌──────────────────────────┐
  │    expand_grammar()      │  CFDG-inspired recursive expansion:
  │    (grammar.py)          │  weighted rules, seeded RNG, transform
  │                          │  accumulation → flat shape list
  └────────────┬─────────────┘
               │
               ▼
  ┌──────────────────────────┐
  │    meshgen.py            │  Pure numpy mesh generators:
  │                          │  ico_sphere, petal_disk, torus, cylinder
  │                          │  + Euler rotation, vertex normals
  └────────────┬─────────────┘
               │
               ▼
  ┌──────────────────────────┐
  │  luxcore_renderer.py     │  LuxCore PATHOCL (GPU) or PATHCPU:
  │                          │  spectral glass, volume absorption,
  │                          │  physically-based caustics
  └────────────┬─────────────┘
               │
               ▼
  ┌──────────────────────────┐
  │     storage.py           │  R2 upload, DB image_url update,
  │                          │  KV sync for live card pages
  └──────────────────────────┘
```

## Mathematical Grounding

The visualization features are not arbitrary aesthetic parameters. They are
derived from the intrinsic geometry and topology of the collection's
embedding space, treating the set of card embeddings as a discrete sample
from a Riemannian manifold.

### Ollivier-Ricci Curvature

For each card, we compute the Ollivier-Ricci curvature on the k-nearest
neighbor graph constructed over 768-dimensional Nomic embeddings.

Given two adjacent nodes x and y in the k-NN graph, the Ollivier-Ricci
curvature is:

    κ(x, y) = 1 - W₁(μₓ, μᵧ) / d(x, y)

where W₁ is the 1-Wasserstein (earth mover's) distance between the
neighborhood distributions μₓ and μᵧ, and d(x, y) is the cosine distance
between embeddings. The per-node curvature averages over incident edges.

**Geometric interpretation**: Positive curvature (κ > 0) indicates the
neighborhoods of adjacent nodes overlap substantially — the card sits in
the interior of a semantic cluster. Negative curvature (κ < 0) indicates
neighborhoods diverge — the card lies at a semantic boundary where topics
transition. This is the discrete analogue of sectional curvature on smooth
manifolds, where geodesic balls grow faster than Euclidean in negatively
curved regions.

**Visual mapping**: Curvature controls the glass color temperature
(warm white at low κ, cool blue at high κ), the petal count in cluster
arrangements, and the IOR of the glass material. Cards at semantic
boundaries produce cooler, more complex structures; cards deep in a cluster
produce warmer, simpler forms.

### Persistent Homology

We run the Vietoris-Rips filtration (via ripser) on the cosine distance
matrix of the collection embeddings, computing persistent homology in
dimensions 0, 1, and 2.

- **H₀** (connected components): How the collection fragments into
  clusters at different distance thresholds. The Betti number b₀ counts
  distinct topological components.

- **H₁** (loops): 1-cycles that persist across a range of filtration
  values indicate circular or cyclic structure in the embedding space —
  topics that loop back on themselves rather than forming trees.

- **H₂** (voids): 2-cycles that enclose empty regions — higher-order
  cavities in the embedding space where no cards exist despite being
  topologically surrounded.

The persistence diagram records (birth, death) pairs for each feature.
Long-lived features (high persistence = death − birth) represent genuine
topological structure; short-lived features are noise.

**Visual mapping**: Total persistence (normalized via tanh) controls
recursion depth — topologically richer collections produce deeper nesting.
b₁ generates toroidal glass rings. b₂ generates inverted-normal void
spheres. Individual persistence intervals spawn filament structures whose
scale encodes the interval's lifetime and whose position encodes its birth
value.

### Gradient Fields and Divergence

The gradient field ∇κ is computed on the embedding manifold by finite
difference over the k-NN graph, then projected to 2D via PCA. The
divergence ∇·(∇κ) identifies sources (positive divergence — emanating
semantic flow) and sinks (negative divergence — converging topics).

**Visual mapping**: The gradient direction positions the key light source,
so the illumination axis aligns with the direction of steepest semantic
change. Divergence magnitude, normalized per card, controls the glass
boundary emission and volume absorption density — cards at divergence
extrema glow more intensely at their edges.

### Complexity (Risk Score)

Per-card complexity is derived from local topological instability: the
average cosine distance to k-nearest neighbors, normalized across the
collection. Cards with distant neighbors are topologically isolated —
they occupy sparse regions of the embedding manifold where small
perturbations change the local topology.

**Visual mapping**: Complexity controls surface subdivision (polygon count
per mesh), branching probability in the grammar, and the tube radius of
toroidal structures. Isolated cards produce finer, more intricate geometry.


## The Grammar Engine

`grammar.py` implements a CFDG-inspired recursive expansion system. From
Context Free Design Grammars (Horigan, 2004) it borrows:

- **Weighted rule alternatives**: At each expansion step, the grammar
  chooses among alternative productions with probabilities derived from
  the card's feature vector. This is the core mechanism that makes
  different cards produce different structures.

- **Recursive expansion with transform accumulation**: Each production
  can invoke sub-rules with a child transform (translation, rotation,
  scale) relative to the parent. Transforms compose multiplicatively,
  producing self-similar structures at decreasing scales.

- **Termination by minimum scale**: Expansion stops when accumulated
  scale drops below MIN_SCALE (0.08) or when the shape budget (MAX_SHAPES
  = 35) is exhausted. This prevents unbounded recursion while allowing
  deep nesting when the feature vector warrants it.

- **Deterministic seeding**: `sha256(card_id)` seeds the RNG, ensuring
  the same card always produces the same visualization regardless of when
  or where it is rendered.

The grammar currently defines three arrangement modes at the root level
(cluster, spiral, branches) with six shape primitives (petal, shell,
torus, void, filament, core). Feature-to-weight mappings:

| Feature     | Grammar effect                                      |
|-------------|-----------------------------------------------------|
| curvature   | Petal count, recurse-vs-stop weight, dome factor    |
| persistence | Max depth (3-7), shell nesting weight, spiral count |
| complexity  | Branch-vs-grow weight, surface segments             |
| boundary    | Emission strength, volume density, core radius      |
| b₁          | Number of toroidal rings (0-3)                      |
| b₂          | Number of void chambers (0-2)                       |
| diagram     | Filament count, scale, and z-position               |
| card_index  | Phase offset for rotational variety in collection   |

### Current Limitations and Future Directions

**Grammar DSL**. The grammar is currently expressed as Python functions
with hardcoded rule structures. A text-based grammar format — closer to
CFDG's declarative syntax — would allow grammar definitions to be version-
controlled, diffed, and iterated without touching Python code. A `.cfdg`
or HOCON-based format with named rules, weighted alternatives, and
transform operators is the natural next step. The goal is one grammar file
per Gaius deployment, providing visual coherence across all collections
while still allowing the mathematical features to drive per-card variation.

**Rule vocabulary**. Six primitives (petal, shell, torus, void, filament,
core) produce recognizable variety but the space of possible structures is
constrained. Extending meshgen.py with lathe surfaces (profiles of
revolution), swept curves (extrude along spline), and L-system branching
structures would dramatically expand the visual vocabulary without changing
the grammar architecture. Each new mesh generator is a pure function
`(parameters) → (vertices, faces)` — the grammar and renderer are
agnostic to what geometry they receive.

**Shape vocabulary extensibility**. The mesh generation layer (`meshgen.py`)
is deliberately separated from both the grammar and the renderer. New
primitives only need to produce numpy vertex and face arrays. The grammar
references them by string constant, and the renderer maps them to LuxCore
inlinedmesh definitions. Adding a new shape is three changes: a meshgen
function, a grammar constant, and a renderer case.

**Interactive preview**. The pipeline currently runs headless — there is
no way to see intermediate states or explore parameter sensitivity. A
preview mode that renders at low sample count (8-16 spp, ~1s on GPU) and
displays the grammar's shape list alongside the mathematical features
would close the feedback loop between topology and visual output. This
would be valuable both for grammar development and for understanding what
the differential geometry features mean visually for a given card.


## Render Backend

The renderer uses LuxCore's unbiased path tracer via the pyluxcore Python
API. The from-source build at `thirdparty/installed/LuxCore/pyluxcore/`
provides CUDA support; the PyPI wheel (CPU-only) serves as fallback.

- **PATHOCL**: GPU-accelerated path tracing on CUDA devices. Hybrid mode
  automatically uses both GPU intersection and 64 CPU native threads.
  Single-GPU targeting via `gpu_id` parameter for orchestrator-managed
  eviction of vLLM endpoints.

- **PATHCPU**: 64-thread CPU rendering when no CUDA devices are available.
  Approximately 10x slower than single-GPU PATHOCL for equivalent sample
  counts.

- **Materials**: Spectral glass with homogeneous volume absorption
  (the defining visual element). LuxCore's spectral rendering produces
  physically accurate caustics and internal reflections that Blender
  Cycles could not achieve — recursive glass nesting in Cycles produced
  opaque white blobs rather than transparent refraction.

- **Halt conditions**: Configurable by time (seconds) and sample count
  (samples per pixel). Production renders use 60s/512spp; the curation
  pipeline uses 20s/128spp for throughput.


## File Index

| File                  | Purpose                                         |
|-----------------------|-------------------------------------------------|
| `data.py`             | CardVizData extraction from embedding geometry   |
| `grammar.py`          | CFDG-inspired recursive shape grammar            |
| `meshgen.py`          | Pure numpy mesh generators + transforms          |
| `luxcore_renderer.py` | LuxCore scene assembly, materials, rendering     |
| `renderer.py`         | Async wrappers, variant management, thread pool  |
| `storage.py`          | R2 upload, DB updates, KV sync                   |
| `scripts/`            | Legacy Blender-based rendering (superseded)      |
| `templates/`          | Blender template files (legacy)                  |
