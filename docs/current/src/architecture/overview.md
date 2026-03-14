# System Overview

Gaius is a platform for navigating complex, graph-oriented data domains. It projects high-dimensional embeddings and topological structures onto a 19x19 grid, augmented by autonomous agents, self-healing infrastructure, and production data pipelines.

## Package Structure

```
src/gaius/
├── app.py              # TUI application (Textual)
├── cli.py              # Non-interactive CLI
├── mcp_server.py       # MCP server (163 tools)
├── core/               # Configuration, state, telemetry
├── engine/             # gRPC engine (central nervous system)
│   ├── server.py       # Main daemon
│   ├── proto/          # Protobuf definitions
│   ├── generated/      # Generated gRPC bindings
│   ├── grpc/           # gRPC servicers
│   ├── services/       # 37 registered services
│   └── backends/       # vLLM, optillm, embedding controllers
├── health/             # FMEA-based self-healing
│   ├── observe.py      # Health Observer daemon
│   ├── fmea/           # Risk scoring framework
│   └── service_fixes.py # Automated remediation
├── agents/             # Autonomous agent system
│   ├── evolution/      # RLVR training
│   ├── theta/          # Memory consolidation
│   └── cognition/      # Self-observation
├── inference/          # Multi-backend routing
├── flows/              # Metaflow data pipelines
├── viz/                # LuxCore visualization
├── storage/            # PostgreSQL + Qdrant
├── acp/                # Agent Client Protocol
├── rase/               # RASE metamodel (agent verification)
├── bases/              # Feature store
├── hx/                 # History and lineage
├── observability/      # OpenTelemetry + Prometheus
├── widgets/            # TUI widgets
├── commands/           # Slash command implementations
├── kb/                 # Knowledge base operations
├── models/             # Agent model versioning
├── client/             # gRPC client library
└── mcp/                # MCP tool implementations
```

## Layer Architecture

The system is organized in layers with strict dependency direction:

| Layer | Components | Responsibility |
|-------|-----------|----------------|
| L1 - Interface | TUI, CLI, MCP | User-facing thin clients |
| L2 - Client | gRPC client library | Transport abstraction |
| L3 - Engine | gRPC server, services | Business logic, orchestration |
| L4 - Backend | vLLM, optillm, embeddings | GPU workload execution |
| L5 - Storage | PostgreSQL, Qdrant, R2 | Persistence |

**Rule**: Higher layers depend on lower layers, never the reverse. The engine (L3) is the single point of coordination — TUI, CLI, and MCP all call engine RPCs rather than accessing backends or storage directly.

## Key Numbers

| Metric | Count |
|--------|-------|
| Lines of code | ~252K |
| Python packages | 26 |
| Engine services | 37 |
| CLI commands | 63 |
| MCP tools | 163 |
| GPUs | 6 (NVIDIA) |
| gRPC port | 50051 |
| PostgreSQL port | 5444 |

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

See [Engine-First Architecture](./engine-first.md) for why this design was chosen.
