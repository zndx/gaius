#!/usr/bin/env bash
# engine-ready.sh — continuous out-of-band liveness watchdog for the gaius Engine.
#
# THE FAILURE CLASS (2026-08-29): the engine process dies, or wedges so :50051
# stops answering, while devenv process-compose still reports gaius-engine
# "ready". Every client (Kumo waterfall, CLI, MCP) fails and nothing recovers it —
# because the in-engine HealthObserver runs INSIDE the engine and dies with it.
# The detector for this class MUST be out-of-band. This is that detector.
#
# L0 of the SRE recovery ladder: a deterministic, mechanical restart. No reasoning.
# It complements the in-supervisor `availability.restart = "on_failure"` on the
# gaius-engine process (fast in-place relaunch on a clean crash): when that in-place
# path can't restore :50051 within SUSTAIN_S — a wedge, a process-compose daemon
# desync, or an exhausted in-place budget — this watchdog does a COMPLETE recycle
# of the whole unit (`systemctl restart gaius.service` → systemd_stop.sh reaps
# compose/engines/sentinels, then a clean re-up). Recovery is a recycle, NOT an
# idempotent ensure.
#
# Truth-probe: the SAME real Engine/Status RPC the readiness_probe uses
# (scripts/zndx_status_ok.py) — status is a liveness PROXY, so we probe the actual
# serving surface, not the reported process state.
#
# CRASH-LOOP BREAKER (the L0→L2 bridge, built here because none existed): a
# persistent, time-windowed recycle budget. After BUDGET_K complete recycles in the
# trailing BUDGET_WINDOW_S, STOP recycling (thrash guard), drop a breaker marker
# with context + emit guru #EN.00000017.SERVEDESYNC, and hand off to L2 — the
# in-engine `engine_serving` health check reads the marker and escalates to ACP for
# root-cause. The breaker is a fast-recovery guard, NOT a gate that withholds the
# agent; it auto-resets as old recycles age out of the window.
set -uo pipefail

# --- Paths (repo-relative so it works from /etc/systemd/system) ----------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="${GAIUS_ENGINE_READY_PY:-$REPO/.devenv/state/venv/bin/python}"
# Cheap raw-gRPC Status probe (~0.1s). NOT zndx_status_ok.py: importing the
# generated stubs drags in the whole engine (~6s CPU, ~885 MB) — far too heavy to
# run every poll. See scripts/engine_serving_probe.py.
STATUS_SCRIPT="${GAIUS_ENGINE_READY_PROBE:-$REPO/scripts/engine_serving_probe.py}"

# --- State (root disk, NOT /raid — same rationale as crash-guard) ---------------
STATE_DIR="${GAIUS_CRASH_STATE_DIR:-/var/lib/gaius}"
DEFER_MARKER="${GAIUS_DEFER_MARKER:-$STATE_DIR/defer-gpu}"
LEDGER="${GAIUS_ENGINE_RECYCLE_LEDGER:-$STATE_DIR/engine-recycles}"
BREAKER="${GAIUS_ENGINE_BREAKER:-$STATE_DIR/engine-breaker-tripped}"

# --- Tunables -------------------------------------------------------------------
POLL_S="${GAIUS_ENGINE_READY_POLL_S:-15}"
# Sustained :50051-DEAD (probe rc=2, gRPC UNAVAILABLE / connection refused) before a
# complete recycle. MUST exceed the legitimate 27B cold-reload window (~2.5-3 min
# via gpu_cleanup) AND give the in-supervisor availability.restart its in-place
# attempts — else a reload's port-down window reads as a dead engine. A merely SLOW
# Status (rc=3, DEADLINE) never counts here (the engine's Status is legitimately
# bimodal, ~0.15s but 20s+ under contention) — only definitive connection failure.
SUSTAIN_S="${GAIUS_ENGINE_READY_SUSTAIN_S:-300}"
# Outer kill-timeout for the probe; must exceed the probe's own RPC deadline (8s).
PROBE_TIMEOUT_S="${GAIUS_ENGINE_READY_PROBE_TIMEOUT_S:-12}"
# Recycle budget (crash-loop breaker).
BUDGET_K="${GAIUS_ENGINE_RECYCLE_BUDGET_K:-3}"
BUDGET_WINDOW_S="${GAIUS_ENGINE_RECYCLE_WINDOW_S:-3600}"
# After a recycle, pause dark-counting so the full recycle + cold reload can land.
RECYCLE_COOLDOWN_S="${GAIUS_ENGINE_RECYCLE_COOLDOWN_S:-240}"
# Consecutive OK time before we declare recovery and clear the breaker marker.
RECOVERY_CONFIRM_S="${GAIUS_ENGINE_RECOVERY_CONFIRM_S:-60}"
GURU="#EN.00000017.SERVEDESYNC"

log() { echo "engine-ready: $*"; }

# Returns the probe's exit code: 0 serving, 2 dead (UNAVAILABLE), 3 slow
# (DEADLINE — alive), 1/other unknown, 124 if the outer timeout fired.
run_probe() { timeout "$PROBE_TIMEOUT_S" "$PY" "$STATUS_SCRIPT" >/dev/null 2>&1; }

now() { date +%s; }

# Recycles within the trailing window, one epoch-second per line.
_prune_ledger() {
  local cutoff; cutoff=$(( $(now) - BUDGET_WINDOW_S ))
  [[ -f "$LEDGER" ]] || return 0
  local kept; kept="$(awk -v c="$cutoff" '$1+0 >= c' "$LEDGER" 2>/dev/null)"
  printf '%s\n' "$kept" | grep -v '^$' > "$LEDGER.tmp" 2>/dev/null || : > "$LEDGER.tmp"
  mv -f "$LEDGER.tmp" "$LEDGER"
}
_ledger_count() { [[ -f "$LEDGER" ]] && grep -cve '^$' "$LEDGER" || echo 0; }

_trip_breaker() {
  local n="$1"
  cat > "$BREAKER" <<EOF
{"guru":"$GURU","tripped_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","recycles_in_window":$n,"window_s":$BUDGET_WINDOW_S,"detail":"engine :50051 dark past sustain; recycle budget exhausted — handed to L2 for root-cause"}
EOF
  sync "$BREAKER" 2>/dev/null || true
  log "$GURU breaker TRIPPED: $n recycles in ${BUDGET_WINDOW_S}s — no further recycle this window; handing to L2 (ACP root-cause). marker=$BREAKER"
}

_do_recycle() {
  echo "$(now)" >> "$LEDGER"
  local n; n="$(_ledger_count)"
  log "$GURU :50051 dark >= ${SUSTAIN_S}s — COMPLETE recycle via the unit (recycle $n/$BUDGET_K this window)"
  systemctl restart --no-block gaius.service || log "WARN: gaius.service restart request failed"
}

log "watchdog up — probe=$STATUS_SCRIPT poll=${POLL_S}s sustain=${SUSTAIN_S}s budget=${BUDGET_K}/${BUDGET_WINDOW_S}s"

dead_s=0        # consecutive seconds :50051 has been DEAD (connection refused)
ok_s=0          # consecutive seconds :50051 has been cleanly SERVING
slow_ticks=0    # for light log throttling of the slow-but-alive state
while true; do
  # Respect an intentional GPU defer (crash-guard on an UNCLEAN boot): the engine
  # is held on purpose until `just resume-gpu`. Never recycle in that case.
  if [[ -e "$DEFER_MARKER" ]]; then
    dead_s=0; ok_s=0
    sleep "$POLL_S"; continue
  fi

  run_probe; rc=$?

  if (( rc == 0 )); then
    # Cleanly serving.
    dead_s=0
    ok_s=$(( ok_s + POLL_S ))
    slow_ticks=0
    # Sustained clean recovery clears a tripped breaker (symmetric with _trip).
    if [[ -e "$BREAKER" ]] && (( ok_s >= RECOVERY_CONFIRM_S )); then
      rm -f "$BREAKER"
      log "$GURU :50051 serving ${ok_s}s — breaker cleared, engine recovered"
    fi
    sleep "$POLL_S"; continue
  fi

  if (( rc != 2 )); then
    # rc=3 (slow/DEADLINE), rc=1 (other), rc=124 (outer timeout): the engine is
    # reachable/ambiguous, NOT connection-dead. Do NOT count toward a recycle — a
    # slow-but-alive engine must never be recycled. Reset the dead counter; hold
    # ok_s (slowness is not a clean recovery, so it won't clear a breaker).
    dead_s=0
    slow_ticks=$(( slow_ticks + 1 ))
    if (( slow_ticks == 1 || slow_ticks % 20 == 0 )); then
      log ":50051 reachable but not cleanly serving (probe rc=$rc, slow/degraded) — alive, not recycling"
    fi
    sleep "$POLL_S"; continue
  fi

  # rc == 2: :50051 is DEAD (connection refused / UNAVAILABLE) — the recycle signal.
  ok_s=0
  slow_ticks=0
  dead_s=$(( dead_s + POLL_S ))
  if (( dead_s < SUSTAIN_S )); then
    log ":50051 dead ${dead_s}/${SUSTAIN_S}s (in-supervisor availability.restart / cold-reload window)"
    sleep "$POLL_S"; continue
  fi

  # Sustained dead — the in-place path has not restored serving. Consider a recycle.
  _prune_ledger
  if (( $(_ledger_count) >= BUDGET_K )); then
    _trip_breaker "$(_ledger_count)"
    dead_s=0                       # stop spamming; re-evaluate after cooldown
    sleep "$RECYCLE_COOLDOWN_S"; continue
  fi

  _do_recycle
  dead_s=0
  sleep "$RECYCLE_COOLDOWN_S"      # let the recycle + 27B cold reload land
done
