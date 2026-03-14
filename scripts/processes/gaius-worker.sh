#!/usr/bin/env bash
# scripts/processes/gaius-worker.sh — Gaius Fetch Worker (content gathering daemon)
# Launched by devenv process-compose; see devenv.nix processes.gaius-worker
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_WORKER "Gaius Worker"

banner "GAIUS WORKER - Content Gathering Daemon"

wait_for_postgres

echo ""
echo "Starting gaius-worker daemon (pool-size=2, poll-interval=60)..."
export PYTHONPATH=""
exec .devenv/state/venv/bin/python -m gaius.workers.cli --pool-size 2 --poll-interval 60 -v
