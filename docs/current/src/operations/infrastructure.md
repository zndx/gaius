# Infrastructure

Gaius runs on a local development infrastructure managed by devenv (Nix-based), with process-compose for service orchestration and Just for task running.

## Components

| Component | Purpose | Management |
|-----------|---------|------------|
| devenv | Nix-based development environment | `devenv shell` |
| process-compose | Service orchestration | `devenv processes up/down` |
| Just | Task runner (recipes) | `just <recipe>` |
| PostgreSQL | Primary database (:5444) | devenv process |
| Qdrant | Vector store (:6334) | devenv process |
| Aeron | IPC transport | devenv process |
| NiFi | Data ingestion | devenv process |
| Metabase | Analytics dashboards | devenv process |
| Gaius Engine | gRPC daemon (:50051) | devenv process |

## Quick Start

```bash
# Enter development environment
devenv shell

# Start all services
devenv processes up

# Or clean restart (preferred)
just restart-clean

# Check status
uv run gaius-cli --cmd "/health" --format json
```

## Architecture

`devenv.nix` is a pure service declaration file (~470 lines). It defines packages, environment variables, service configurations, and process dependency graphs. All process startup bash lives in `scripts/processes/*.sh`.

See:
- [devenv Environment](./devenv.md) — Nix configuration details
- [Process Scripts](./processes.md) — Startup script architecture
- [Just Task Runner](./just.md) — Available recipes
