"""Directives the resident Nautilus sends over EngineSupervision.Supervise, and
what the engine does with them.

Nautilus never kills. It measures SILENCE since a task's last progress signal and
asks the engine to release an orphaned claim (``ReclaimOrphan``); it detects what
determinism cannot settle and asks the engine's Overwatch judge (``Escalation``);
it announces Backlog channel crossings (``BacklogTransition``). The engine owns
every side effect and re-checks every precondition — a heartbeat that landed after
the supervisor's snapshot voids a reclaim; a child the engine knows to be alive
refuses it — and records each directive as a FORECAST in the efficacy ledger (the
engine stays the ledger's single writer). Delivery is at-least-once: results are
answered from ``supervision_directives`` on a resend, never re-applied.

Adoption doctrine (observe → score → promote): ``GAIUS_SUPERVISION_ACTUATE`` defaults
to off, so a reclaim records its forecast (``side_effect='reclaim_dry_run'``) and
performs no UPDATE until Nautilus's Brier record earns the promotion.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from gaius.engine.services.supervision_bus import KIND_DIRECTIVE_RESULT, KIND_TASK, get_bus

logger = logging.getLogger(__name__)

GURU_LIVERUN = "#SV.00000005.LIVERUN"
GURU_NOTINFLIGHT = "#SV.00000006.NOTINFLIGHT"
GURU_SILENCE = "#SV.00000007.SILENCE"
GURU_DRYRUN = "#SV.00000008.DRYRUN"
GURU_UNKNOWNDIRECTIVE = "#SV.00000009.UNKNOWNDIRECTIVE"

OBSERVER_RECLAIM = "watchdog:nautilus.reclaim"
CALL_SITE = "supervision_directives"

# The pg_cron watchdog's class split, kept as the floor when the instance has no
# net for a class (mechanics scale: seconds; never F-rounded here).
LONG_CLASSES = {"article_curate", "prospects_update", "publish_cards", "objective_verify"}
NET_LONG_S = 4 * 3600
NET_DEFAULT_S = 45 * 60


def actuate_enabled() -> bool:
    return (os.environ.get("GAIUS_SUPERVISION_ACTUATE") or "").strip().lower() in ("1", "true", "yes", "on")


def _now_ms() -> int:
    return int(time.time() * 1000)


class DirectiveHandler:
    def __init__(self, pool: Any, *, judge: Any = None, processor: Any = None) -> None:
        self._pool = pool
        self._judge = judge
        self._processor = processor  # ScheduledTaskProcessor: live-run knowledge

    # ── entry ───────────────────────────────────────────────────────────────
    async def handle(self, directive_id: str, kind: str, body: dict[str, Any], *, session_id: int | None = None) -> dict[str, Any]:
        """Dispatch one directive; idempotent on directive_id. Returns the result dict
        (accepted, applied, note, forecast_id, judge_status)."""
        prior = await self._prior_result(directive_id)
        if prior is not None:
            return {**prior, "note": (prior.get("note") or "") + " (replayed answer)"}
        if kind == "reclaim_orphan":
            result = await self.reclaim_orphan(directive_id, body)
        elif kind == "escalation":
            result = await self.escalation(directive_id, body)
        elif kind == "backlog_transition":
            result = await self.backlog_transition(directive_id, body)
        else:
            result = {"accepted": False, "applied": False, "note": f"{GURU_UNKNOWNDIRECTIVE} {kind}", "forecast_id": "", "judge_status": ""}
        await self._remember(directive_id, kind, result, session_id)
        return result

    async def _prior_result(self, directive_id: str) -> dict[str, Any] | None:
        if not directive_id:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT accepted, applied, forecast_id, result FROM supervision_directives WHERE directive_id = $1::uuid",
                    directive_id,
                )
        except Exception:  # noqa: BLE001 — a malformed id is not a prior result
            return None
        if row is None:
            return None
        res = row["result"] or {}
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:  # noqa: BLE001
                res = {}
        return {
            "accepted": bool(row["accepted"]),
            "applied": bool(row["applied"]),
            "forecast_id": str(row["forecast_id"] or ""),
            "note": str(res.get("note") or ""),
            "judge_status": str(res.get("judge_status") or ""),
        }

    async def _remember(self, directive_id: str, kind: str, result: dict[str, Any], session_id: int | None) -> None:
        if not directive_id:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO supervision_directives (directive_id, kind, session_id, accepted, applied, forecast_id, result)
                    VALUES ($1::uuid, $2, $3, $4, $5, NULLIF($6,'')::uuid, $7::jsonb)
                    ON CONFLICT (directive_id) DO NOTHING
                    """,
                    directive_id, kind, session_id, bool(result.get("accepted")), bool(result.get("applied")),
                    str(result.get("forecast_id") or ""), json.dumps(result, default=str),
                )
        except Exception:  # noqa: BLE001 — bookkeeping only
            logger.debug("supervision_directives insert skipped", exc_info=True)

    # ── ReclaimOrphan ───────────────────────────────────────────────────────
    def _net_seconds(self, task_type: str) -> int:
        try:
            from gaius.engine.supervision_spec import load_spec

            spec = load_spec()
            if spec is not None:
                p = spec.process(f"task.{task_type}")
                if p is not None and p.HasField("cadence") and p.cadence.net_seconds:
                    return int(p.cadence.net_seconds)
        except Exception:  # noqa: BLE001
            pass
        return NET_LONG_S if task_type in LONG_CLASSES else NET_DEFAULT_S

    def _live_child(self, task_id: int, workload_id: str) -> bool:
        proc = self._processor
        try:
            if proc is not None and task_id in getattr(proc, "_inflight_ids", set()):
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            from gaius.engine.flow_processes import flow_processes

            row = flow_processes().get(workload_id) if workload_id else None
            if row is not None and getattr(getattr(row, "proc", None), "returncode", 0) is None:
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    async def reclaim_orphan(self, directive_id: str, body: dict[str, Any]) -> dict[str, Any]:
        task_id = int(body.get("task_id") or 0)
        task_type = str(body.get("task_type") or "")
        silence_ms = int(body.get("silence_ms") or 0)
        claimed_progress_ms = int(body.get("last_progress_unix_ms") or 0)
        dry_run = bool(body.get("dry_run")) or not actuate_enabled()
        net_s = self._net_seconds(task_type)
        engine_rev = self._engine_rev()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, task_type, picked_up_at, heartbeat_at, completed_at, result FROM scheduled_tasks WHERE id = $1",
                task_id,
            )
        if row is None or row["picked_up_at"] is None or row["completed_at"] is not None:
            return {"accepted": True, "applied": False, "note": f"{GURU_NOTINFLIGHT} task {task_id} is not in flight", "forecast_id": "", "judge_status": ""}
        task_type = task_type or str(row["task_type"])
        result = row["result"] or {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:  # noqa: BLE001
                result = {}
        wid = str(result.get("workload_id") or "") if isinstance(result, dict) else ""
        last_progress = row["heartbeat_at"] or row["picked_up_at"]
        last_progress_ms = int(last_progress.timestamp() * 1000)
        engine_silence_ms = _now_ms() - last_progress_ms

        # Guard 1 — a live child the supervisor cannot see: refuse, and score the
        # supervisor's false positive as a PASS forecast against the live table.
        if self._live_child(task_id, wid):
            fid = await self._forecast(task_type, task_id, "pass", 0.85, "reclaim_refused", engine_rev,
                                       {"directive_id": directive_id, "nautilus_silence_ms": silence_ms, "engine_silence_ms": engine_silence_ms, "reason": "live child"})
            return {"accepted": True, "applied": False, "note": f"{GURU_LIVERUN} task {task_id} has a live child", "forecast_id": fid, "judge_status": ""}
        # Guard 2 — silence: the supervisor's claim must be at least as old as what
        # the engine sees, and past the class net.
        if (claimed_progress_ms and last_progress_ms > claimed_progress_ms) or engine_silence_ms < net_s * 1000:
            fid = await self._forecast(task_type, task_id, "pass", 0.85, "reclaim_refused", engine_rev,
                                       {"directive_id": directive_id, "nautilus_silence_ms": silence_ms, "engine_silence_ms": engine_silence_ms, "net_s": net_s, "reason": "heartbeat resumed"})
            return {"accepted": True, "applied": False, "note": f"{GURU_SILENCE} progress {engine_silence_ms // 1000}s ago < net {net_s}s", "forecast_id": fid, "judge_status": ""}
        if dry_run:
            fid = await self._forecast(task_type, task_id, "fail", 0.15, "reclaim_dry_run", engine_rev,
                                       {"directive_id": directive_id, "nautilus_silence_ms": silence_ms, "engine_silence_ms": engine_silence_ms, "net_s": net_s})
            return {"accepted": True, "applied": False, "note": f"{GURU_DRYRUN} would reset task {task_id} (silent {engine_silence_ms // 1000}s > net {net_s}s)", "forecast_id": fid, "judge_status": ""}

        # Applied: one CTE — forecast + reset, precondition re-checked in SQL.
        async with self._pool.acquire() as conn:
            done = await conn.fetchrow(
                """
                WITH victim AS (
                  SELECT id, task_type, picked_up_at, heartbeat_at
                    FROM scheduled_tasks
                   WHERE id = $1 AND picked_up_at IS NOT NULL AND completed_at IS NULL
                     AND COALESCE(heartbeat_at, picked_up_at) < NOW() - make_interval(secs => $2)
                   FOR UPDATE SKIP LOCKED
                ), forecast AS (
                  INSERT INTO probe_forecasts (observer, call_site, observer_kind, proposition, verdict, p,
                                               evidence, side_effect, task_class, task_id, task_lifecycle, engine_rev)
                  SELECT $3, $4, 'watchdog', 'a live worker owns task ' || v.id, 'fail', 0.15,
                         jsonb_build_object('picked_up_at', v.picked_up_at, 'heartbeat_at', v.heartbeat_at,
                                            'silence_minutes', ROUND(EXTRACT(EPOCH FROM (NOW() - COALESCE(v.heartbeat_at, v.picked_up_at)))/60),
                                            'directive_id', $5::text, 'net_s', $2),
                         'watchdog_reset', v.task_type, v.id, 'CLAIMED', $6
                    FROM victim v RETURNING forecast_id
                )
                UPDATE scheduled_tasks st
                   SET picked_up_at = NULL, heartbeat_at = NULL,
                       error = 'reset by watchdog: stuck running (nautilus)'
                  FROM victim v WHERE st.id = v.id
                RETURNING st.id, (SELECT forecast_id FROM forecast) AS forecast_id
                """,
                task_id, float(net_s), OBSERVER_RECLAIM, CALL_SITE + ".reclaim_orphan", directive_id, engine_rev,
            )
        if done is None:
            return {"accepted": True, "applied": False, "note": f"{GURU_SILENCE} precondition changed under us (heartbeat or completion landed)", "forecast_id": "", "judge_status": ""}
        fid = str(done["forecast_id"] or "")
        bus = get_bus()
        if bus is not None:
            bus.publish(KIND_TASK, task_id=task_id, task_type=task_type, state="RESET", reason="orphan",
                        error=f"reclaimed by nautilus [{directive_id}]", source="", workload_id=wid,
                        scheduled_for_unix_ms=0, picked_up_unix_ms=0, heartbeat_unix_ms=0, completed_unix_ms=0)
        return {"accepted": True, "applied": True, "note": f"reset task {task_id} (silent {engine_silence_ms // 1000}s > net {net_s}s)", "forecast_id": fid, "judge_status": ""}

    async def _forecast(self, task_type: str, task_id: int, verdict: str, p: float, side_effect: str, engine_rev: str, evidence: dict[str, Any]) -> str:
        try:
            async with self._pool.acquire() as conn:
                fid = await conn.fetchval(
                    """
                    INSERT INTO probe_forecasts (observer, call_site, observer_kind, proposition, verdict, p,
                                                 evidence, side_effect, task_class, task_id, task_lifecycle, engine_rev)
                    VALUES ($1, $2, 'watchdog', $3, $4, $5, $6::jsonb, $7, $8, $9, 'CLAIMED', $10)
                    RETURNING forecast_id
                    """,
                    OBSERVER_RECLAIM, CALL_SITE + ".reclaim_orphan", f"a live worker owns task {task_id}", verdict, p,
                    json.dumps(evidence, default=str), side_effect, task_type, task_id, engine_rev,
                )
            return str(fid or "")
        except Exception:  # noqa: BLE001 — ledger is fail-open
            logger.debug("reclaim forecast skipped", exc_info=True)
            return ""

    @staticmethod
    def _engine_rev() -> str:
        try:
            from gaius.engine.services.efficacy_ledger import get_ledger

            ledger = get_ledger()
            rev = getattr(ledger, "engine_rev", None) if ledger is not None else None
            if rev:
                return str(rev)
        except Exception:  # noqa: BLE001
            pass
        return "unknown"

    # ── Escalation (the typed Overwatch consult) ────────────────────────────
    async def escalation(self, directive_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from gaius.engine.services.overwatch_events import SOURCE_RESIDENT, record_trigger

        trigger = str(body.get("trigger") or "")
        scope = str(body.get("scope") or "")
        report_only = bool(body.get("report_only"))
        evidence = {"directive_id": directive_id, "signature": str(body.get("signature") or ""), "report_only": report_only,
                    "backlog_slot": int(body.get("backlog_slot") or 0), "position": body.get("position") or {}}
        ledger_report = None
        try:
            from gaius.engine.services.efficacy_ledger import get_ledger

            ledger = get_ledger()
            if ledger is not None and not report_only:
                ledger_report = await ledger.report()
        except Exception:  # noqa: BLE001
            ledger_report = None
        out = await record_trigger(
            self._pool, self._judge, trigger=trigger, scope=scope, detail=str(body.get("detail") or ""),
            evidence=evidence, snapshot_markdown=str(body.get("snapshot_markdown") or ""),
            ledger_report=ledger_report, consult=not report_only, source=SOURCE_RESIDENT,
        )
        return {"accepted": True, "applied": bool(out.get("consulted")), "note": f"overwatch_events#{out.get('event_id')} {out.get('action_taken')}",
                "forecast_id": "", "judge_status": str(out.get("judge_status") or "")}

    # ── BacklogTransition (channel emission; Stage 5 wires the Agenda) ──────
    async def backlog_transition(self, directive_id: str, body: dict[str, Any]) -> dict[str, Any]:
        # Stage 1–4: record the crossing loudly; the Agenda/Reminder/briefing
        # emitters land in Stage 5. The forecast below is the Backlog Objective's
        # measurement seed ("surfaced before horizon").
        workflow = str(body.get("workflow") or "")
        slot = int(body.get("slot") or 0)
        horizon_ms = int(body.get("horizon_unix_ms") or 0)
        before_horizon = horizon_ms == 0 or _now_ms() <= horizon_ms
        logger.warning("#SV.00000014.BACKLOG %s slot %d state %s channel %s%s", workflow, slot,
                       body.get("state"), body.get("channel"), " (resolved)" if body.get("resolved") else "")
        fid = ""
        try:
            async with self._pool.acquire() as conn:
                fid = await conn.fetchval(
                    """
                    INSERT INTO probe_forecasts (observer, call_site, observer_kind, proposition, verdict, p,
                                                 evidence, side_effect, task_class, engine_rev)
                    VALUES ('objective:ops_backlog.surfaced', $1, 'objective', $2, $3, $4, $5::jsonb, $6, $7, $8)
                    RETURNING forecast_id
                    """,
                    CALL_SITE + ".backlog_transition",
                    f"item {body.get('item_key') or workflow} surfaced on {body.get('channel')} before F{slot}",
                    "pass" if before_horizon else "fail", 0.85 if before_horizon else 0.15,
                    json.dumps({k: body.get(k) for k in ("workflow", "item_key", "slot", "state", "category", "channel", "first_miss_unix_ms", "horizon_unix_ms", "resolved")}, default=str),
                    "channel_pending", workflow.replace("task.", ""), self._engine_rev(),
                )
        except Exception:  # noqa: BLE001
            logger.debug("backlog transition forecast skipped", exc_info=True)
        return {"accepted": True, "applied": False, "note": "recorded; channel emission lands in Stage 5", "forecast_id": str(fid or ""), "judge_status": ""}
