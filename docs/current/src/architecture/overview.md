# System Overview

Gaius projects high-dimensional embeddings and their topological/geometric structure onto a 19x19 lattice. The system integrates persistent homology, Ollivier-Ricci curvature, agent orchestration, FMEA-based health monitoring, and LuxCore visualization.

## Layer Architecture

The system is organized in layers with strict dependency direction:

| Layer | Components | Responsibility |
|-------|-----------|----------------|
| L1 - Core | Persistent homology, Ricci curvature, UMAP projection, telemetry | Mathematical foundations |
| L2 - Transport | gRPC client, PostgreSQL, Qdrant, Iceberg | Persistence and communication |
| L3 - Engine | gRPC server, 37 registered services | Business logic, orchestration |
| L4 - Inference | vLLM, optillm, embeddings, models | GPU workload execution |
| L5 - Orchestration | Swarm, Theta, evolution, health | Agent coordination |
| L6 - Verification | RASE metamodel, constraints, oracle | Safety-critical verification |
| L7 - Widgets | Grid, mini-grids, file tree, info panel | TUI components |
| L8 - Application | TUI, CLI, MCP server | User-facing interfaces |

**Rule**: Higher layers depend on lower layers, never the reverse. The engine (L3) is the single point of coordination — TUI, CLI, and MCP all call engine RPCs rather than accessing backends or storage directly.

## Communication Paths

All three interfaces communicate with the engine via gRPC:

```
┌─────────┐  ┌─────────┐  ┌─────────┐
│   TUI   │  │   CLI   │  │   MCP   │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     └────────────┼────────────┘
                  │ gRPC :50051
           ┌──────┴──────┐
           │   Engine    │
           │  (37 svcs)  │
           └──────┬──────┘
                  │
     ┌────────────┼────────────┐
     │            │            │
┌────┴────┐ ┌────┴────┐ ┌────┴────┐
│  vLLM   │ │ Postgres│ │ Qdrant  │
│ (GPUs)  │ │  :5444  │ │  :6334  │
└─────────┘ └─────────┘ └─────────┘
```

## Mathematical Foundations

The core layer (L1) provides the mathematical primitives that other layers consume:

**Grid projection**: UMAP maps embedding vectors from ℝ⁷⁶⁸ to continuous 2D coordinates (cosine metric, k=15, min_dist=0.1). Coordinates are quantized to the 19x19 integer lattice by rounding and clipping to [0, 18]. Grid positions follow Go board conventions (A1–T19, omitting I).

**Persistent homology**: Ripser computes a Vietoris-Rips filtration over the cosine distance matrix of the original high-dimensional embeddings (not the projected coordinates). Persistence barcodes for H0 (components), H1 (loops), and H2 (voids) are computed. Intervals with persistence > 0.1 are marked significant.

**Ollivier-Ricci curvature**: Discrete curvature on the k-NN graph (k=15, cosine metric, alpha=0.5, OTD method). Per-node curvature is the mean of incident edge curvatures. Positive curvature indicates overlapping neighborhoods (cluster interiors); negative indicates diverging neighborhoods (transition regions). Gradient fields and divergence values are projected to the 9x9 Iso mini-grid via inverse-distance-weighted interpolation (power=2).

These three computations feed into multiple downstream systems:

- **Visualization** — Curvature and persistence control the grammar engine's recursive shape expansion
- **Agent trajectories** — Roles use curvature values for lattice positioning (Leader → cluster centroids, Risk → boundary regions)
- **Overlays** — TUI renders curvature, persistence, and complexity as scalar field overlays on the grid

## Execution Paths

**TUI session**: `gaius` → splash screen → `GaiusApp.compose()` → `on_mount()` initializes gRPC client, loads KB entries, projects grid, starts background services.

**CLI command**: `gaius-cli --cmd "/health"` → parse command → gRPC call → engine servicer → format response.

**MCP tool call**: MCP client → `mcp_server.py` → `@mcp.tool` handler → `gaius.mcp.operations` → gRPC → engine → backend.

**Agent evolution**: Engine daemon → `EvolutionService.daemon_loop()` → check GPU idle (<30%) → select next agent → optimize → evaluate → save version.

**Theta consolidation**: `/sitrep` → `ThetaAgent.consolidate()` → NVAR (Nonlinear Vector AutoRegression) drift detection → BERTSubs subsumption inference → Knowledge Gradient selection → wikilink injection.

## Key Numbers

| Metric | Count |
|--------|-------|
| Lines of code | ~252K |
| Python packages | 26 |
| Engine services | 37 |
| CLI commands | 63 |
| MCP tools | 163 |
| GPUs | 6 (NVIDIA) |
| FMEA (Failure Mode and Effects Analysis) modes | 34 |
| gRPC port | 50051 |
| PostgreSQL port | 5444 |

## Package Structure

```
src/gaius/
├── app.py              # TUI application (Textual)
├── cli.py              # Non-interactive CLI
├── mcp_server.py       # MCP server (163 tools)
├── core/               # TDA, geometry, projection, state
├── engine/             # gRPC engine (central nervous system)
├── health/             # FMEA-based health monitoring and self-healing
├── agents/             # Swarm, theta, evolution, cognition
├── inference/          # Multi-backend routing
├── rase/               # MBSE metamodel (agent verification)
├── viz/                # LuxCore visualization
├── storage/            # PostgreSQL + Qdrant
├── flows/              # Metaflow data pipelines
├── widgets/            # TUI widgets
└── commands/           # Slash command implementations
```

See [Engine-First Architecture](./engine-first.md) for why this design was chosen.
