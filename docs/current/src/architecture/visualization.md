# Visualization

The visualization pipeline generates unique procedural images for collection cards using LuxCore path tracing. Each card's image is deterministic -- derived from the differential geometry and algebraic topology of its embedding neighborhood.

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

Visualizations are not arbitrary aesthetic choices. They are driven by intrinsic geometric properties of the embedding space:

- **Ollivier-Ricci curvature** controls glass color temperature and petal count. Positive curvature (cluster interior) produces warmer, simpler forms. Negative curvature (semantic boundary) produces cooler, complex structures.
- **Persistent homology** (H0, H1, H2) controls recursion depth, toroidal rings, and void chambers. Topologically richer collections produce deeper nesting.
- **Gradient fields** position the key light along the direction of steepest semantic change.
- **Complexity** (local topological isolation) controls surface subdivision and branching probability.

## Components

The pipeline spans four modules in `gaius.viz/`:

| Module | Purpose |
|--------|---------|
| `data.py` | Feature extraction from embedding geometry |
| `grammar.py` | [Grammar Engine](./grammar.md) -- recursive shape expansion |
| `meshgen.py` | Pure numpy mesh generators (ico_sphere, petal, torus) |
| `luxcore_renderer.py` | [LuxCore Renderer](./luxcore.md) -- scene assembly and rendering |
| `renderer.py` | Async wrappers, variant management, thread pool |
| `storage.py` | [R2 upload](./viz-storage.md), DB updates, KV sync |

## Render Variants

Each card is rendered in two variants:

| Variant | Dimensions | Purpose |
|---------|-----------|---------|
| `display` | 1400x300 | Card header image on site |
| `og` | 1200x630 | OpenGraph social sharing |

## gRPC Integration

Rendering is triggered via the `/render` CLI command, which invokes the `RenderCards` streaming RPC on the gRPC engine (port 50051). GPU eviction is coordinated with the vLLM controller:

```bash
# Render cards for a collection
uv run gaius-cli --cmd "/render collection-id"
```

The render workload sets `allow_baseline_eviction=True` to temporarily free a GPU from vLLM inference. After rendering completes, `clear_embeddings()` releases the Nomic model (~3GB) from GPU memory.

## Halt Conditions

Rendering quality is controlled by time and sample count:

- **Production**: 60 seconds / 512 samples per pixel
- **Curation pipeline**: 20 seconds / 128 samples per pixel (faster throughput)

## Materials

LuxCore's spectral rendering produces physically accurate glass caustics and internal reflections. This was the primary motivation for switching from Blender Cycles, which rendered recursive glass nesting as opaque white blobs rather than transparent refraction.
