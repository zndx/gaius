#!/usr/bin/env bash
# scripts/lib/gpu-helpers.sh — GPU cleanup helpers
#
# Source this file:
#   source "$(dirname "${BASH_SOURCE[0]}")/gpu-helpers.sh"

# Kill stale vLLM/engine GPU processes and show memory status.
# Used by both gaius-engine startup and `just gpu-cleanup`.
gpu_cleanup() {
  echo "Cleaning up stale GPU processes..."

  # Find and kill any processes using GPU memory
  VLLM_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')
  if [ -n "$VLLM_PIDS" ]; then
    echo "  Found GPU processes: $VLLM_PIDS"
    for pid in $VLLM_PIDS; do
      if [ -n "$pid" ]; then
        echo "    Killing PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
    sleep 2
    echo "  GPU processes terminated"
  else
    echo "  No stale GPU processes found"
  fi

  # Also kill any orphaned Python vllm/engine processes (not using GPU yet)
  pkill -9 -f "vllm serve" 2>/dev/null || true
  pkill -9 -f "gaius.engine.server" 2>/dev/null || true

  # Show GPU memory status
  echo ""
  echo "GPU Memory Status:"
  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/  /' || echo "  (nvidia-smi not available)"
  echo ""
}
