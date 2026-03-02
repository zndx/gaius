#!/usr/bin/env bash
# scripts/processes/aeron-driver.sh — Aeron Media Driver (C++ native)
# Launched by devenv process-compose; see devenv.nix processes.aeron-driver
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_ENGINE "Aeron Media Driver"

banner "AERON MEDIA DRIVER - Ultra-Low-Latency IPC Transport"

# Clean up stale Aeron directories
AERON_DIR="/dev/shm/gaius-aeron"
if [ -d "$AERON_DIR" ]; then
  echo "Cleaning up stale Aeron directory: $AERON_DIR"
  rm -rf "$AERON_DIR"
fi

echo "Starting Aeron Media Driver (C++ native)..."
echo "  IPC Channel: aeron:ipc"
echo "  Shared Memory: $AERON_DIR"
echo ""

# Set Aeron directory and run native driver
export AERON_DIR="$AERON_DIR"
exec aeronmd
