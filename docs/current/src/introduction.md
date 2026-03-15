# Gaius

> *"True glory consists in doing what deserves to be written, in writing what deserves to be read."*
> — Gaius Plinius Secundus (Pliny the Elder)

**Gaius** is a CLI-first terminal interface for navigating complex, graph-oriented data domains. It renders high-dimensional embeddings and topological structures onto a constrained grid — transforming abstract complexity into spatial intuition.

Named after the Roman polymath Pliny the Elder, whose *Naturalis Historia* attempted to catalog all knowledge of the natural world, Gaius embodies a similar ambition: to provide a unified interface through which the modern polymath can perceive, navigate, and reason about interconnected information landscapes.

## What Makes Gaius Different

Traditional terminals present information as streams of text. Dashboards present it as isolated charts. Neither captures the *shape* of data — the loops, clusters, and voids that reveal hidden structure.

Gaius implements the following core capabilities:

1. **Low-Dimensional Projection onto a Discrete Lattice**: High-dimensional embeddings are mapped onto a regular 19×19 integer lattice via UMAP quantization, with multiple orthogonal layout modes. The main lattice is accompanied by a dual system of 9×9 orthographic mini-grids: an **Embed** view showing the local cosine-similarity neighborhood around the cursor, and an **Iso** view rendering discrete Ricci curvature as an elevation map over the projected manifold. Together these provide simultaneous access to global topology and local differential geometry.

2. **Persistent Homology (H₀–H₂) over the Projected Lattice**: Persistent homology is computed over a Vietoris–Rips filtration of the UMAP-projected point cloud, producing persistence barcodes across dimensions zero through two. Long-lived generators of H₁ (persistent 1-cycles) serve as the primary scale-invariant topological invariants, quantifying robust loops and structural redundancies in the underlying data manifold. H₀ captures connected components; H₂ identifies higher-dimensional voids.

3. **Discrete Ricci Curvature on the Semantic Manifold**: Ollivier–Ricci curvature is estimated over a k-nearest-neighbor graph constructed from the embedding space. The resulting curvature field, gradient vectors, and divergence values are projected onto the lattice and rendered in the Iso mini-grid, revealing regions of semantic convergence (positive curvature) and divergence (negative curvature).

4. **Structured Multi-Agent Exploration**: A swarm of seven specialized agents (Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary) operates directly on the filtered complex with parallel execution and consensus synthesis. Agent training follows the RASE (Rapid Agentic Systems Engineering) framework, which provides intrinsically verifiable rewards via a formal constraint-satisfaction oracle rather than learned approximations.

5. **Modal Keyboard-Driven Interface**: The interface follows a strictly modal paradigm (in the tradition of Vim and Plan 9 acme) with `hjkl` motion, slash-command dispatch, and overlay toggles, enabling efficient navigation of both the lattice and the underlying gRPC service graph.

6. **Health Monitoring via Failure-Mode and Effects Analysis (FMEA)**: A background observer daemon continuously evaluates system components using FMEA scoring (Severity × Occurrence × Detection) and escalates via the automated corrective protocol (ACP) when risk priority thresholds are exceeded.

## Core Mathematical Pipeline

The following pipeline is fully implemented in the current prototype:

1. **Embedding** — Documents are encoded as multi-vector embeddings (ColNomic, GPU-accelerated) and stored in a vector index.
2. **Lattice projection** — UMAP maps the high-dimensional embedding space onto the 19×19 integer lattice, with layout variants for different analytical perspectives.
3. **Persistent homology** — A Vietoris–Rips filtration is constructed over the projected point cloud; persistence barcodes are computed for H₀, H₁, and H₂, yielding topological overlays on the lattice.
4. **Discrete Ricci curvature** — Ollivier–Ricci curvature is estimated on the k-NN graph of the embedding space, producing curvature, gradient, and divergence fields rendered in the orthographic Iso mini-grid.
5. **Agent exploration** — The seven-role agent swarm operates on the filtered complex; topological features and curvature values inform agent state, trajectory selection, and Zettelkasten knowledge capture.
6. **Visualization** — LuxCore path-traced renderings of card topology are generated procedurally from the computed geometric features.

The lattice thus serves simultaneously as a visualization surface and a discrete approximation of the underlying data manifold, bridging persistent homology, manifold geometry, and agent-based exploration in a single interactive system.

## The Platform

The computational pipeline above is embedded within a broader systems architecture:

- **gRPC inference control plane** — 37 registered services coordinating 6 NVIDIA GPUs with makespan-scheduled vLLM inference
- **Three isomorphic interfaces** — TUI (interactive exploration), CLI (scripting and automation), MCP (163 tools for AI-assisted workflows), all communicating with the engine via a shared gRPC protocol
- **Metaflow pipelines** — Orchestrated data flows for article curation, agent evaluation, and batch rendering
- **LuxCore path tracer** — Procedural card visualizations driven by the grammar engine, with GPU-accelerated rendering via PATHOCL
- **FMEA-based Health Observer** — Background daemon scoring system components on Severity × Occurrence × Detection, escalating via the automated corrective protocol when risk priority thresholds are exceeded
- **Bases feature store** — Temporal entity queries with a domain query language compiled to SQL via AST-based guardrails
- **RASE metamodel** — Formal verification framework for agent training: constraints are specified declaratively, composed via AllOf/AnyOf/Not, and evaluated by a ground-truth oracle to produce verifiable reward signals

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

The end-to-end pipeline — from high-dimensional embeddings through lattice projection, filtration, curvature estimation, and multi-agent exploration — is operational in the current prototype, providing a unified topological interface for the systematic investigation of complex information landscapes.
