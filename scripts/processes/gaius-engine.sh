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

# ========================================================================
# GPU CLEANUP - Ensure clean start by killing any stale vLLM processes
# ========================================================================
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

echo "Starting gaius-engine (manages optillm/vLLM dynamically)..."
export PYTHONPATH=""
exec .devenv/state/venv/bin/python -m gaius.engine --config config/agents.conf -v
