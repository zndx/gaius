"""zndx.supervision.v1.EngineSupervision — the engine-hosted supervision stream.

The resident Nautilus DIALS this service (the engine serves it): one bidirectional
stream per supervisor. Sequence per connection:

1. the first message must be ``Subscribe`` (``#SV.00000003.NOSUBSCRIBE``);
2. subscribe to the in-process bus BEFORE replay (no gap), open a
   ``supervision_sessions`` row, send ``EngineHello``;
3. replay ``[since, now]`` from the engine's tables (or the bus ring when the
   supervisor resumes inside this engine session), then ``ReplayComplete``;
4. a reader task pumps the supervisor's directives to ``DirectiveHandler`` and
   answers each with a per-session ``DirectiveResult``; the main loop yields live
   events, heartbeating every 30 s when nothing happened;
5. a newer ``Subscribe`` with the same ``supervisor_id`` supersedes the old stream
   (``Goodbye{SUPERSEDED}``).

Modeled on ``GaiusZndxEngineServicer.WatchWorkload`` (publisher queue + heartbeat
on timeout). Events carry SOURCE timestamps; ``seq`` is the per-session gap
detector. The engine runs identically with no supervisor connected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator

import grpc
from google.protobuf.json_format import MessageToDict
from grpc import aio

from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv
from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2_grpc as sv_grpc
from gaius.engine.services.supervision_bus import (
    KIND_ADMISSION,
    KIND_DIRECTIVE_RESULT,
    KIND_INCIDENT,
    KIND_OBJECTIVE,
    KIND_POSITION,
    KIND_SERVING,
    KIND_TASK,
    SupervisionEvent,
    get_bus,
    init_bus,
)
from gaius.engine.services.supervision_replay import replay_events

logger = logging.getLogger(__name__)

GURU_NOSUBSCRIBE = "#SV.00000003.NOSUBSCRIBE"
GURU_NOBACKLOG = "#SV.00000010.NOBACKLOG"
GURU_NOPOOL = "#SV.00000015.NOPOOL"

HEARTBEAT_S = 30.0
KIND_GOODBYE = "goodbye"

_TASK_STATE = {
    "QUEUED": sv.TASK_STATE_QUEUED, "CLAIMED": sv.TASK_STATE_CLAIMED, "HEARTBEAT": sv.TASK_STATE_HEARTBEAT,
    "COMPLETED": sv.TASK_STATE_COMPLETED, "DEFERRED": sv.TASK_STATE_DEFERRED, "FAILED": sv.TASK_STATE_FAILED,
    "ERROR": sv.TASK_STATE_ERROR, "STALLED": sv.TASK_STATE_STALLED, "YIELDED": sv.TASK_STATE_YIELDED,
    "SKIPPED": sv.TASK_STATE_SKIPPED, "RESET": sv.TASK_STATE_RESET,
}
_ADMISSION = {
    "PENDING": sv.ADMISSION_PHASE_PENDING, "ADMITTED": sv.ADMISSION_PHASE_ADMITTED,
    "NOTADMITTED": sv.ADMISSION_PHASE_NOTADMITTED, "RETIRED": sv.ADMISSION_PHASE_RETIRED,
}
_VERDICT = {"PASS": sv.VERDICT_PASS, "FAIL": sv.VERDICT_FAIL, "INCONCLUSIVE": sv.VERDICT_INCONCLUSIVE, "ERROR": sv.VERDICT_ERROR}
_INCIDENT = {
    "ACTIVE": sv.INCIDENT_STATE_ACTIVE, "HEALING": sv.INCIDENT_STATE_HEALING, "RECOVERING": sv.INCIDENT_STATE_RECOVERING,
    "RESOLVED": sv.INCIDENT_STATE_RESOLVED, "MANUAL_REQUIRED": sv.INCIDENT_STATE_MANUAL_REQUIRED,
}
_SERVING = {"serving": sv.SERVING_STATUS_SERVING, "starting": sv.SERVING_STATUS_STARTING, "degraded": sv.SERVING_STATUS_DEGRADED,
            "failed": sv.SERVING_STATUS_FAILED, "absent": sv.SERVING_STATUS_ABSENT}


def _pool_of(services: Any) -> Any:
    for name in ("db_pool", "pool", "_db_pool"):
        p = getattr(services, name, None)
        if p is not None:
            return p
    getter = getattr(services, "get_db_pool", None)
    return getter() if callable(getter) else None


def _engine_rev() -> str:
    try:
        from gaius.engine.services.efficacy_ledger import get_ledger

        ledger = get_ledger()
        rev = getattr(ledger, "engine_rev", None) if ledger is not None else None
        if rev:
            return str(rev)
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("GAIUS_ENGINE_REV") or "unknown"


def event_to_proto(ev: SupervisionEvent, epoch: str) -> sv.EngineEvent:
    """Bus payload (flat dict) → EngineEvent. Unknown kinds become an empty event."""
    p = ev.payload
    out = sv.EngineEvent(seq=ev.seq, at_unix_ms=ev.at_unix_ms, epoch=epoch, replayed=ev.replayed)
    if ev.kind == KIND_TASK:
        out.task.CopyFrom(sv.TaskLifecycle(
            task_id=int(p.get("task_id") or 0), task_type=str(p.get("task_type") or ""),
            state=_TASK_STATE.get(str(p.get("state") or ""), sv.TASK_STATE_UNSPECIFIED),
            reason=str(p.get("reason") or ""), error=str(p.get("error") or "")[:300], source=str(p.get("source") or ""),
            scheduled_for_unix_ms=int(p.get("scheduled_for_unix_ms") or 0), picked_up_unix_ms=int(p.get("picked_up_unix_ms") or 0),
            heartbeat_unix_ms=int(p.get("heartbeat_unix_ms") or 0), completed_unix_ms=int(p.get("completed_unix_ms") or 0),
            workload_id=str(p.get("workload_id") or ""),
            evidence={str(k): str(v) for k, v in (p.get("evidence") or {}).items()},
        ))
    elif ev.kind == KIND_ADMISSION:
        out.admission.CopyFrom(sv.AdmissionEvent(
            workload_id=str(p.get("workload_id") or ""), kind=str(p.get("kind") or ""), leaf=str(p.get("leaf") or ""),
            phase=_ADMISSION.get(str(p.get("phase") or ""), sv.ADMISSION_PHASE_UNSPECIFIED),
            wait_ms=int(p.get("wait_ms") or 0), net_ms=int(p.get("net_ms") or 0), priority=int(p.get("priority") or 0),
            holders=[str(h) for h in (p.get("holders") or [])], task_id=int(p.get("task_id") or 0),
        ))
    elif ev.kind == KIND_POSITION:
        out.position.CopyFrom(sv.PositionReport(
            position=sv.Position(process=str(p.get("process") or ""), machine=str(p.get("machine") or ""),
                                 phase=str(p.get("phase") or ""), run_id=str(p.get("run_id") or ""),
                                 step=str(p.get("step") or ""), momentum=int(p.get("momentum") or 0),
                                 source=sv.POSITION_SOURCE_INFERRED, at_unix_ms=ev.at_unix_ms, epoch=epoch),
            detail=str(p.get("detail") or ""),
        ))
    elif ev.kind == KIND_OBJECTIVE:
        out.objective.CopyFrom(sv.ObjectiveVerdict(
            objective=str(p.get("objective") or ""), run_id=str(p.get("run_id") or ""),
            verdict=_VERDICT.get(str(p.get("verdict") or "").upper(), sv.VERDICT_UNSPECIFIED),
            gates_passed=int(p.get("gates_passed") or 0), gates_total=int(p.get("gates_total") or 0),
            judge_rendered=bool(p.get("judge_rendered")), awaits=str(p.get("awaits") or ""),
            started_unix_ms=int(p.get("started_unix_ms") or 0), completed_unix_ms=int(p.get("completed_unix_ms") or 0),
            gates=[sv.GateResult(name=str(g.get("name") or ""), verdict=_VERDICT.get(str(g.get("verdict") or "").upper(), sv.VERDICT_UNSPECIFIED),
                                 detail=str(g.get("detail") or "")[:300]) for g in (p.get("gates") or []) if isinstance(g, dict)],
        ))
    elif ev.kind == KIND_INCIDENT:
        out.incident.CopyFrom(sv.IncidentEvent(
            fingerprint=str(p.get("fingerprint") or ""), state=_INCIDENT.get(str(p.get("state") or "").upper(), sv.INCIDENT_STATE_UNSPECIFIED),
            tier=int(p.get("tier") or 0), endpoint=str(p.get("endpoint") or ""), failure_mode=str(p.get("failure_mode") or ""),
            sequence_id=str(p.get("sequence_id") or ""), sequence_num=int(p.get("sequence_num") or 0), event_type=str(p.get("event_type") or ""),
        ))
    elif ev.kind == KIND_SERVING:
        out.serving.CopyFrom(sv.ServingEvent(
            phase=sv.SERVING_PHASE_SETTLED if str(p.get("phase") or "") == "settled" else sv.SERVING_PHASE_TRANSITIONING,
            generation=int(p.get("generation") or 0), capability=str(p.get("capability") or ""), alias=str(p.get("alias") or ""),
            model=str(p.get("model") or ""), actual=_SERVING.get(str(p.get("actual") or "").lower(), sv.SERVING_STATUS_UNSPECIFIED),
            warmup_seconds=int(p.get("warmup_seconds") or 0), settled_unix_ms=int(p.get("settled_unix_ms") or 0),
        ))
    elif ev.kind == KIND_DIRECTIVE_RESULT:
        out.directive_result.CopyFrom(sv.DirectiveResult(
            directive_id=str(p.get("directive_id") or ""), accepted=bool(p.get("accepted")), applied=bool(p.get("applied")),
            note=str(p.get("note") or "")[:500], forecast_id=str(p.get("forecast_id") or ""), judge_status=str(p.get("judge_status") or ""),
            at_unix_ms=ev.at_unix_ms,
        ))
    elif ev.kind == KIND_GOODBYE:
        out.goodbye.CopyFrom(sv.Goodbye(reason=int(p.get("reason") or sv.GOODBYE_REASON_UNSPECIFIED), note=str(p.get("note") or "")))
    return out


class EngineSupervisionServicer(sv_grpc.EngineSupervisionServicer):
    def __init__(self, services: Any) -> None:
        self._services = services
        self._sessions: dict[str, asyncio.Queue] = {}  # supervisor_id -> live queue

    # ── helpers ─────────────────────────────────────────────────────────────
    def _epoch(self) -> tuple[str, str, str]:
        spec_version, sha = "", ""
        try:
            from gaius.engine.supervision_spec import load_spec

            spec = load_spec()
            if spec is not None:
                spec_version, sha = spec.spec_version, spec.sha256
        except Exception:  # noqa: BLE001
            pass
        rev = _engine_rev()
        return f"{spec_version}+{rev}", spec_version, sha

    def _handler(self, pool: Any):
        from gaius.engine.services.supervision_directives import DirectiveHandler

        judge = None
        try:
            from gaius.engine.services.overwatch_judge import get_judge

            judge = get_judge()
        except Exception:  # noqa: BLE001
            judge = None
        proc = getattr(self._services, "scheduled_task_processor", None)
        return DirectiveHandler(pool, judge=judge, processor=proc)

    async def _open_session(self, pool: Any, sub: sv.Subscribe, peer: str) -> int | None:
        try:
            async with pool.acquire() as conn:
                return await conn.fetchval(
                    """
                    INSERT INTO supervision_sessions (peer, supervisor_id, supervisor_epoch, since_unix_ms, last_heartbeat_at)
                    VALUES ($1, $2, $3, $4, NOW()) RETURNING id
                    """,
                    peer[:200], sub.supervisor_id[:200], f"{sub.spec_version}+{sub.spec_sha256[:12]}", int(sub.since_unix_ms),
                )
        except Exception:  # noqa: BLE001
            logger.debug("supervision_sessions open skipped", exc_info=True)
            return None

    async def _touch_session(self, pool: Any, sid: int | None, **cols: Any) -> None:
        if sid is None or not cols:
            return
        sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(cols))
        try:
            async with pool.acquire() as conn:
                await conn.execute(f"UPDATE supervision_sessions SET {sets}, last_heartbeat_at = NOW() WHERE id = $1", sid, *cols.values())
        except Exception:  # noqa: BLE001
            logger.debug("supervision_sessions touch skipped", exc_info=True)

    async def _close_session(self, pool: Any, sid: int | None, reason: str) -> None:
        if sid is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE supervision_sessions SET disconnected_at = NOW(), goodbye_reason = $2 WHERE id = $1", sid, reason)
        except Exception:  # noqa: BLE001
            logger.debug("supervision_sessions close skipped", exc_info=True)

    # ── the stream ──────────────────────────────────────────────────────────
    async def Supervise(self, request_iterator: AsyncIterator[sv.SupervisorMessage], context: aio.ServicerContext):
        pool = _pool_of(self._services)
        if pool is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"{GURU_NOPOOL} engine database pool unavailable")
            return
        try:
            first = await request_iterator.__anext__()
        except StopAsyncIteration:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"{GURU_NOSUBSCRIBE} stream closed before Subscribe")
            return
        if first.WhichOneof("message") != "subscribe":
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"{GURU_NOSUBSCRIBE} first message must be Subscribe")
            return
        sub = first.subscribe
        epoch, spec_version, spec_sha = self._epoch()
        project = os.environ.get("GAIUS_PROJECT", "gaius")
        if sub.project and sub.project != project:
            yield sv.EngineEvent(seq=0, at_unix_ms=int(time.time() * 1000), epoch=epoch,
                                 goodbye=sv.Goodbye(reason=sv.GOODBYE_REASON_PROJECT_MISMATCH, note=f"engine project is {project}"))
            return

        bus = get_bus() or init_bus()
        q = bus.subscribe()
        old = self._sessions.get(sub.supervisor_id)
        if old is not None and old is not q:
            bus.publish_to(old, KIND_GOODBYE, reason=sv.GOODBYE_REASON_SUPERSEDED, note=f"superseded by a newer Subscribe from {sub.supervisor_id}")
        self._sessions[sub.supervisor_id] = q
        peer = context.peer() if hasattr(context, "peer") else ""
        sid = await self._open_session(pool, sub, peer)
        logger.info("supervision: session %s opened (%s) since=%s resume=%s/%s", sid, sub.supervisor_id, sub.since_unix_ms, sub.resume_session, sub.resume_seq)
        sent = 0
        goodbye_reason = "closed"
        reader: asyncio.Task | None = None
        try:
            yield sv.EngineEvent(seq=0, at_unix_ms=int(time.time() * 1000), epoch=epoch, hello=sv.EngineHello(
                project=project, engine_build=_engine_rev(), spec_version=spec_version, spec_sha256=spec_sha,
                boot_unix_ms=int(bus.session * 1000), session=int(bus.session), engine_grpc=os.environ.get("GAIUS_ENGINE_GRPC", "127.0.0.1:50051"),
                capabilities=["replay:scheduled_tasks", "replay:objective_verifications", "replay:healing_events",
                              "directive:reclaim_orphan", "directive:escalation", "directive:backlog_transition"],
            ))
            # Replay: ring fast path inside the same engine session, else tables.
            replayed: list[SupervisionEvent] | None = None
            meta: dict[str, Any] = {"clamped": False, "tables": []}
            if sub.resume_session and int(sub.resume_session) == int(bus.session):
                replayed = bus.ring_since(int(sub.resume_seq))
                if replayed is not None:
                    meta = {"clamped": False, "tables": ["ring"], "since_unix_ms": int(sub.since_unix_ms)}
            if replayed is None:
                if int(sub.since_unix_ms) > 0:
                    replayed, meta = await replay_events(pool, int(sub.since_unix_ms))
                else:
                    replayed, meta = [], {"clamped": False, "tables": [], "since_unix_ms": 0}
            for ev in replayed:
                yield event_to_proto(ev, epoch)
                sent += 1
            yield sv.EngineEvent(seq=bus.seq, at_unix_ms=int(time.time() * 1000), epoch=epoch, replay_complete=sv.ReplayComplete(
                since_unix_ms=int(meta.get("since_unix_ms") or 0), through_seq=bus.seq, events=len(replayed),
                tables=[str(t) for t in meta.get("tables", [])], clamped=bool(meta.get("clamped")),
            ))
            await self._touch_session(pool, sid, replay_rows=len(replayed))

            handler = self._handler(pool)
            reader = asyncio.create_task(self._pump(request_iterator, q, handler, sid, pool))
            last_touch = time.monotonic()
            while not context.cancelled():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield self._heartbeat(bus, epoch)
                    if time.monotonic() - last_touch > 60:
                        await self._touch_session(pool, sid, events_sent=sent)
                        last_touch = time.monotonic()
                    continue
                yield event_to_proto(ev, epoch)
                sent += 1
                if ev.kind == KIND_GOODBYE:
                    goodbye_reason = "superseded"
                    break
                if reader.done():
                    goodbye_reason = "supervisor closed"
                    break
        finally:
            if reader is not None and not reader.done():
                reader.cancel()
            bus.unsubscribe(q)
            if self._sessions.get(sub.supervisor_id) is q:
                self._sessions.pop(sub.supervisor_id, None)
            await self._touch_session(pool, sid, events_sent=sent)
            await self._close_session(pool, sid, goodbye_reason)
            logger.info("supervision: session %s closed (%s): %d events", sid, sub.supervisor_id, sent)

    def _heartbeat(self, bus: Any, epoch: str) -> sv.EngineEvent:
        proc = getattr(self._services, "scheduled_task_processor", None)
        claimed = len(getattr(proc, "_inflight_ids", ()) or ()) if proc is not None else 0
        return sv.EngineEvent(seq=bus.seq, at_unix_ms=int(time.time() * 1000), epoch=epoch, heartbeat=sv.EngineHeartbeat(
            at_unix_ms=int(time.time() * 1000), last_seq=bus.seq, claimed_tasks=claimed,
        ))

    async def _pump(self, request_iterator: AsyncIterator[sv.SupervisorMessage], q: asyncio.Queue, handler: Any, sid: int | None, pool: Any) -> None:
        """Read the supervisor's messages until it closes; answer directives per session."""
        bus = get_bus()
        sem = asyncio.Semaphore(1)
        received = accepted = refused = 0
        try:
            async for msg in request_iterator:
                which = msg.WhichOneof("message")
                if which == "ack":
                    await self._touch_session(pool, sid, directives_received=received)
                    continue
                if which == "heartbeat":
                    await self._touch_session(pool, sid, directives_received=received)
                    continue
                if which == "subscribe":
                    continue  # re-subscribe on an open stream is ignored; a new stream supersedes
                if which in ("reclaim_orphan", "escalation", "backlog_transition"):
                    received += 1
                    body = MessageToDict(getattr(msg, which), preserving_proto_field_name=True, including_default_value_fields=False)
                    async with sem:
                        result = await handler.handle(msg.directive_id, which, body, session_id=sid)
                    if result.get("accepted"):
                        accepted += 1
                    else:
                        refused += 1
                    if bus is not None:
                        bus.publish_to(q, KIND_DIRECTIVE_RESULT, directive_id=msg.directive_id, **result)
                    await self._touch_session(pool, sid, directives_received=received, directives_accepted=accepted, directives_refused=refused)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a dropped stream is the supervisor's observation
            logger.info("supervision: reader ended: %s", e)

    # ── Backlog read-through (still answers when the supervisor is dark) ────
    async def Backlog(self, request: sv.BacklogRequest, context: aio.ServicerContext) -> sv.BacklogResponse:
        pool = _pool_of(self._services)
        if pool is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"{GURU_NOPOOL} engine database pool unavailable")
            return sv.BacklogResponse()
        from gaius.engine.services.backlog_read import read_backlog

        epoch, _, _ = self._epoch()
        live = bool(self._sessions)
        try:
            return await read_backlog(pool, request, epoch=epoch, supervisor_connected=live)
        except Exception as e:  # noqa: BLE001
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"{GURU_NOBACKLOG} {e}")
            return sv.BacklogResponse()
