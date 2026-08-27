#!/usr/bin/env bash
# scripts/processes/gaius-engine.sh — Gaius Engine (central inference & evolution daemon)
# Manages optillm/vLLM processes dynamically.
# Launched by devenv process-compose; see devenv.nix processes.gaius-engine
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"
source "$SCRIPT_DIR/../lib/gpu-helpers.sh"

check_disabled DISABLE_ENGINE "Gaius Engine"

banner "GAIUS ENGINE - Centralized Inference & Evolution Daemon"

# Exclusive lattice bind — refuse to start if :50051 is already held.
# (gRPC SO_REUSEPORT would otherwise dual-bind; see #EN.00000014.DUALBIND)
assert_tcp_port_free "${GAIUS_ENGINE_GRPC_PORT:-50051}" "gaius-engine lattice"

# Same cluster hostname as Signals/Ægir when they export it.
if [[ -z "${GAIUS_ADVERTISE_HOST:-}" && -n "${SIGNALS_ADVERTISE_HOST:-}" ]]; then
  export GAIUS_ADVERTISE_HOST="$SIGNALS_ADVERTISE_HOST"
fi

# Follow devenv's assigned PGPORT (worktrees / sibling projects). If
# systemd pinned this checkout's postmaster to the lattice port, wait
# discovers that live listener instead of a dark assigned port.
wait_for_postgres "${PGUSER:-$USER}"

# Interactive direnv `source_up` loads ~/local/.env (XAI/BRAVE/CEREBRAS).
# system.slice / process-compose do not. Walk repo → $HOME for .env files.
_dir="$(cd "$SCRIPT_DIR/../.." && pwd)"
while true; do
  if [[ -f "$_dir/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$_dir/.env"
    set +a
  fi
  [[ "$_dir" == "/" || "$_dir" == "$HOME" ]] && break
  _dir="$(dirname "$_dir")"
done
unset _dir
# dotenv DATABASE_URL is static (:5444). Re-derive from the effective PGPORT
# devenv exported so we do not talk to a dark contract port.
export DATABASE_URL="postgres://localhost:${PGPORT:-5444}/zndx_gaius?sslmode=disable"
# Warehouse is Signals RustFS. devenv MinIO is not a lattice store.
export GAIUS_MINIO_ENDPOINT="${GAIUS_MINIO_ENDPOINT:-${RUSTFS_ADDRESS:-127.0.0.1:9010}}"
export GAIUS_MINIO_BUCKET="${GAIUS_MINIO_BUCKET:-signals-dataproducts}"
export GAIUS_HX_PREFIX="${GAIUS_HX_PREFIX:-iceberg/}"
export GAIUS_MINIO_ACCESS_KEY="${GAIUS_MINIO_ACCESS_KEY:-${RUSTFS_ACCESS_KEY:-rustfsadmin}}"
export GAIUS_MINIO_SECRET_KEY="${GAIUS_MINIO_SECRET_KEY:-${RUSTFS_SECRET_KEY:-rustfsadmin}}"
# Iceberg catalog is Signals Polarisfork (signals-polaris.service), not Gaius SQL.
export GAIUS_HX_CATALOG_TYPE="${GAIUS_HX_CATALOG_TYPE:-rest}"
export GAIUS_HX_CATALOG_NAME="${GAIUS_HX_CATALOG_NAME:-signals}"
export GAIUS_HX_POLARIS_URI="${GAIUS_HX_POLARIS_URI:-http://127.0.0.1:8181/api/catalog}"
# Discover 1h strip + 1 Hz warehouse INSERT: devenv Postgres impala_fdw → Kudu.
export SIGNALS_WAREHOUSE_DSN="${SIGNALS_WAREHOUSE_DSN:-postgresql://signals@127.0.0.1:5455/signals}"
export GAIUS_WAREHOUSE_DSN="${GAIUS_WAREHOUSE_DSN:-postgresql://gaius:gaius@127.0.0.1:${PGPORT:-5444}/zndx_gaius}"
export SIGNALS_ROOT="${SIGNALS_ROOT:-$HOME/local/src/wxs/signals}"
# Engine is the Kudu writer (INSERT gpu_metrics_tier0). Do not start the
# C++ sidecar ingest from this process.

# Engine owns vLLM. Recycle always remediates GPU/vLLM state — do not skip
# cleanup because :8081 answered once (that hid thinking deaths on restart).
gpu_cleanup

# ========================================================================
# WAIT FOR AERON
# ========================================================================
wait_for_aeron

# Enable OpenTelemetry tracing if configured. Precedence: explicit
# OTEL_ENDPOINT override > profile env (devenv.nix forces 4337 — gaius's
# collector claim; 4317 is squatted by cldr/cybersec) > 4337 default.
export OTEL_SERVICE_NAME="gaius-engine"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_ENDPOINT:-${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4337}}"

# Set API keys for inference backends
export OPTILLM_API_KEY="${OPTILLM_API_KEY:-gaius-local-key}"
export OPENAI_API_KEY="${OPTILLM_API_KEY:-gaius-local-key}"

# Pass through Cloudflare credentials for KV sync
export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
# GAIUS_SESSIONS namespace for X OAuth
export CLOUDFLARE_KV_NAMESPACE_ID="${CLOUDFLARE_KV_NAMESPACE_ID:-}"
# GAIUS_COLLECTIONS namespace for landing page cards
export CLOUDFLARE_COLLECTIONS_KV_NAMESPACE_ID="${CLOUDFLARE_COLLECTIONS_KV_NAMESPACE_ID:-4541b17fa5244bffb346f9a55b8eca93}"

echo ""

# Crash-gated GPU defer. crash-guard.service drops this marker when the
# previous boot ended uncleanly (no graceful-shutdown sentinel). Hold the
# GPU workloads (preload + ambient + evolution) so a load-induced crash
# can't loop into a reboot cycle; the engine still comes up for inspection
# (warehouse, CLI, health, cognition). Marker is on the root disk, NOT /raid.
# Resume once you've inspected: `just resume-gpu` (scripts/gpu-resume.sh).
GAIUS_DEFER_MARKER="${GAIUS_DEFER_MARKER:-/var/lib/gaius/defer-gpu}"
if [[ -f "$GAIUS_DEFER_MARKER" ]]; then
  echo "GPU-DEFER: unclean-reboot marker present ($GAIUS_DEFER_MARKER)"
  echo "GPU-DEFER: holding GPU workloads (preload/ambient/evolution) — engine boots for inspection only"
  echo "GPU-DEFER: resume with 'just resume-gpu' (or scripts/gpu-resume.sh) once cleared to run"
  export GAIUS_CLEAN_START=false
  export GAIUS_AUTO_START_AMBIENT=false
  export GAIUS_AUTO_EVOLUTION=false
fi

echo "Starting gaius-engine (manages optillm/vLLM dynamically)..."
export PYTHONPATH=""
exec .devenv/state/venv/bin/python -m gaius.engine --config config/agents.conf -v
