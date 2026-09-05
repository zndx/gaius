#!/usr/bin/env bash
# `just restart` — the one restart by command: clean, controlled, agent-friendly.
#
# No arguments, no ceremony. Everything the procedure needs is derived from state:
#   • the objectives under remediation = every declared objective whose latest
#     verdict is FAIL (an objective declared with a quantitative criterion is
#     primary by construction — there is no flag);
#   • the change under test = the working tree's git rev;
#   • the context to carry over = those objectives with their failing gates and
#     evidence, the in-flight work, and the recent ACP sessions — written BEFORE
#     the restart so the fresh session resumes the remediation naturally, the way
#     any resumed session picks up where it left off.
#
# Procedure (memory: gaius-controlled-restart-window; progress doctrine: never
# cut a run that is delivering):
#   1. wait until no publish_cards slot is in flight (slots are not paused)
#   2. pause the five enqueuers (a trap re-enables them on ANY exit)
#   3. drain: no in-flight rows, no gaius.flows.* processes (net 45 min; past it
#      → re-enable and exit 3 "deferred", nothing restarted)
#   4. restart gaius.service (bare systemctl as root, sudo -n as the user)
#   5. verify: :50051, thinking HEALTHY, boot errors, EngineSupervision registered,
#      Nautilus resident, and `/objective verify` for every objective from step 0
#
# State: $GAIUS_STATE_DIR (default .devenv/state/gaius)/restarts/<UTC stamp>/
#   context.json  (written before the restart)   result.json  (written after)
#   …/restarts/latest → the newest run. The ACP rendezvous reads these
#   (docs/notes/2026-09-05/224300_acp_restart_rendezvous_protocol.md).
#
# Executor-only flags (not part of the command; the ACP request path sets them):
#   --free           skip 1–3: a declared objective is unmet, so the running
#                    system is not delivering and the restart costs nothing
#   --reason TEXT    --change-ref SHA    --request-id ID
#
# Exit: 0 restarted, every objective under remediation PASS · 2 could not pause
# enqueuers · 3 drain net passed (deferred) · 4 systemctl failed · 5 :50051 never
# came back · 6 restarted but an objective under remediation is not PASS.
set -uo pipefail

FREE=0 REASON="" CHANGE_REF="" REQUEST_ID="" DRAIN_NET_MIN="${GAIUS_RESTART_DRAIN_NET_MIN:-45}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --free) FREE=1; shift;;
    --reason) REASON="$2"; shift 2;;
    --change-ref) CHANGE_REF="$2"; shift 2;;
    --request-id) REQUEST_ID="$2"; shift 2;;
    --drain-net-min) DRAIN_NET_MIN="$2"; shift 2;;
    *) echo "unknown arg: $1 (just restart takes none)" >&2; exit 64;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PSQL="psql -h ${PGHOST:-127.0.0.1} -p ${PGPORT:-5444} -U gaius -d zndx_gaius -Atq"
export PGPASSWORD="${PGPASSWORD:-gaius}"
JOBS="'fmp-roll','ambient-synthesis','clt-skos-admit','clt-skos-label','feature-probe'"
CLI=".devenv/state/venv/bin/gaius-cli"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STATE_DIR="${GAIUS_STATE_DIR:-$ROOT/.devenv/state/gaius}/restarts/$STAMP"
mkdir -p "$STATE_DIR" && ln -sfn "$STATE_DIR" "$(dirname "$STATE_DIR")/latest"
ACP_LOG="$ROOT/build/dev/.gaius-acp-grok/logs/unified.jsonl"

ts() { date -u +%H:%M:%S; }
say() { echo "[$(ts)] restart: $*"; }
T_START=$(date +%s)
REV_BEFORE="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "")"
DIRTY="$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null | grep -c . || true)"
[[ -n "$CHANGE_REF" ]] || CHANGE_REF="$REV_BEFORE"
RESTARTED_AT="" RESTART_VIA="" PORT_UP_S="" THINKING_STATUS="" THINKING_S="" BOOT_ERRS="" SUPERVISION_REG="" REV_AFTER="" EXIT_CODE=0
(( EUID == 0 )) && say "running as root — not needed (polkit grants manage-units to $(stat -c %U "$ROOT")); state files will be handed back to the repo owner at the end"
OBJ_RESULTS="[]"

inflight() { $PSQL -c "select coalesce(string_agg(task_type||'#'||id||' '||to_char(now()-picked_up_at,'HH24:MI'), ', '),'') from scheduled_tasks where picked_up_at is not null and completed_at is null" 2>/dev/null; }
flows() { pgrep -af "python[0-9.]* -m gaius\.flows\." 2>/dev/null | grep -v "uv run" | cut -c1-110 | tr '\n' ';'; }

# 0. context: the objectives under remediation and what surrounds them
FAILING_JSON="$($PSQL -c "SELECT coalesce(json_agg(json_build_object('objective', objective_name, 'verdict', verdict, 'verified_at', started_at, 'gates', (SELECT json_agg(json_build_object('gate', g->>'gate', 'verdict', g->>'verdict', 'evidence', left(g->>'evidence', 400))) FROM jsonb_array_elements(gate_results) g WHERE g->>'verdict' <> 'pass'))), '[]') FROM (SELECT DISTINCT ON (objective_name) objective_name, verdict, started_at, gate_results FROM objective_verifications ORDER BY objective_name, started_at DESC) v WHERE verdict = 'fail'" 2>/dev/null || echo "[]")"
OBJECTIVES=$(python3 -c "import json,sys; print(' '.join(o['objective'] for o in json.loads(sys.argv[1])))" "$FAILING_JSON" 2>/dev/null || echo "")
python3 - "$STATE_DIR/context.json" "$FAILING_JSON" "$ACP_LOG" "$REASON" "$CHANGE_REF" "$REV_BEFORE" "$DIRTY" "$REQUEST_ID" "$FREE" "$(inflight)" "$(flows)" <<'EOF'
import json, sys, datetime, os
out, failing, acp_log, reason, change_ref, rev, dirty, request_id, free, inflight, flows = sys.argv[1:12]
sessions = {}
try:
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    with open(acp_log, "rb") as fh:
        fh.seek(max(0, os.path.getsize(acp_log) - 8_000_000))
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = str(d.get("ts", ""))[:19]
            if t < cutoff or not d.get("sid"):
                continue
            s = sessions.setdefault(d["sid"], {"first": t, "last": t, "events": 0})
            s["last"] = t; s["events"] += 1
except FileNotFoundError:
    pass
json.dump({
    "kind": "gaius.restart.context", "stamp": os.path.basename(os.path.dirname(out)),
    "requested_at": datetime.datetime.utcnow().isoformat() + "Z",
    "request_id": request_id or None, "reason": reason or "just restart",
    "mode": "free" if free == "1" else "controlled",
    "change_ref": change_ref, "rev_before": rev, "working_tree_dirty_files": int(dirty or 0),
    "objectives_under_remediation": json.loads(failing or "[]"),
    "inflight_before": inflight, "flows_before": flows,
    "acp_sessions_recent_2h": sessions,
    "resume_hint": "Re-open the ACP session with objectives_under_remediation as the task: "
                   "verify each with /objective verify <name> after HEALTHY; PASS → keep/PR, FAIL → revert.",
}, open(out, "w"), indent=1)
EOF
say "context → $STATE_DIR/context.json (rev $REV_BEFORE, dirty files $DIRTY, objectives under remediation: ${OBJECTIVES:-none})"

emit_result() {
  python3 - "$STATE_DIR/result.json" "$OBJ_RESULTS" <<EOF
import json, sys, datetime
json.dump({
  "kind": "gaius.restart.result", "stamp": "$STAMP", "request_id": "$REQUEST_ID" or None,
  "mode": "free" if $FREE else "controlled", "reason": """$REASON""" or "just restart",
  "change_ref": "$CHANGE_REF", "rev_before": "$REV_BEFORE", "engine_rev_after": "$REV_AFTER" or None,
  "exit_code": $EXIT_CODE,
  "started_at": datetime.datetime.utcfromtimestamp($T_START).isoformat() + "Z",
  "restarted_at": "$RESTARTED_AT" or None, "restart_via": "$RESTART_VIA" or None,
  "port_up_s": ${PORT_UP_S:-None}, "thinking_status": "$THINKING_STATUS" or None,
  "thinking_healthy_s": ${THINKING_S:-None}, "boot_errors": ${BOOT_ERRS:-None},
  "supervision_registered": ${SUPERVISION_REG:-None},
  "objectives": json.loads(sys.argv[2]),
  "finished_at": datetime.datetime.utcnow().isoformat() + "Z",
}, open(sys.argv[1], "w"), indent=1)
EOF
  say "result → $STATE_DIR/result.json (exit $EXIT_CODE)"
  # If someone ran this under sudo anyway, hand the state back to the repo owner
  # so the next `just restart` as the user can write beside it.
  if (( EUID == 0 )); then chown -R --reference="$ROOT" "$(dirname "$STATE_DIR")" 2>/dev/null || true; fi
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

if [[ $FREE == 0 ]]; then
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
  say "free: a declared objective is unmet, nothing is protected — restarting now (in flight: $(inflight))"
fi

# 4. restart — no sudo by design: polkit grants manage-units to the operator via
# scripts/systemd/50-gaius-units.pkla (`just reboot-hardening-install`). The old
# `sudo -n` was an unexamined habit that happened to be load-bearing before the
# rule existed (polkit 0.105: "Interactive authentication required" from any
# non-interactive caller). If the rule is missing we escalate ONCE, loudly.
t0=$(date +%s); RESTARTED_AT="$(date -u +%FT%TZ)"
RESTART_VIA="systemctl"
say "restarting gaius.service (systemctl restart, no sudo)"
if ! systemctl --no-ask-password restart gaius.service; then
  rc=$?
  if (( EUID != 0 )) && sudo -n true 2>/dev/null; then
    say "systemctl restart refused (rc $rc): polkit does not grant manage-units to $(id -un) — run \`just reboot-hardening-install\`; escalating once with sudo -n"
    RESTART_VIA="sudo"
    if ! sudo -n systemctl restart gaius.service; then say "systemctl restart FAILED under sudo too (rc $?)"; EXIT_CODE=4; exit 4; fi
  else
    say "systemctl restart FAILED (rc $rc) and no non-interactive sudo available"; EXIT_CODE=4; exit 4
  fi
fi
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
# grep -c prints the count AND exits 1 when it is 0, so `|| echo 0` yields "0\n0"
# and broke the result JSON on the first run (23:49 2026-09-05). Take the count as
# printed; default only when grep produced nothing (missing log).
BOOT_ERRS=$(grep -cE "Traceback|ImportError" "$ENGINE_LOG" 2>/dev/null); BOOT_ERRS=${BOOT_ERRS:-0}
SUPERVISION_REG=$(grep -c "Registered zndx.supervision.v1.EngineSupervision" "$ENGINE_LOG" 2>/dev/null); SUPERVISION_REG=${SUPERVISION_REG:-0}
REV_AFTER=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "")
say "engine log: boot errors=$BOOT_ERRS EngineSupervision registered=$SUPERVISION_REG rev=$REV_AFTER"
for _ in $(seq 1 30); do
  external/nautilus/target/release/nautilus status --target 127.0.0.1:50061 --quiet 2>/dev/null && break
  sleep 10
done
external/nautilus/target/release/nautilus status --target 127.0.0.1:50061 2>&1 | head -3 | sed "s/^/[$(ts)] nautilus: /"

for name in $OBJECTIVES; do
  out=$($CLI --cmd "/objective verify $name" --format json 2>/dev/null)
  verdict=$(echo "$out" | jq -r '.data.results[0].verdict // "unreadable"' 2>/dev/null)
  gates=$(echo "$out" | jq -c '[.data.results[0].gates[]? | {gate, verdict, evidence: (.evidence|tostring|.[0:300])}]' 2>/dev/null || echo "[]")
  say "objective $name: $verdict"
  OBJ_RESULTS=$(python3 -c "import json,sys; a=json.loads(sys.argv[1]); a.append({'objective': sys.argv[2], 'verdict': sys.argv[3], 'gates': json.loads(sys.argv[4] or '[]')}); print(json.dumps(a))" "$OBJ_RESULTS" "$name" "$verdict" "$gates")
  [[ "$verdict" == "pass" ]] || EXIT_CODE=6
done
if (( EXIT_CODE == 6 )); then say "restarted; an objective under remediation is not PASS — the resumed session decides"; exit 6; fi
say "complete"
