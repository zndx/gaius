"""One writer for trigger firings — shared by the in-engine NautilusService (retiring)
and the resident Nautilus's directives over EngineSupervision.Supervise.

Both paths render the same kind of firing (a model-free trigger over the engine's
mechanics) and both may consult the Overwatch judge (ACP + an independent model,
fail-closed, budgeted, a process singleton). Before 2026-09-04 the only writer was
``NautilusService._dispatch``; factoring it here means the observe-phase comparison
between the two supervisors is a GROUP BY on ``overwatch_events.source``, and the
retirement of the in-engine daemon deletes a caller, not a code path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

GURU_TRIGGER = "#OW.00000006.TRIGGER"
GURU_EVTFAIL = "#OW.00000007.EVTFAIL"

SOURCE_INENGINE = "engine.nautilus"
SOURCE_RESIDENT = "nautilus.rs"


async def record_trigger(
    pool: Any,
    judge: Any,
    *,
    trigger: str,
    scope: str,
    detail: str,
    evidence: dict[str, Any] | None,
    snapshot_markdown: str,
    ledger_report: Any = None,
    consult: bool,
    source: str,
) -> dict[str, Any]:
    """Record one firing; consult the judge when asked. Returns
    ``{event_id, judge_status, judge_verdict, action_taken, consulted}``.

    Never raises for the bookkeeping write (``#OW.00000007.EVTFAIL`` logged); a
    judge failure is the judge's own fail-closed status, recorded as such.
    """
    logger.warning("%s %s [%s] (%s): %s", GURU_TRIGGER, trigger, scope, source, detail)
    judge_payload: dict[str, Any] = {"status": "not_invoked"}
    if consult:
        if judge is None:
            judge_payload = {"status": "judge_unavailable"}
        else:
            try:
                judge_payload = await judge.consult(
                    trigger=trigger,
                    scope=scope,
                    detail=detail,
                    snapshot_markdown=snapshot_markdown,
                    ledger_report=ledger_report,
                )
            except Exception as e:  # noqa: BLE001 — fail-closed judge, honest status
                judge_payload = {"status": "judge_error", "error": str(e)[:300]}
    elif evidence and evidence.get("report_only"):
        judge_payload = {"status": "report_only"}

    action = "recorded"
    verdict = judge_payload.get("verdict")
    if isinstance(verdict, dict) and not verdict.get("in_contract", True):
        # v1 monitor tier: proposals are recorded for the operator; nothing executes.
        action = f"reported:{verdict.get('recommended_action', 'report')}"

    event_id: int | None = None
    try:
        async with pool.acquire() as conn:
            event_id = await conn.fetchval(
                """
                INSERT INTO overwatch_events (
                    trigger_name, scope, detail, snapshot,
                    judge_invoked, judge_status, judge_verdict, action_taken, source
                ) VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7::jsonb,$8,$9)
                RETURNING id
                """,
                trigger,
                scope,
                detail,
                json.dumps(evidence or {}, default=str),
                bool(consult),
                judge_payload.get("status"),
                json.dumps(verdict, default=str) if verdict else None,
                action,
                source,
            )
    except Exception:  # noqa: BLE001
        logger.exception("%s overwatch_events write failed", GURU_EVTFAIL)
    return {
        "event_id": event_id,
        "judge_status": judge_payload.get("status"),
        "judge_verdict": verdict,
        "action_taken": action,
        "consulted": bool(consult),
    }
