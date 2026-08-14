# Process Scripts

All process startup bash lives in `scripts/processes/*.sh`. Shared helpers are in `scripts/lib/`.

## Process Scripts

| Script | Service | Dependencies |
|--------|---------|-------------|
| `aeron-driver.sh` | Aeron IPC transport | None |
| `gaius-engine.sh` | gRPC engine daemon | Aeron, PostgreSQL |
| `gaius-worker.sh` | Background worker | Engine |
| `metabase.sh` | Analytics dashboards | PostgreSQL |
| `metaflow-bootstrap.sh` | Metaflow K8s setup | Kubernetes |
| `metaflow-db-setup.sh` | Metaflow database | PostgreSQL |
| `metaflow-port-forwards.sh` | K8s port forwarding | Kubernetes |
| `metaflow-ui.sh` | Metaflow UI | Metaflow service |
| `nifi.sh` | Data ingestion | PostgreSQL |

## Shared Helpers

### `scripts/lib/process-helpers.sh`

Common functions used by all process scripts:

| Function | Purpose |
|----------|---------|
| `banner` | Print startup banner with service name |
| `check_disabled` | Skip if service is disabled via env var |
| `wait_for_postgres` | Block until PostgreSQL is accepting connections |
| `wait_for_aeron` | Block until Aeron driver is ready |

### `scripts/lib/gpu-helpers.sh`

GPU cleanup functions shared by `gaius-engine.sh` and the justfile:

| Function | Purpose |
|----------|---------|
| `gpu_cleanup` | Kill orphan vLLM/CUDA processes |

## Script Pattern

Every process script follows the same structure:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

banner "Service Name"
check_disabled "SERVICE_NAME"

# Wait for dependencies
wait_for_postgres

# Set KUBECONFIG unconditionally (not from enterShell)
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"

# Start the service
exec some-command --flags
```

## Systemd peer wrappers

Signals group control (`gaius.service`, `After=signals-ready.service`) execs
these instead of embedding shell in the unit file:

| Script | Role |
|--------|------|
| `scripts/systemd_start.sh` | Idempotent `just up`; blocks until `Engine/Status` on `:50051` |
| `scripts/systemd_stop.sh` | `just down` / `devenv processes down` (no GPU teardown) |

See [Signals peer unit](./peer-unit.md).

## Adding a New Process

1. Create `scripts/processes/<name>.sh` with the pattern above
2. Add process block to `devenv.nix` with one-liner exec
3. Pass any Nix-only values as env vars in the exec block
4. Set dependency ordering with `process-compose.depends_on`
