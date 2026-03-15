# Gaius

> *"True glory consists in doing what deserves to be written, in writing what deserves to be read."*
> — Gaius Plinius Secundus (Pliny the Elder)

**Gaius** is a CLI-first terminal interface for navigating complex, graph-oriented data domains. It renders high-dimensional embeddings and topological structures onto a constrained grid — transforming abstract complexity into spatial intuition.

Named after the Roman polymath Pliny the Elder, whose *Naturalis Historia* attempted to catalog all knowledge of the natural world, Gaius embodies a similar ambition: to provide a unified interface through which the modern polymath can perceive, navigate, and reason about interconnected information landscapes.

## What Makes Gaius Different

Traditional terminals present information as streams of text. Dashboards present it as isolated charts. Neither captures the *shape* of data — the loops, clusters, and voids that reveal hidden structure.

Gaius implements the following core capabilities:

1. **Low-Dimensional Projection onto a Discrete Lattice**: High-dimensional embeddings are mapped onto a regular 19×19 integer lattice via a dimensionality-reduction procedure (UMAP with fixed hyperparameters). Each lattice point is uniquely addressable and carries local geometric meaning derived from the ambient Riemannian structure.

2. **Computation of Persistent Topological Features**: Persistent homology is computed over a Vietoris–Rips filtration of the embedded point cloud. This produces a barcode whose long-lived generators of the first homology group H₁ (persistent 1-cycles) serve as scale-invariant topological invariants. These features quantify robust loops and potential redundancies or bottlenecks in the underlying data manifold.

3. **Autonomous Exploration Agents**: A population of agents performs reinforcement learning with verifiable rewards (RLVR) on the filtered complex. Knowledge consolidation occurs through periodic replay of trajectories, yielding a compressed latent representation projected back onto the lattice.

4. **Modal Keyboard-Driven Interface**: The interface follows a strictly modal paradigm (in the tradition of Vim and Plan 9 acme) with `hjkl` motion, slash-command dispatch, and overlay toggles, enabling efficient navigation of both the lattice and the underlying gRPC service graph.

5. **Health Monitoring via Failure-Mode and Effects Analysis (FMEA)**: A background observer daemon continuously evaluates system components using FMEA scoring and escalates via an automated corrective protocol (ACP) when thresholds are exceeded.

## The Platform

Gaius has grown from a TUI prototype into a full platform:

- **gRPC Engine** with 37 registered services on port 50051
- **Three interfaces**: TUI (interactive), CLI (scripting), MCP (AI-assisted)
- **6 NVIDIA GPUs** running vLLM inference with makespan scheduling
- **Metaflow pipelines** for article curation, evaluation, and rendering
- **LuxCore path tracer** for procedural card visualizations
- **FMEA-based Health Observer** daemon with automated corrective protocol escalation
- **Bases feature store** with temporal entity queries
- **RASE metamodel** for verifiable agent training

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

Gaius thereby supplies a unified topological interface for the systematic exploration of complex information landscapes.
