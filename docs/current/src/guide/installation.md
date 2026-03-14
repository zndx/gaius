# Installation

Gaius uses devenv (built on Nix) for reproducible development environments and `uv` for Python dependency management.

## Prerequisites

| Dependency | Purpose | Install |
|------------|---------|---------|
| **Nix** | Package manager | [nix.dev](https://nix.dev) |
| **devenv** | Development environment | `nix profile install github:cachix/devenv` |
| **uv** | Python package manager | Provided by devenv |
| **Just** | Task runner | Provided by devenv |

You do not need to install Python, PostgreSQL, or any other runtime dependency manually. Nix provides everything.

## Environment Setup

Clone the repository and enter the devenv shell:

```bash
git clone <repo-url>
cd gaius
devenv shell
```

The first `devenv shell` invocation downloads and caches all Nix dependencies. Subsequent invocations start in under a second.

Inside the shell, install Python dependencies:

```bash
uv sync
```

For optional features, use extras:

```bash
uv sync --extra tda      # Topological data analysis (giotto-tda)
uv sync --extra swarm    # Multi-agent support (langchain)
```

## Starting Platform Services

Gaius depends on several backend services: PostgreSQL, Qdrant, the gRPC engine, and others. Start them all with:

```bash
devenv processes up -d
```

To stop all services:

```bash
devenv processes down
```

To verify everything is running, use the Just task runner:

```bash
just --list              # Show all available tasks
just restart-clean       # Full clean restart if something is stuck
```

## Database

PostgreSQL runs on port **5444** with a database named **zndx_gaius**:

```bash
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius
```

The database name is `zndx_gaius`, not `gaius`. The connection URL used internally is:

```
postgres://gaius:gaius@localhost:5444/zndx_gaius?sslmode=disable
```

## Verifying the Installation

Once services are running, confirm the gRPC engine is healthy:

```bash
uv run gaius-cli --cmd "/health" --format json
```

If this returns a JSON health report, the installation is complete. If it fails, try `just restart-clean` and check the process logs in `.devenv/processes.log`.
