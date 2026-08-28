#!/usr/bin/env bash
# thinking-ready.sh — post-boot watchdog for the baseline GPU workload.
#
# On a clean boot the engine preloads thinking, but its admission can lose the
# ~1min post-reboot yunikorn stabilization race, and nothing re-admits it (the
# ambient loop only logs NOHEALTHY). If thinking is not serving within the
# deadline, do a COMPLETE recycle of the gaius unit: `systemctl restart` runs
# systemd_stop.sh (which reaps the MiNIFi sentinel pods) then re-runs the boot
# preload from a clean slate. Bounded retries come from the unit's Restart=.
#
# Recovery is a complete process recycle, NOT an idempotent ensure — a half-dead
# or stuck endpoint is torn down and brought up fresh.
set -uo pipefail

MARKER="${GAIUS_DEFER_MARKER:-/var/lib/gaius/defer-gpu}"
PORT="${GAIUS_THINKING_PORT:-8081}"
DEADLINE_S="${GAIUS_THINKING_READY_DEADLINE_S:-360}"   # > a normal admit + vLLM load
POLL_S="${GAIUS_THINKING_READY_POLL_S:-15}"

log() { echo "thinking-ready: $*"; }

# Respect an intentional GPU defer (crash-guard on an UNCLEAN boot): thinking is
# held on purpose until `just resume-gpu`. Never recycle in that case.
if [[ -e "$MARKER" ]]; then
  log "GPU-defer marker present ($MARKER) — thinking intentionally held; no recycle"
  exit 0
fi

deadline=$(( SECONDS + DEADLINE_S ))
while (( SECONDS < deadline )); do
  if curl -sf -o /dev/null --max-time 4 "http://127.0.0.1:${PORT}/health"; then
    log "thinking vLLM serving on :${PORT} — baseline up ($(( SECONDS ))s)"
    exit 0
  fi
  # A defer marker can appear mid-wait (operator or a re-detected crash) — honor it.
  if [[ -e "$MARKER" ]]; then
    log "GPU-defer marker appeared mid-wait — no recycle"
    exit 0
  fi
  sleep "$POLL_S"
done

log "thinking not serving within ${DEADLINE_S}s — COMPLETE recycle via the unit"
systemctl restart --no-block gaius.service || log "WARN: gaius restart request failed"
# Non-zero exit triggers the unit's Restart=on-failure for a bounded retry.
exit 1
