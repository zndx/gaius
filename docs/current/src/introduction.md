# Gaius

**Gaius** is a terminal interface for navigating graph-oriented data domains. It projects high-dimensional embeddings onto a discrete lattice via UMAP, computes persistent homology and Ollivier–Ricci curvature over the embedding space, and renders the results as interactive overlays on the lattice.

Named after Gaius Plinius Secundus (Pliny the Elder), whose *Naturalis Historia* cataloged the natural world across 37 books.

## Capabilities

1. **Lattice Projection**: UMAP (cosine metric, k=15 neighbors, min_dist=0.1) maps embedding vectors to continuous 2D coordinates. These are quantized to a 19×19 integer lattice by rounding and clipping to [0, 18]. The main lattice is accompanied by two 9×9 orthographic mini-grids centered on the cursor: an **Embed** view showing the local cosine-similarity neighborhood, and an **Iso** view rendering scalar fields (curvature, persistence, complexity) as elevation maps via inverse-distance-weighted interpolation (power=2).

2. **Persistent Homology (H₀–H₂)**: Ripser computes a Vietoris–Rips filtration over the cosine distance matrix of the original high-dimensional embeddings (not the projected coordinates), producing persistence barcodes for dimensions 0 through 2. Intervals with persistence > 0.1 are marked significant. H₀ captures connected components, H₁ captures 1-cycles, and H₂ captures 2-dimensional voids. Barcodes are rendered as overlays on the lattice, with persistent generators mapped to their lattice positions via the UMAP projection.

3. **Ollivier–Ricci Curvature**: Discrete Ricci curvature is computed on a k-nearest-neighbor graph (k=15, cosine metric) constructed from the embedding space, using the OTD method with α=0.5. Per-node curvature is the mean of incident edge curvatures. The resulting curvature field, gradient vectors (finite-difference approximation), and divergence values are projected to the Iso mini-grid. Positive curvature indicates cluster interiors; negative curvature indicates semantic boundaries.

4. **Multi-Agent Exploration**: Seven agents (Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary) navigate the lattice with role-specific positioning behaviors (center-seeking, peripheral, random) and cluster affinities. Agent training uses the RASE framework (Rapid Agentic Systems Engineering), where constraints are composed declaratively via AllOf/AnyOf/Not and evaluated by a ground-truth oracle to produce verifiable reward signals.

5. **Modal Interface**: Vim-style modal navigation (`hjkl` motion, slash-command dispatch, overlay toggles) over both the lattice and the underlying gRPC service graph.

6. **FMEA Health Observer**: A background daemon scores system components on Severity × Occurrence × Detection. When risk priority numbers exceed configured thresholds, it escalates to an agent via the [Agent Client Protocol](https://agentclientprotocol.com/) (ACP) for FMEA-mediated intervention.

## Computational Pipeline

The following pipeline is implemented end-to-end:

1. **Embed** — Documents are encoded as multi-vector embeddings (ColNomic, GPU-accelerated) and indexed.
2. **Project** — UMAP maps the embedding space to 2D; coordinates are rounded to the 19×19 integer lattice.
3. **Filtration** — Vietoris–Rips filtration over the cosine distance matrix of original embeddings; Ripser computes persistence barcodes for H₀, H₁, H₂. Significant intervals (persistence > 0.1) produce topological overlays.
4. **Curvature** — Ollivier–Ricci curvature on the k-NN graph (k=15, α=0.5, OTD); curvature, gradient, and divergence fields are interpolated onto the 9×9 Iso mini-grid via IDW.
5. **Exploration** — Agents operate on the lattice; topological features and curvature values are available as grid state for trajectory selection.
6. **Rendering** — LuxCore path-traces procedural card visualizations from the computed geometric features.

The lattice serves as both a visualization surface and a discrete approximation of the data manifold, coupling persistent homology, differential geometry, and agent-based exploration in one interactive system.

## Architecture

- **Inference** — gRPC control plane with 37 services coordinating 6 NVIDIA GPUs via makespan-scheduled vLLM
- **Interfaces** — TUI, CLI, and MCP server (163 tools), all communicating with the engine via shared gRPC protocol
- **Pipelines** — Metaflow orchestration for article curation, agent evaluation, and batch rendering
- **Visualization** — LuxCore PATHOCL engine with GPU-accelerated rendering driven by a CFDG-inspired grammar
- **Observability** — FMEA-scored health observer with [ACP](https://agentclientprotocol.com/)-mediated agent intervention
- **Storage** — Bases feature store with a domain query language compiled to SQL via AST-based guardrails; RASE metamodel for agent verification

## Getting Started

```bash
# Launch the TUI
uv run gaius

# Use the CLI for scripting
uv run gaius-cli --cmd "/health" --format json

# Check system status
uv run gaius-cli --cmd "/gpu status" --format json
```

Navigate with `hjkl`. Cycle overlays with `o`. Toggle modes with `v`. Press `?` for help.
