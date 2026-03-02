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

# ========================================================================
# GPU CLEANUP - Ensure clean start by killing any stale vLLM processes
# ========================================================================
gpu_cleanup

# ========================================================================
# WAIT FOR AERON
# ========================================================================
wait_for_aeron

# Enable OpenTelemetry tracing if configured
export OTEL_SERVICE_NAME="gaius-engine"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_ENDPOINT:-http://localhost:4317}"

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
