#!/usr/bin/env bash
# scripts/lib/gpu-helpers.sh — GPU cleanup helpers
#
# Source this file:
#   source "$(dirname "${BASH_SOURCE[0]}")/gpu-helpers.sh"
#
# Cleanup is LEASE-AWARE: sibling zndx engines (aegir, atelier) register
# advisory GPU leases in /tmp/zndx-gpu-leases (per-GPU-set lock files with
# project-tagged owner.json payloads). Any process that is a live lease
# holder — or a descendant of one — is spared. Everything here must go
# through _kill_unleased; a blanket pkill/kill of GPU processes kills the
# sibling engines' vLLM workers.

# Shared cross-project advisory lease dir (same convention as aegir/atelier).
ZNDX_GPU_LEASE_DIR="${ZNDX_GPU_LEASE_DIR:-/tmp/zndx-gpu-leases}"

# Print PIDs of live cross-project lease holders, one per line.
# Stale leases (holder pid gone) are ignored.
_lease_holder_pids() {
  local f pid
  for f in "$ZNDX_GPU_LEASE_DIR"/*.owner.json; do
    if [ ! -e "$f" ]; then continue; fi
    pid=$(grep -o '"pid"[[:space:]]*:[[:space:]]*[0-9]*' "$f" 2>/dev/null | grep -o '[0-9]*$' || true)
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
      echo "$pid"
    fi
  done
  return 0
}

# Parent PID of $1 (robust against spaces/parens in comm), or empty.
_ppid_of() {
  local stat
  stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 0
  stat="${stat##*) }"
  # After stripping "pid (comm) ", fields are: state ppid pgrp ...
  set -- $stat
  echo "${2:-}"
  return 0
}

# True (0) if pid $1 equals pid $2 or is one of its descendants.
_is_same_or_descendant() {
  local pid="$1" ancestor="$2" hops=0
  while [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$pid" != "1" ] && [ "$hops" -lt 64 ]; do
    if [ "$pid" = "$ancestor" ]; then
      return 0
    fi
    pid=$(_ppid_of "$pid")
    hops=$((hops + 1))
  done
  return 1
}

# kill -9 every PID argument NOT owned by a live lease holder.
# Spared PIDs are reported so cleanup output shows why they survived.
_kill_unleased() {
  local holders pid holder spared
  holders=$(_lease_holder_pids)
  for pid in "$@"; do
    if [ -z "$pid" ] || [ ! -d "/proc/$pid" ]; then continue; fi
    spared=""
    for holder in $holders; do
      if _is_same_or_descendant "$pid" "$holder"; then
        spared="$holder"
        break
      fi
    done
    if [ -n "$spared" ]; then
      echo "    Sparing PID $pid — owned by cross-project lease holder $spared ($ZNDX_GPU_LEASE_DIR)"
    else
      echo "    Killing PID $pid..."
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  return 0
}

# Kill stale vLLM/engine GPU processes and show memory status.
# Used by both gaius-engine startup and `just gpu-cleanup`.
gpu_cleanup() {
  echo "Cleaning up stale GPU processes..."

  # Find processes using GPU memory; kill only unleased ones
  VLLM_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')
  if [ -n "${VLLM_PIDS// /}" ]; then
    echo "  Found GPU processes: $VLLM_PIDS"
    _kill_unleased $VLLM_PIDS
    sleep 2
    echo "  GPU process cleanup done"
  else
    echo "  No stale GPU processes found"
  fi

  # Orphaned vLLM processes (not using GPU yet) — sibling engines' vLLM
  # matches this pattern too, so the same lease sparing applies.
  _kill_unleased $(pgrep -f "vllm serve" 2>/dev/null || true)
  # The gaius engine is ours alone; the pattern cannot match sibling engines.
  pkill -9 -f "gaius.engine.server" 2>/dev/null || true

  # Show GPU memory status
  echo ""
  echo "GPU Memory Status:"
  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/  /' || echo "  (nvidia-smi not available)"
  echo ""
}
