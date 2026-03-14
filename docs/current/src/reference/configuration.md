# Configuration

Gaius uses HOCON configuration files with environment variable overrides. The canonical source is `config/base.conf`.

## Configuration Hierarchy

1. `config/base.conf` — Default values
2. `~/.config/gaius/acp.conf` — ACP-specific overrides
3. Environment variables — Highest priority

## Database

| Key | Default | Env Var | Description |
|-----|---------|---------|-------------|
| `database.host` | `localhost` | `PGHOST` | PostgreSQL host |
| `database.port` | `5444` | `PGPORT` | PostgreSQL port |
| `database.name` | `zndx_gaius` | `PGDATABASE` | Database name |
| `database.user` | `gaius` | `PGUSER` | Database user |
| `database.password` | `gaius` | `PGPASSWORD` | Database password |

**Important**: Always use `gaius.core.config.get_database_url()` to get the connection URL. Never hardcode.

## Engine

| Key | Default | Env Var | Description |
|-----|---------|---------|-------------|
| `engine.grpc.host` | `0.0.0.0` | `GAIUS_ENGINE_HOST` | gRPC bind host |
| `engine.grpc.port` | `50051` | `GAIUS_ENGINE_PORT` | gRPC port |
| `engine.grpc.max_workers` | `10` | — | Max gRPC worker threads |
| `engine.orchestrator.preload_endpoints` | `["reasoning"]` | — | Endpoints to load on startup |
| `engine.orchestrator.startup_timeout` | `600` | — | Startup timeout (seconds) |
| `engine.scheduler.default_timeout` | `120` | `GAIUS_ENGINE_TIMEOUT` | Default inference timeout |
| `engine.evolution.enabled` | `true` | — | Enable evolution daemon |
| `engine.evolution.idle_threshold` | `60` | — | GPU idle seconds before evolution |

## Health

| Key | Default | Description |
|-----|---------|-------------|
| `health.check_interval` | `60` | Health Observer poll interval (seconds) |
| `health.fmea.learning_rate` | `0.2` | Adaptive S/O/D learning rate |
| `health.self_healing.enabled` | `true` | Enable automatic remediation |

## Agents

| Key | Default | Description |
|-----|---------|-------------|
| `agents.swarm.parallel` | `true` | Enable parallel swarm execution |
| `agents.swarm.timeout` | `60` | Swarm execution timeout (seconds) |
| `agents.theta.confidence_threshold` | `0.8` | Theta consolidation confidence threshold |

## ACP Security

Configured in `~/.config/gaius/acp.conf`:

```hocon
acp {
  github {
    allowed_repos = ["zndx/gaius-acp"]
    require_private = true
    verify_on_each_operation = true
    cache_visibility_seconds = 300
  }
}
```
