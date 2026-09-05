#!/usr/bin/env bash
# Engine restart under policy — the procedure behind the "controlled window"
# (memory: gaius-controlled-restart-window) promoted from the sweep scratchpad,
# and the FREE mode the 2026-09-05 doctrine adds: when a primary objective is
# unmet the running system is not delivering, so a restart costs nothing and
# the drain is skipped. Progress doctrine still holds in controlled mode: never
# cut a run that is delivering.
#
#   scripts/restart_window.sh [--mode controlled|free] [--label TEXT]
#                             [--reason TEXT] [--change-ref SHA]
#                             [--objective NAME] [--result-json PATH]
#                             [--drain-net-min N] [--engine-log PATH]
#
# controlled: 1. wait until no publish_cards slot is in flight (slots are not paused)
#             2. pause the five enqueuers (a trap re-enables them on ANY exit)
#             3. drain: no in-flight rows, no gaius.flows.* processes (net 45 min;
#                past it → re-enable, exit 3 "deferred")
#             4. restart gaius.service   5. verify
# free:       4. restart gaius.service   5. verify
#
# verify: :50051 listening, thinking HEALTHY, boot errors in the engine log,
#         EngineSupervision registered, Nautilus resident status, and — when
#         --objective is given — `/objective verify <name>` on the live surface.
# --result-json writes one JSON object with every measurement so a harness (the
# ACP restart rendezvous, docs/notes/2026-09-05/235000_acp_restart_rendezvous_protocol.md)
# can resolve the restart forecast without parsing prose.
#
# Exit codes: 0 restarted+verified · 2 could not pause enqueuers · 3 drain net
# passed (deferred, nothing restarted) · 4 systemctl failed · 5 :50051 never came
# back · 6 objective verify did not PASS (restart happened; caller decides revert).
set -uo pipefail

MODE=controlled LABEL="" REASON="" CHANGE_REF="" OBJECTIVE="" RESULT_JSON="" DRAIN_NET_MIN=45
ENGINE_LOG="${ENGINE_LOG:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2;;
    --label) LABEL="$2"; shift 2;;
    --reason) REASON="$2"; shift 2;;
    --change-ref) CHANGE_REF="$2"; shift 2;;
    --objective) OBJECTIVE="$2"; shift 2;;
    --result-json) RESULT_JSON="$2"; shift 2;;
    --drain-net-min) DRAIN_NET_MIN="$2"; shift 2;;
    --engine-log) ENGINE_LOG="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 64;;
  esac
done
[[ "$MODE" == "controlled" || "$MODE" == "free" ]] || { echo "--mode must be controlled|free" >&2; exit 64; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PGHOST_="${PGHOST:-127.0.0.1}"; PGPORT_="${PGPORT:-5444}"
PSQL="psql -h $PGHOST_ -p $PGPORT_ -U gaius -d zndx_gaius -Atq"
export PGPASSWORD="${PGPASSWORD:-gaius}"
JOBS="'fmp-roll','ambient-synthesis','clt-skos-admit','clt-skos-label','feature-probe'"
CLI=".devenv/state/venv/bin/gaius-cli"
if [[ -z "$ENGINE_LOG" ]]; then
  ENGINE_LOG="$(ls -t /run/user/1001/devenv-*/processes/logs/gaius-engine.stderr.log 2>/dev/null | head -1)"
fi

ts() { date -u +%H:%M:%S; }
say() { echo "[$(ts)] ${LABEL:+$LABEL: }$*"; }
T_START=$(date +%s)
RESTARTED_AT="" PORT_UP_S="" THINKING_STATUS="" THINKING_S="" BOOT_ERRS="" SUPERVISION_REG="" OBJ_VERDICT="" OBJ_GATES="" REV_AFTER="" EXIT_CODE=0

emit_result() {
  [[ -n "$RESULT_JSON" ]] || return 0
  python3 - "$RESULT_JSON" <<EOF
import json, sys, datetime
json.dump({
  "mode": "$MODE", "label": "$LABEL", "reason": """$REASON""", "change_ref": "$CHANGE_REF",
  "objective": "$OBJECTIVE", "exit_code": $EXIT_CODE,
  "started_at": datetime.datetime.utcfromtimestamp($T_START).isoformat() + "Z",
  "restarted_at": "$RESTARTED_AT" or None,
  "port_up_s": ${PORT_UP_S:-None}, "thinking_status": "$THINKING_STATUS" or None,
  "thinking_healthy_s": ${THINKING_S:-None}, "boot_errors": ${BOOT_ERRS:-None},
  "supervision_registered": ${SUPERVISION_REG:-None},
  "objective_verdict": "$OBJ_VERDICT" or None, "objective_gates": "$OBJ_GATES" or None,
  "engine_rev_after": "$REV_AFTER" or None,
  "finished_at": datetime.datetime.utcnow().isoformat() + "Z",
}, open(sys.argv[1], "w"), indent=1)
EOF
  say "result written to $RESULT_JSON"
}

PAUSED=0
reenable() {
  if [[ $PAUSED == 1 ]]; then
    for _ in 1 2 3 4 5 6; do
      if $PSQL -c "UPDATE cron.job SET active=true WHERE jobname IN ($JOBS)" >/dev/null 2>&1; then
        say "enqueuers re-enabled"; PAUSED=0; break
      fi
      sleep 20
    done
    [[ $PAUSED == 1 ]] && say "FAILED to re-enable enqueuers — run: UPDATE cron.job SET active=true WHERE jobname IN ($JOBS)"
  fi
  emit_result
}
trap reenable EXIT

inflight() { $PSQL -c "select coalesce(string_agg(task_type||'#'||id||' '||to_char(now()-picked_up_at,'HH24:MI'), ', '),'') from scheduled_tasks where picked_up_at is not null and completed_at is null" 2>/dev/null; }
flows() { pgrep -af "python[0-9.]* -m gaius\.flows\." 2>/dev/null | grep -v "uv run" | cut -c1-110 | tr '\n' ';'; }

say "mode=$MODE${REASON:+ reason=$REASON}${CHANGE_REF:+ change_ref=$CHANGE_REF}${OBJECTIVE:+ objective=$OBJECTIVE}"

if [[ "$MODE" == "controlled" ]]; then
  # 1. no publish_cards slot in flight
  n=0
  while true; do
    pc=$($PSQL -c "select count(*) from scheduled_tasks where task_type='publish_cards' and picked_up_at is not null and completed_at is null" 2>/dev/null || echo "?")
    [[ "$pc" == "0" ]] && break
    n=$((n+1)); (( n % 10 == 1 )) && say "publish_cards slot in flight ($pc) — waiting (in flight: $(inflight))"
    sleep 60
  done
  say "no publish_cards slot in flight — opening the window"

  # 2. pause enqueuers
  if $PSQL -c "UPDATE cron.job SET active=false WHERE jobname IN ($JOBS)" >/dev/null; then PAUSED=1; say "enqueuers paused"; else say "could not pause enqueuers; aborting"; EXIT_CODE=2; exit 2; fi

  # 3. drain
  start=$(date +%s)
  while true; do
    rows=$(inflight); procs=$(flows)
    [[ -z "$rows" && -z "$procs" ]] && break
    el=$(( ($(date +%s) - start) / 60 ))
    if (( el >= DRAIN_NET_MIN )); then say "drain net ($DRAIN_NET_MIN min) passed with work still alive: rows=[$rows] procs=[$procs] — deferred"; EXIT_CODE=3; exit 3; fi
    (( el % 5 == 0 )) && say "draining ${el} min: rows=[$rows] procs=[$procs]"
    sleep 60
  done
  say "drained"
else
  say "free mode: primary objective unmet, nothing to protect — restarting now (in flight: $(inflight))"
fi

# 4. restart
t0=$(date +%s); RESTARTED_AT="$(date -u +%FT%TZ)"
if (( EUID == 0 )); then RESTART_CMD="systemctl restart gaius.service"; else RESTART_CMD="sudo -n systemctl restart gaius.service"; fi
say "restarting gaius.service ($RESTART_CMD)"
if ! $RESTART_CMD; then say "systemctl restart FAILED (rc $?)"; EXIT_CODE=4; exit 4; fi
for _ in $(seq 1 60); do nc -z 127.0.0.1 50051 2>/dev/null && break; sleep 10; done
if ! nc -z 127.0.0.1 50051 2>/dev/null; then say ":50051 not listening after 10 min — journalctl -u gaius.service"; EXIT_CODE=5; exit 5; fi
PORT_UP_S=$(( $(date +%s) - t0 )); say ":50051 up after ${PORT_UP_S}s; waiting for thinking HEALTHY"
st=""
for _ in $(seq 1 90); do
  st=$($CLI --cmd "/gpu status" --format json 2>/dev/null | jq -r '.data.endpoints[]? | select(.name=="thinking") | .status' 2>/dev/null | head -1)
  [[ "$st" == "HEALTHY" || "$st" == "PROCESS_STATUS_HEALTHY" ]] && break
  sleep 10
done
THINKING_STATUS="${st:-unknown}"; THINKING_S=$(( $(date +%s) - t0 )); say "thinking status: $THINKING_STATUS after ${THINKING_S}s"

# 5. verify
ENGINE_LOG="$(ls -t /run/user/1001/devenv-*/processes/logs/gaius-engine.stderr.log 2>/dev/null | head -1)"
BOOT_ERRS=$(grep -cE "Traceback|ImportError" "$ENGINE_LOG" 2>/dev/null || echo 0)
SUPERVISION_REG=$(grep -c "Registered zndx.supervision.v1.EngineSupervision" "$ENGINE_LOG" 2>/dev/null || echo 0)
REV_AFTER=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "")
say "engine log: boot errors=$BOOT_ERRS EngineSupervision registered=$SUPERVISION_REG rev=$REV_AFTER"
for _ in $(seq 1 30); do
  external/nautilus/target/release/nautilus status --target 127.0.0.1:50061 --quiet 2>/dev/null && break
  sleep 10
done
external/nautilus/target/release/nautilus status --target 127.0.0.1:50061 2>&1 | head -3 | sed "s/^/[$(ts)] nautilus: /"
if [[ -n "$OBJECTIVE" ]]; then
  out=$($CLI --cmd "/objective verify $OBJECTIVE" --format json 2>/dev/null)
  OBJ_VERDICT=$(echo "$out" | jq -r '.data.results[0].verdict // empty' 2>/dev/null)
  OBJ_GATES=$(echo "$out" | jq -r '[.data.results[0].gates[]? | "\(.gate)=\(.verdict)"] | join(" ")' 2>/dev/null)
  say "objective $OBJECTIVE: ${OBJ_VERDICT:-unreadable} ($OBJ_GATES)"
  if [[ "$OBJ_VERDICT" != "pass" ]]; then EXIT_CODE=6; say "restart complete; objective not PASS — caller decides revert"; exit 6; fi
fi
say "restart window complete"
