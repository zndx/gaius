#!/usr/bin/env bash
# crash-guard.sh — crash-gated boot state for GPU workload deferral.
#
# Model: a clean-shutdown STAMP (a small file holding the shutdown timestamp) is
# written at graceful shutdown (`crash-guard.service` ExecStop) and fsync'd so it
# survives the reboot. At boot (ExecStart):
#   - stamp present -> clean reboot   -> consume it, clear any defer marker
#   - stamp absent  -> UNCLEAN reboot -> drop the `defer-gpu` marker so
#                      gaius-engine.sh holds GPU workloads until an operator runs
#                      `just resume-gpu`.
#
# "stamp", not "sentinel": sentinel is reserved for our MiNIFi K8s stand-ins for
# non-K8s apps. The stamp carries its shutdown timestamp as content so a boot can
# report exactly which graceful shutdown it is consuming.
#
# State lives on the ROOT disk (/var/lib/gaius), deliberately NOT on /raid —
# the RAID0 array is the thing most likely to be wedged during a crash.
#
# The dir is created 0775 root:rch so the rch-owned engine can read the
# marker and `gpu-resume.sh` (rch) can remove it.
set -euo pipefail

STATE_DIR="${GAIUS_CRASH_STATE_DIR:-/var/lib/gaius}"
STAMP="$STATE_DIR/clean-shutdown.stamp"
MARKER="${GAIUS_DEFER_MARKER:-$STATE_DIR/defer-gpu}"

mkdir -p "$STATE_DIR"

case "${1:-boot}" in
  boot)
    if [[ -e "$STAMP" ]]; then
      ts="$(cat "$STAMP" 2>/dev/null || echo '?')"
      rm -f "$STAMP" "$MARKER"
      echo "crash-guard: clean boot (stamp $ts consumed) — GPU workloads start normally"
    else
      : > "$MARKER"
      echo "crash-guard: UNCLEAN reboot detected (no clean-shutdown stamp)"
      echo "crash-guard: dropped GPU-defer marker $MARKER"
      echo "crash-guard: GPU workloads will be HELD until 'just resume-gpu'"
    fi
    ;;
  shutdown)
    date -u +%Y-%m-%dT%H:%M:%SZ > "$STAMP"
    # fsync the stamp AND its directory entry before returning, so it survives the
    # reboot. The 2026-08-28 false-positive defer was an un-synced write that a
    # clean unmount still lost — do not rely on systemd's later global sync.
    sync "$STAMP" "$STATE_DIR" 2>/dev/null || sync
    echo "crash-guard: graceful shutdown — clean-shutdown stamp written + synced"
    ;;
  *)
    echo "usage: $0 {boot|shutdown}" >&2
    exit 2
    ;;
esac
