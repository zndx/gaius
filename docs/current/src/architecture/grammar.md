# Grammar Engine

The grammar engine implements a CFDG-inspired recursive expansion system that generates unique 3D scenes from card topology features. It lives in `gaius.viz.grammar` and produces a flat list of positioned shapes that the [LuxCore renderer](./luxcore.md) assembles into spectral glass scenes.

## Mathematical Grounding

The grammar's inputs are not aesthetic parameters — they are computed from the intrinsic geometry and topology of the collection's embedding manifold:

- **Ollivier-Ricci curvature** (κ) on the k-NN graph over 768-dim Nomic embeddings: `κ(x,y) = 1 - W₁(μₓ, μᵧ) / d(x,y)`, where W₁ is the 1-Wasserstein distance between neighborhood distributions (GraphRicciCurvature, k=15, alpha=0.5)
- **Persistent homology** via Vietoris-Rips filtration (ripser, cosine distance): Betti numbers b₀, b₁, b₂ and persistence diagrams
- **Complexity**: mean cosine distance to k-nearest neighbors, normalized across the collection
- **Gradient fields**: ∇κ on the embedding manifold, projected to 2D via PCA — positions the key light along the direction of steepest semantic change

## Design Principles

From Context Free Design Grammars (Horigan, 2004), the engine borrows three key ideas:

1. **Weighted rule alternatives** — at each expansion step, the grammar chooses among productions with probabilities derived from the card's feature vector. This is what makes different cards produce different structures.

2. **Recursive expansion with transform accumulation** — each production can invoke sub-rules with a child transform (translation, rotation, scale) relative to the parent. Transforms compose multiplicatively, producing self-similar structures at decreasing scales.

3. **Termination by minimum scale** — expansion stops when accumulated scale drops below `MIN_SCALE` (0.08) or when the shape budget (`MAX_SHAPES` = 35) is exhausted.

## Deterministic Seeding

Every card produces the same visualization regardless of when or where it is rendered:

```python
seed = int(hashlib.sha256(card_id.encode()).hexdigest(), 16) % (2**32)
rng = random.Random(seed)
```

## Feature-to-Rule Mapping

Card topology features control rule weights and recursion depth:

| Feature | Grammar Effect |
|---------|---------------|
| curvature (κ) | Petal count, recurse-vs-stop weight, dome factor, glass color temperature |
| persistence | Max depth (3-7), shell nesting weight, spiral count |
| complexity | Branch-vs-grow weight, surface segments, tube radius |
| boundary (∇·∇κ) | Emission strength, volume absorption density, core radius |
| b₁ (1-cycles) | Number of toroidal glass rings (0-3) |
| b₂ (2-cycles) | Number of void chambers (0-2) — inverted-normal spheres |
| diagram | Filament count, scale (encodes persistence interval lifetime), z-position (encodes birth value) |
| card_index | Phase offset for rotational variety within a collection |

## Shape Primitives

Six mesh types, all implemented as arbitrary meshes in `meshgen.py` (pure numpy vertex/face arrays, not geometric primitives):

| Shape | Mesh Generator | Driven By |
|-------|---------------|-----------|
| Petals | `petal_disk()` — flower-like segments | κ (count), arrangement mode |
| Shells | `ico_sphere()` — nested recursive enclosures | persistence (nesting depth) |
| Tori | `torus()` — glass rings | b₁ (1-cycles in persistent homology) |
| Voids | `ico_sphere()` with inverted normals | b₂ (2-cycles, cavities) |
| Filaments | `cylinder()` — thin structures | persistence diagram intervals |
| Core | `ico_sphere()` — central anchor | boundary (divergence magnitude) |

## Arrangement Modes

The root-level grammar selects one of three arrangement modes probabilistically based on curvature and complexity:

- **Cluster** — radial arrangement around a center point
- **Spiral** — logarithmic spiral placement
- **Branches** — tree-like recursive branching

## Extensibility

Adding a new shape primitive requires three changes:

1. A mesh generator function in `meshgen.py`: `(parameters) -> (vertices, faces)`
2. A shape constant in `grammar.py`
3. A renderer case in `luxcore_renderer.py`

The grammar and renderer are agnostic to the geometry they receive — any mesh generator that returns numpy vertex and face arrays works. This separation means the grammar architecture is fixed while the visual vocabulary grows.
