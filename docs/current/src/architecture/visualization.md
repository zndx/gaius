# Visualization

The visualization pipeline generates unique procedural images for collection cards using LuxCore path tracing. Each card's image is deterministic — derived from the differential geometry and algebraic topology of its embedding neighborhood.

## Pipeline

```
Nomic Embeddings (768-dim)
    |
    ├──> GeometryComputer (Ollivier-Ricci curvature, gradient fields)
    └──> TDAComputer (persistent homology via ripser)
            |
            v
        CardVizData (normalized feature vector per card)
            |
            v
        Grammar Engine (CFDG-inspired recursive expansion)
            |
            v
        MeshGen (pure numpy mesh generators)
            |
            v
        LuxCore Renderer (PATHOCL GPU / PATHCPU fallback)
            |
            v
        R2 Storage (viz.gaius.zndx.org)
```

## Mathematical Grounding

Visualizations are driven by intrinsic geometric properties of the embedding space, not arbitrary aesthetic choices:

- **Ollivier-Ricci curvature** controls glass color temperature and petal count. Positive curvature (cluster interior) produces warmer, simpler forms. Negative curvature (semantic boundary) produces cooler, complex structures.
- **Persistent homology** (H0, H1, H2) controls recursion depth, toroidal rings, and void chambers. Topologically richer collections produce deeper nesting.
- **Gradient fields** position the key light along the direction of steepest semantic change. Divergence magnitude controls glass boundary emission and volume absorption density.
- **Complexity** (local topological isolation — average cosine distance to k-nearest neighbors) controls surface subdivision and branching probability.

## Grammar Engine

`grammar.py` implements a CFDG-inspired recursive expansion system (Horigan, 2004). The core mechanism: at each expansion step, the grammar chooses among alternative productions with probabilities derived from the card's feature vector. Transforms compose multiplicatively, producing self-similar structures at decreasing scales.

**Deterministic seeding**: `sha256(card_id)` seeds the RNG, so the same card always produces the same visualization regardless of when or where it is rendered.

**Termination**: Expansion stops when accumulated scale drops below `MIN_SCALE` (0.08) or the shape budget (`MAX_SHAPES` = 35) is exhausted.

**Feature-to-weight mappings**:

| Feature | Grammar Effect |
|---------|---------------|
| curvature | Petal count, recurse-vs-stop weight, dome factor |
| persistence | Max depth (3–7), shell nesting weight, spiral count |
| complexity | Branch-vs-grow weight, surface segments |
| boundary | Emission strength, volume density, core radius |
| b1 | Number of toroidal rings (0–3) |
| b2 | Number of void chambers (0–2) |
| diagram | Filament count, scale, and z-position from persistence intervals |
| card_index | Phase offset for rotational variety within a collection |

Three root arrangement modes (cluster, spiral, branches) combine with six shape primitives (petal, shell, torus, void, filament, core).

## Mesh Generators

`meshgen.py` provides pure numpy mesh generators — each is a function `(parameters) → (vertices, faces, normals)`:

| Generator | Geometry | Parameters |
|-----------|----------|------------|
| `ico_sphere` | Subdivided icosahedron | radius, subdivisions |
| `petal_disk` | Radially-modulated disk | radius, petal_count, amplitude |
| `torus` | Standard torus | major_radius, minor_radius, segments |
| `cylinder` | Open cylinder | radius, height, segments |

All generators produce vertex normals for smooth shading. Euler rotation and uniform scaling are applied per-shape by the grammar's accumulated transform.

## Render Backend

LuxCore's unbiased path tracer via the pyluxcore Python API. The from-source build (`thirdparty/installed/LuxCore/pyluxcore/`) provides CUDA support; the PyPI wheel (CPU-only) serves as fallback.

- **PATHOCL** — GPU-accelerated path tracing on CUDA devices. Hybrid mode automatically uses both GPU intersection and 64 CPU native threads. Single-GPU targeting via `gpu_id` for orchestrator-managed eviction of vLLM endpoints.
- **PATHCPU** — 64-thread CPU rendering when no CUDA devices are available. ~10x slower than single-GPU PATHOCL.
- **Materials** — Spectral glass with homogeneous volume absorption. LuxCore's spectral rendering produces physically accurate caustics and internal reflections. This was the motivation for switching from Blender Cycles, which rendered recursive glass nesting as opaque white blobs.
- **Halt conditions** — Production: 60s / 512 samples per pixel. Curation pipeline: 20s / 128 spp for throughput.

## Render Variants

| Variant | Dimensions | Purpose |
|---------|-----------|---------|
| `display` | 1400x300 | Card header image on site |
| `og` | 1200x630 | OpenGraph social sharing |

## gRPC Integration

Rendering is triggered via the `/render` CLI command, which invokes the `RenderCards` streaming RPC. The render workload sets `allow_baseline_eviction=True` to temporarily free a GPU from vLLM inference. After rendering completes, `clear_embeddings()` releases the Nomic model (~3GB) from GPU memory.

## Components

| Module | Purpose |
|--------|---------|
| `data.py` | Feature extraction from embedding geometry |
| `grammar.py` | [Grammar Engine](./grammar.md) — recursive shape expansion |
| `meshgen.py` | Pure numpy mesh generators (ico_sphere, petal, torus) |
| `luxcore_renderer.py` | [LuxCore Renderer](./luxcore.md) — scene assembly and rendering |
| `renderer.py` | Async wrappers, variant management, thread pool |
| `storage.py` | [R2 upload](./viz-storage.md), DB updates, KV sync |
