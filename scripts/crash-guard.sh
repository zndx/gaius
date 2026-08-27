#!/usr/bin/env bash
# crash-guard.sh — crash-gated boot state for GPU workload deferral.
#
# Model: a `clean-shutdown` sentinel is written at graceful shutdown
# (`crash-guard.service` ExecStop). At boot (ExecStart):
#   - sentinel present  -> clean reboot  -> consume it, clear any defer marker
#   - sentinel absent    -> UNCLEAN reboot -> drop the `defer-gpu` marker so
#                           gaius-engine.sh holds GPU workloads until an
#                           operator runs `just resume-gpu`.
#
# State lives on the ROOT disk (/var/lib/gaius), deliberately NOT on /raid —
# the RAID0 array is the thing most likely to be wedged during a crash.
#
# The dir is created 0775 root:rch so the rch-owned engine can read the
# marker and `gpu-resume.sh` (rch) can remove it.
set -euo pipefail

STATE_DIR="${GAIUS_CRASH_STATE_DIR:-/var/lib/gaius}"
SENTINEL="$STATE_DIR/clean-shutdown"
MARKER="${GAIUS_DEFER_MARKER:-$STATE_DIR/defer-gpu}"

mkdir -p "$STATE_DIR"

case "${1:-boot}" in
  boot)
    if [[ -e "$SENTINEL" ]]; then
      rm -f "$SENTINEL" "$MARKER"
      echo "crash-guard: clean boot (sentinel consumed) — GPU workloads start normally"
    else
      : > "$MARKER"
      echo "crash-guard: UNCLEAN reboot detected (no clean-shutdown sentinel)"
      echo "crash-guard: dropped GPU-defer marker $MARKER"
      echo "crash-guard: GPU workloads will be HELD until 'just resume-gpu'"
    fi
    ;;
  shutdown)
    : > "$SENTINEL"
    echo "crash-guard: graceful shutdown — clean-shutdown sentinel written"
    ;;
  *)
    echo "usage: $0 {boot|shutdown}" >&2
    exit 2
    ;;
esac
