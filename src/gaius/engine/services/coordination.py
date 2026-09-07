"""Coordination Activities — the gaius engine's view of inter-project intent.

An Activity (``zndx.engine.v1.Activity``) is intent with a lifetime, declared by
a peer ENGINE to the Signals engine and materialised by Signals as a run of its
own Airflow DAG. The gaius engine is the peer that WATCHES Signals
(``Scheduler/WatchActivities``); everything below the engine — flows, the CLI,
the resident Nautilus — reads the view from THIS engine (``Engine/ServerQuery
kind=ACTIVITIES``, ``EngineSupervision`` ``ActivityEvent``) and never connects
to Signals or Airflow. Two hops, never one.

What the engine does with an Activity (protocol spec
``specification/protocol/coordination_activities.md``):

- **Cede.** A RUNNING activity with posture ``gaius.endpoint.<alias>: hold-uptime``
  cedes that endpoint's intent (owner, activity, horizon): the orchestrator does
  not chase its uptime, the workload profile carries no unmet intent for it, the
  root watchdog sees nothing to recycle. A healthy ceded endpoint keeps running.
  When the activity ends the desired set is restored.
- **Admit around it.** ``precludes[]`` names YK leaves nothing may be admitted
  into while the activity runs; ``sentinel_claim.apply_and_admit`` defers those
  classes (``#YK.00000012.PRECLUDED``) — leaves not named keep admitting.
- **Tell the supervisor.** Every transition the engine observes is a
  ``KIND_ACTIVITY`` bus event (→ ``ActivityEvent``) with ``ceded[]`` naming this
  engine's process ids held by it.

Every watch event REPLACES the view (absence = ended). The horizon is the
safety: an activity whose ``horizon_ns`` has passed is dropped — and its cession
restored — even while Signals is dark. A silent stream (> 150 s) is a dead
stream and is redialled; a Signals that predates the Activity RPCs
(UNIMPLEMENTED) is logged once and retried every 5 min.

- **Run our own.** (2026-09-07) Airflow ORDERS workloads: a scheduled Airflow run
  declares an activity at Signals with ``peer=gaius`` and ``kind=<workload>``
  whose ``claims[]`` are the workload's YuniKorn queue configuration; Signals
  asserts those claims into the arbiter while the run is in force. When THIS
  engine sees its own activity RUNNING it starts the workload exactly as
  pg_cron would (one ``scheduled_tasks`` row — the row is the memory, so a
  repeated event or an engine restart never double-runs), heartbeats the lease
  every 60 s while the row is queued or in flight, and RELEASES the activity
  when the row books a terminal outcome — which completes the Airflow ``hold``
  sensor and retracts the queue configuration. A deferral (YuniKorn
  backpressure) is retried while the activity is in force; a workload of the
  same class already in flight is ATTACHED (its completion releases the
  activity) rather than run twice beside pg_cron.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

GURU_NOACTIVITIES = "#CO.00000001.NOACTIVITIES"   # Signals predates Scheduler/WatchActivities
GURU_STREAMDROP = "#CO.00000002.STREAMDROP"       # the watch stream ended / failed
GURU_SILENT = "#CO.00000003.SILENT"               # no event (not even a heartbeat) for SILENCE_S
GURU_NOWATCHER = "#CO.00000004.NOWATCHER"         # watcher not running (disabled or booting)
GURU_RENEWFAIL = "#CO.00000006.RENEWFAIL"         # lease heartbeat refused/unreachable (retry next pass)
GURU_RELEASEFAIL = "#CO.00000007.RELEASEFAIL"     # release refused/unreachable (the lease TTL expires it)
GURU_ENQUEUEFAIL = "#CO.00000008.ENQUEUEFAIL"     # could not start/attach the workload row

# ── workloads Airflow orders (kind → how pg_cron enqueued the same class) ─────
# The payload and the gate are pg_cron's `article-curate-daily` job VERBATIM
# (`INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
#  SELECT 'article_curate', '{"check_cooldown": true}', 'pg_cron', NOW()
#  WHERE collections.should_run_curation()`) so the Airflow-declared run and
# the cron-declared run are the same workload to the processor. A gate that
# says no releases the activity as "skipped" — the Airflow run closes clean.
WORKLOAD_KINDS: dict[str, dict[str, Any]] = {
    "article_curate": {
        "task_type": "article_curate",
        "payload": {"check_cooldown": True},
        "gate_sql": "SELECT collections.should_run_curation()",
    },
}
# Classes whose schedule now lives in the Signals Airflow (ServerQuery SCHEDULES
# reports source=airflow for them; pg_cron stays the source for the rest).
AIRFLOW_SOURCED_CLASSES: dict[str, str] = {"article_curate": "gaius_article_curate"}
WORKLOAD_SOURCE = "airflow"
WORKLOAD_HEARTBEAT_S = 60.0          # Signals' lease TTL is 180 s
WORKLOAD_HORIZON_S = 2 * 3600.0      # each heartbeat re-sets the horizon this far ahead
WORKLOAD_RETRY_S = 120.0             # a deferred/yielded row is re-enqueued after this while in force
# Terminal outcomes that release the activity. deferred/yielded are NOT terminal
# for an Airflow-ordered workload: the cadence that would retry them is gone, so
# the watcher re-enqueues while the activity is in force.
RELEASE_STATUSES = frozenset({"completed", "failed", "error", "stalled", "skipped"})
RETRY_STATUSES = frozenset({"deferred", "yielded"})
RPC_TIMEOUT_S = 15.0

PROJECT = "gaius"
POSTURE_HOLD_UPTIME = "hold-uptime"
KIND_ACTIVITY = "activity"  # supervision bus kind (mirrored in supervision_bus)

# ActivityState enum → the lowercase vocabulary ActivityEvent.state carries.
STATE_NAMES = {
    0: "unspecified",
    1: "queued",
    2: "running",
    3: "released",
    4: "expired",
    5: "failed",
    6: "superseded",
}
IN_FORCE = frozenset({"queued", "running"})
TERMINAL = frozenset({"released", "expired", "failed", "superseded"})

# Signals emits at least every 60 s; five quiet reads of 30 s = a dead stream.
READ_TIMEOUT_S = 30.0
SILENCE_S = 150.0
BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 60.0
UNIMPLEMENTED_RETRY_S = 300.0


def signals_target() -> str:
    """Same resolution as queue_share._addr(): the Signals engine's lattice port."""
    return (
        os.environ.get("SIGNALS_ENGINE_GRPC")
        or os.environ.get("SIGNALS_ENGINE_TARGET")
        or "127.0.0.1:50551"
    )


def now_ns() -> int:
    return time.time_ns()


# ── proto ↔ dict ─────────────────────────────────────────────────────────────
def activity_to_dict(a: Any) -> dict[str, Any]:
    """zndx.engine.v1.Activity → flat, JSON-safe dict (the view's unit)."""
    state = a.state
    return {
        "activity_id": str(a.activity_id),
        "kind": str(a.kind),
        "peer": str(a.peer),
        "owner": str(a.owner),
        "dag_id": str(a.dag_id),
        "run_id": str(a.run_id),
        "state": STATE_NAMES.get(int(state), "unspecified") if isinstance(state, int) else str(state),
        "declared_ns": int(a.declared_ns),
        "horizon_ns": int(a.horizon_ns),
        "renewed_ns": int(a.renewed_ns),
        "ended_ns": int(a.ended_ns),
        "claims": [{"leaf": str(c.leaf), "gpu": int(c.gpu)} for c in a.claims],
        "precludes": [str(p) for p in a.precludes],
        "postures": {str(k): str(v) for k, v in a.postures.items()},
        "reason": str(a.reason),
        "note": str(a.note),
    }


def dict_to_proto(d: dict[str, Any]) -> Any:
    """Flat dict → zndx.engine.v1.Activity (for ServerQuery kind=ACTIVITIES)."""
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    state_num = next((k for k, v in STATE_NAMES.items() if v == str(d.get("state") or "")), 0)
    a = zpb.Activity(
        activity_id=str(d.get("activity_id") or ""),
        kind=str(d.get("kind") or ""),
        peer=str(d.get("peer") or ""),
        owner=str(d.get("owner") or ""),
        dag_id=str(d.get("dag_id") or ""),
        run_id=str(d.get("run_id") or ""),
        state=state_num,
        declared_ns=int(d.get("declared_ns") or 0),
        horizon_ns=int(d.get("horizon_ns") or 0),
        renewed_ns=int(d.get("renewed_ns") or 0),
        ended_ns=int(d.get("ended_ns") or 0),
        precludes=[str(p) for p in (d.get("precludes") or [])],
        reason=str(d.get("reason") or ""),
        note=str(d.get("note") or ""),
    )
    for c in d.get("claims") or []:
        a.claims.add(leaf=str(c.get("leaf") or ""), gpu=int(c.get("gpu") or 0))
    for k, v in (d.get("postures") or {}).items():
        a.postures[str(k)] = str(v)
    return a


# ── pure view logic ──────────────────────────────────────────────────────────
def hold_aliases(view: dict[str, dict[str, Any]], project: str = PROJECT) -> dict[str, str]:
    """alias → activity_id for every RUNNING activity holding one of OUR endpoints."""
    prefix = f"{project}.endpoint."
    out: dict[str, str] = {}
    for aid, a in view.items():
        if a.get("state") != "running":
            continue
        for key, val in (a.get("postures") or {}).items():
            if key.startswith(prefix) and str(val) == POSTURE_HOLD_UPTIME:
                alias = key[len(prefix):]
                if alias:
                    out.setdefault(alias, aid)
    return out


def precluded(view: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """leaf FQN → the RUNNING activity precluding it (first wins)."""
    out: dict[str, dict[str, Any]] = {}
    for a in view.values():
        if a.get("state") != "running":
            continue
        for leaf in a.get("precludes") or []:
            out.setdefault(str(leaf), a)
    return out


@dataclass
class CoordinationView:
    """The engine's replaceable picture of every activity Signals showed it.

    Pure: ``replace``/``sweep`` return the transitions they imply; the watcher
    turns those into bus events and cessions. Testable without gRPC.
    """

    project: str = PROJECT
    activities: dict[str, dict[str, Any]] = field(default_factory=dict)
    observed_ns: int = 0

    def replace(self, incoming: list[dict[str, Any]], at_ns: int) -> list[tuple[dict[str, Any], str]]:
        """Adopt a full snapshot; return [(activity, transition)] for what changed."""
        out: list[tuple[dict[str, Any], str]] = []
        new: dict[str, dict[str, Any]] = {}
        for a in incoming:
            aid = str(a.get("activity_id") or "")
            if not aid:
                continue
            a = dict(a)
            # Horizon safety: in-force past its horizon is expired, whatever Signals says.
            if a.get("state") in IN_FORCE and 0 < int(a.get("horizon_ns") or 0) <= at_ns:
                a["state"] = "expired"
                a["ended_ns"] = a.get("ended_ns") or at_ns
            new[aid] = a

        for aid, a in new.items():
            old = self.activities.get(aid)
            st = a.get("state")
            if old is None:
                if st == "running":
                    out.append((a, "started"))
                elif st in TERMINAL:
                    out.append((a, st))
                else:
                    out.append((a, "observed"))
                continue
            if a.get("run_id") != old.get("run_id") and st in IN_FORCE:
                out.append((a, "renewed"))
            elif old.get("state") != st:
                if st == "running":
                    out.append((a, "started"))
                elif st in TERMINAL:
                    out.append((a, st))
                else:
                    out.append((a, "observed"))
        for aid, old in self.activities.items():
            if aid not in new and old.get("state") in IN_FORCE:
                # Signals stopped showing an in-force activity: it ended. Before
                # its horizon that is a release; at/after it an expiry. The
                # transition vocabulary is shared with Hermes's engine:
                # declared | observed | started | renewed | released | expired | failed.
                gone = dict(old)
                horizon = int(gone.get("horizon_ns") or 0)
                gone["state"] = "expired" if 0 < horizon <= at_ns else "released"
                gone["ended_ns"] = at_ns
                out.append((gone, gone["state"]))
        # Keep terminal activities Signals still shows (its trailing window);
        # drop the ones it stopped showing.
        self.activities = new
        self.observed_ns = at_ns
        return out

    def sweep(self, at_ns: int) -> list[tuple[dict[str, Any], str]]:
        """Expire in-force activities past their horizon without new data (Signals dark)."""
        out: list[tuple[dict[str, Any], str]] = []
        for a in self.activities.values():
            if a.get("state") in IN_FORCE and 0 < int(a.get("horizon_ns") or 0) <= at_ns:
                a["state"] = "expired"
                a["ended_ns"] = a.get("ended_ns") or at_ns
                out.append((a, "expired"))
        return out

    def holds(self) -> dict[str, str]:
        return hold_aliases(self.activities, self.project)

    def precluded(self) -> dict[str, dict[str, Any]]:
        return precluded(self.activities)

    def snapshot(self, include_ended: bool = True) -> list[dict[str, Any]]:
        rows = [dict(a) for a in self.activities.values()]
        if not include_ended:
            rows = [a for a in rows if a.get("state") in IN_FORCE]
        rows.sort(key=lambda a: (a.get("state") not in IN_FORCE, -int(a.get("declared_ns") or 0)))
        return rows


# ── the watcher ──────────────────────────────────────────────────────────────
@dataclass
class CoordinationWatcher:
    """Owns the view, the Signals watch stream, and the cessions it implies."""

    orchestrator: Any
    bus: Any = None
    target: str = field(default_factory=signals_target)
    project: str = PROJECT
    view: CoordinationView = field(default_factory=CoordinationView)
    # Returns the engine's shared asyncpg pool (or None while booting): the
    # workload pass reads/writes scheduled_tasks through it.
    pool_getter: Any = None
    _task: asyncio.Task | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _ceded: dict[str, str] = field(default_factory=dict)  # alias → activity_id we applied
    # activity_id → {task_id, task_type, state, last_heartbeat_ns} for OUR workloads
    _workloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    _released: set[str] = field(default_factory=set)      # we released these (gate said no / done)
    _wl_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connected: bool = False
    last_event_ns: int = 0
    events: int = 0
    reconnects: int = 0
    _unimplemented_logged: bool = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self.run(), name="coordination-watch")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ── read API (local processes ask THIS engine) ───────────────────────────
    def snapshot(self, include_ended: bool = True) -> list[dict[str, Any]]:
        return self.view.snapshot(include_ended=include_ended)

    def precluded_leaves(self) -> set[str]:
        return set(self.view.precluded().keys())

    def precluding_activity(self, leaf: str) -> dict[str, Any] | None:
        return self.view.precluded().get(str(leaf))

    def is_ceded(self, alias: str) -> bool:
        return alias in self._ceded

    def ceded(self) -> dict[str, str]:
        return dict(self._ceded)

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "target": self.target,
            "last_event_ms": self.last_event_ns // 1_000_000,
            "observed_ms": self.view.observed_ns // 1_000_000,
            "events": self.events,
            "reconnects": self.reconnects,
            "activities": len(self.view.activities),
            "ceded": dict(self._ceded),
            "workloads": {aid: dict(w) for aid, w in self._workloads.items()},
        }

    def workload_for(self, activity_id: str) -> dict[str, Any] | None:
        w = self._workloads.get(str(activity_id))
        return dict(w) if w else None

    def workload_label(self, activity_id: str) -> str:
        w = self._workloads.get(str(activity_id))
        if not w:
            return ""
        return f"{w.get('task_type')} #{w.get('task_id')} {w.get('state')}"

    # ── our own workloads (Airflow orders; the row is the memory) ────────────
    def own_running(self) -> list[dict[str, Any]]:
        """Our RUNNING activities whose kind names a workload we know how to start."""
        return [
            a for a in self.view.activities.values()
            if a.get("peer") == self.project
            and a.get("state") == "running"
            and str(a.get("kind") or "") in WORKLOAD_KINDS
            and str(a.get("activity_id") or "") not in self._released
        ]

    async def workload_pass(self, at_ns: int | None = None) -> list[tuple[str, str]]:
        """Start / attach / retry / heartbeat our own in-force workloads.

        Idempotent: the scheduled_tasks row carrying ``payload.activity_id`` is
        the memory, so repeated watch events and engine restarts converge on one
        run. Returns [(activity_id, action)] for what happened this pass.
        """
        pool = self.pool_getter() if callable(self.pool_getter) else None
        if pool is None:
            return []
        at = int(at_ns if at_ns is not None else now_ns())
        actions: list[tuple[str, str]] = []
        async with self._wl_lock:
            for a in self.own_running():
                aid = str(a.get("activity_id") or "")
                kind = str(a.get("kind") or "")
                spec = WORKLOAD_KINDS[kind]
                try:
                    action = await self._workload_step(pool, a, aid, kind, spec, at)
                except Exception as e:  # noqa: BLE001 — one activity's failure never stops the pass
                    logger.warning("%s workload step for activity %s (%s): %s", GURU_ENQUEUEFAIL, aid, kind, e)
                    continue
                if action:
                    actions.append((aid, action))
        return actions

    async def _workload_step(self, pool: Any, a: dict[str, Any], aid: str, kind: str, spec: dict[str, Any], at: int) -> str:
        task_type = str(spec["task_type"])
        row = await pool.fetchrow(
            "SELECT id, task_type, picked_up_at, completed_at, result, error FROM scheduled_tasks "
            "WHERE payload->>'activity_id' = $1 ORDER BY id DESC LIMIT 1",
            aid,
        )
        if row is None:
            gate = spec.get("gate_sql")
            if gate:
                ok = await pool.fetchval(str(gate))
                if not ok:
                    outcome = f"skipped: {gate} is false"
                    await self.release_activity(aid, outcome)
                    self._workloads[aid] = {"task_id": 0, "task_type": task_type, "state": "skipped", "last_heartbeat_ns": at}
                    logger.info("coordination: workload %s for activity %s skipped (%s)", task_type, aid, gate)
                    self._publish(a, "skipped_workload", [], at)
                    return "skipped"
            live = await pool.fetchrow(
                "SELECT id, picked_up_at FROM scheduled_tasks WHERE task_type = $1 AND completed_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                task_type,
            )
            state = "queued"
            if live is not None:
                tid = int(live["id"])
                await pool.execute(
                    "UPDATE scheduled_tasks SET payload = COALESCE(payload, '{}'::jsonb) || $2::jsonb WHERE id = $1",
                    tid,
                    json.dumps({"activity_id": aid, "activity_kind": kind}),
                )
                action = "attached_workload"
                state = "running" if live["picked_up_at"] is not None else "queued"
                logger.info("coordination: attached workload %s #%d to activity %s (already %s)", task_type, tid, aid, state)
            else:
                tid = await self._enqueue(pool, spec, aid, kind)
                action = "started_workload"
                logger.info("coordination: started workload %s #%d for activity %s", task_type, tid, aid)
            self._workloads[aid] = {"task_id": tid, "task_type": task_type, "state": state, "last_heartbeat_ns": 0}
            self._publish(a, action, [], at)
            await self._heartbeat(aid, at)
            return action

        tid = int(row["id"])
        state = self._row_state(row)
        wl = self._workloads.setdefault(aid, {"task_id": tid, "task_type": task_type, "state": state, "last_heartbeat_ns": 0})
        wl.update({"task_id": tid, "task_type": task_type, "state": state})
        if row["completed_at"] is None:
            await self._heartbeat(aid, at)
            return ""
        if state in RETRY_STATUSES:
            completed_ns = int(row["completed_at"].timestamp() * 1_000_000_000)
            if at - completed_ns >= WORKLOAD_RETRY_S * 1_000_000_000:
                new_tid = await self._enqueue(pool, spec, aid, kind)
                wl.update({"task_id": new_tid, "state": "queued"})
                logger.info(
                    "coordination: re-enqueued workload %s #%d for activity %s after %s #%d",
                    task_type, new_tid, aid, state, tid,
                )
                self._publish(a, "retried_workload", [], at)
                await self._heartbeat(aid, at)
                return "retried_workload"
            await self._heartbeat(aid, at)
            return ""
        # Terminal: the processor released it (or the lease TTL will expire it).
        return ""

    @staticmethod
    def _row_state(row: Any) -> str:
        if row["completed_at"] is None:
            return "running" if row["picked_up_at"] is not None else "queued"
        result = row["result"]
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        status = str((result or {}).get("status") or "") if isinstance(result, dict) else ""
        if status:
            return status
        return "error" if row["error"] else "completed"

    async def _enqueue(self, pool: Any, spec: dict[str, Any], aid: str, kind: str) -> int:
        payload = dict(spec.get("payload") or {})
        payload.update({"activity_id": aid, "activity_kind": kind, "source": WORKLOAD_SOURCE})
        tid = await pool.fetchval(
            "INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for) "
            "VALUES ($1, $2::jsonb, $3, NOW()) RETURNING id",
            str(spec["task_type"]),
            json.dumps(payload),
            WORKLOAD_SOURCE,
        )
        return int(tid)

    async def _heartbeat(self, aid: str, at: int) -> None:
        wl = self._workloads.get(aid)
        if wl is None:
            return
        if at - int(wl.get("last_heartbeat_ns") or 0) < WORKLOAD_HEARTBEAT_S * 1_000_000_000:
            return
        horizon = at + int(WORKLOAD_HORIZON_S * 1_000_000_000)
        if await self.renew_activity(aid, horizon):
            wl["last_heartbeat_ns"] = at

    # ── Scheduler RPCs the ENGINE (the peer) makes for its own activities ─────
    async def renew_activity(self, activity_id: str, horizon_ns: int) -> bool:
        try:
            resp = await _scheduler_call(self.target, "RenewActivity", peer=self.project, activity_id=activity_id, horizon_ns=int(horizon_ns))
        except Exception as e:  # noqa: BLE001
            logger.warning("%s RenewActivity(%s) on %s: %s — retry next pass (lease TTL bounds it)", GURU_RENEWFAIL, activity_id, self.target, e)
            return False
        if not resp.accepted:
            logger.warning("%s RenewActivity(%s) refused: %s", GURU_RENEWFAIL, activity_id, resp.error)
            return False
        return True

    async def release_activity(self, activity_id: str, outcome: str) -> bool:
        ok = await release_rpc(self.target, activity_id, outcome, peer=self.project)
        if ok:
            self._released.add(activity_id)
            a = self.view.activities.get(activity_id)
            if a is not None:
                self._publish(dict(a, state="released", note=outcome), "released", [], now_ns())
        return ok

    # ── ingest ───────────────────────────────────────────────────────────────
    def ingest(self, incoming: list[dict[str, Any]], at_ns: int | None = None) -> list[tuple[dict[str, Any], str]]:
        """Adopt a snapshot (from the stream or a test), reconcile cessions, publish."""
        at = int(at_ns if at_ns is not None else now_ns())
        transitions = self.view.replace(incoming, at)
        self.last_event_ns = at
        self.events += 1
        self._reconcile(transitions, at)
        return transitions

    def sweep(self, at_ns: int | None = None) -> list[tuple[dict[str, Any], str]]:
        at = int(at_ns if at_ns is not None else now_ns())
        transitions = self.view.sweep(at)
        if transitions:
            self._reconcile(transitions, at)
        return transitions

    def _reconcile(self, transitions: list[tuple[dict[str, Any], str]], at_ns: int) -> None:
        wanted = self.view.holds()
        by_activity: dict[str, list[str]] = {}
        # Restore first: an endpoint whose activity ended (or stopped holding it).
        for alias, aid in list(self._ceded.items()):
            if wanted.get(alias) != aid:
                self._restore(alias, aid)
        for alias, aid in wanted.items():
            by_activity.setdefault(aid, []).append(f"endpoint.{alias}")
            if self._ceded.get(alias) != aid:
                self._cede(alias, self.view.activities[aid])
        for a, transition in transitions:
            self._publish(a, transition, by_activity.get(str(a.get("activity_id") or ""), []), at_ns)

    def _cede(self, alias: str, a: dict[str, Any]) -> None:
        aid = str(a.get("activity_id") or "")
        fn = getattr(self.orchestrator, "cede_endpoint", None)
        try:
            if callable(fn):
                fn(
                    alias,
                    owner=f"{a.get('peer') or '?'}:{a.get('owner') or '?'}",
                    activity_id=aid,
                    horizon_ns=int(a.get("horizon_ns") or 0),
                    kind=str(a.get("kind") or ""),
                )
            self._ceded[alias] = aid
            logger.info(
                "coordination: ceded endpoint %s to %s %s (%s:%s) until %s",
                alias, a.get("kind"), aid, a.get("peer"), a.get("owner"),
                _iso(int(a.get("horizon_ns") or 0)),
            )
        except Exception:  # noqa: BLE001 — a cession failure must not kill the watcher
            logger.exception("coordination: cede_endpoint(%s) failed", alias)

    def _restore(self, alias: str, aid: str) -> None:
        fn = getattr(self.orchestrator, "restore_endpoint", None)
        try:
            if callable(fn):
                fn(alias, activity_id=aid)
            self._ceded.pop(alias, None)
            logger.info("coordination: restored endpoint %s (activity %s ended)", alias, aid)
        except Exception:  # noqa: BLE001
            logger.exception("coordination: restore_endpoint(%s) failed", alias)

    def _publish(self, a: dict[str, Any], transition: str, ceded: list[str], at_ns: int) -> None:
        bus = self.bus
        if bus is None:
            return
        try:
            # `kind` is the bus's own positional (the event kind); the activity's
            # kind travels as `activity_kind` and the servicer maps it back to
            # ActivityEvent.kind — the same payload shape Hermes's engine emits.
            bus.publish(
                KIND_ACTIVITY,
                at_unix_ms=at_ns // 1_000_000,
                activity_id=str(a.get("activity_id") or ""),
                activity_kind=str(a.get("kind") or ""),
                peer=str(a.get("peer") or ""),
                owner=str(a.get("owner") or ""),
                dag_id=str(a.get("dag_id") or ""),
                run_id=str(a.get("run_id") or ""),
                state=str(a.get("state") or ""),
                declared_ns=int(a.get("declared_ns") or 0),
                horizon_ns=int(a.get("horizon_ns") or 0),
                ended_ns=int(a.get("ended_ns") or 0),
                precludes=[str(p) for p in (a.get("precludes") or [])],
                postures={str(k): str(v) for k, v in (a.get("postures") or {}).items()},
                reason=str(a.get("reason") or ""),
                transition=transition,
                ceded=list(ceded),
            )
        except Exception:  # noqa: BLE001 — bookkeeping never disturbs the watcher
            logger.debug("coordination: bus publish skipped", exc_info=True)

    # ── the stream ───────────────────────────────────────────────────────────
    async def run(self) -> None:
        import grpc
        from grpc import aio

        backoff = BACKOFF_MIN_S
        while not self._stop.is_set():
            try:
                await self._watch_once()
                backoff = BACKOFF_MIN_S
            except asyncio.CancelledError:
                raise
            except aio.AioRpcError as e:
                self.connected = False
                if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                    if not self._unimplemented_logged:
                        logger.warning(
                            "%s Signals at %s has no Scheduler/WatchActivities (protocol older than "
                            "2026-09-06); coordination view stays empty — retrying every %.0fs",
                            GURU_NOACTIVITIES, self.target, UNIMPLEMENTED_RETRY_S,
                        )
                        self._unimplemented_logged = True
                    await self._sleep(UNIMPLEMENTED_RETRY_S)
                    continue
                logger.warning(
                    "%s WatchActivities on %s: %s %s — redial in %.0fs",
                    GURU_STREAMDROP, self.target, e.code().name, (e.details() or "")[:160], backoff,
                )
            except _Silent:
                self.connected = False
                logger.warning(
                    "%s no activity event from %s for %.0fs (Signals heartbeats every 60 s) — redial",
                    GURU_SILENT, self.target, SILENCE_S,
                )
            except Exception as e:  # noqa: BLE001
                self.connected = False
                logger.warning("%s WatchActivities on %s: %s — redial in %.0fs", GURU_STREAMDROP, self.target, e, backoff)
            self.sweep()
            self.reconnects += 1
            await self._sleep(backoff)
            backoff = min(BACKOFF_MAX_S, backoff * 2)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _watch_once(self) -> None:
        from grpc import aio

        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

        async with aio.insecure_channel(self.target) as channel:
            stub = spb_grpc.SchedulerStub(channel)
            call = stub.WatchActivities(spb.WatchActivitiesRequest(peer=self.project))
            # One outstanding read at a time. asyncio.wait(timeout=) does NOT
            # cancel the pending read (cancelling a grpc.aio read cancels the
            # RPC), so a quiet 30 s is a sweep + silence check, not a redial.
            reader: asyncio.Task | None = None
            quiet_s = 0.0
            try:
                while not self._stop.is_set():
                    if reader is None:
                        reader = asyncio.ensure_future(call.read())
                    done, _ = await asyncio.wait({reader}, timeout=READ_TIMEOUT_S)
                    if not done:
                        quiet_s += READ_TIMEOUT_S
                        self.sweep()
                        await self._workload_pass_safely()
                        if quiet_s >= SILENCE_S:
                            raise _Silent()
                        continue
                    msg = reader.result()  # raises AioRpcError on a failed stream
                    reader = None
                    quiet_s = 0.0
                    if msg is aio.EOF:
                        raise _StreamClosed("stream closed by Signals")
                    if not self.connected:
                        self.connected = True
                        self._unimplemented_logged = False
                        logger.info("coordination: watching activities on %s", self.target)
                    at = int(msg.observed_ns) if int(msg.observed_ns) > 0 else now_ns()
                    # The local clock decides horizons; Signals' observed_ns
                    # timestamps the view.
                    self.ingest([activity_to_dict(a) for a in msg.activities], now_ns())
                    self.view.observed_ns = at
                    await self._workload_pass_safely()
            finally:
                if reader is not None and not reader.done():
                    reader.cancel()
                try:
                    call.cancel()
                except Exception:  # noqa: BLE001
                    pass


    async def _workload_pass_safely(self) -> None:
        try:
            await self.workload_pass()
        except Exception:  # noqa: BLE001 — the workload pass never kills the watch stream
            logger.exception("coordination: workload pass failed")


class _Silent(Exception):
    pass


class _StreamClosed(Exception):
    pass


def _iso(ns: int) -> str:
    if not ns:
        return "-"
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ns / 1e9))


# ── Scheduler RPC helpers (grpc.aio; the engine is the peer) ─────────────────
async def _scheduler_call(target: str, method: str, **fields: Any) -> Any:
    from grpc import aio

    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

    req_cls = getattr(spb, f"{method}Request")
    async with aio.insecure_channel(target) as channel:
        stub = spb_grpc.SchedulerStub(channel)
        return await getattr(stub, method)(req_cls(**fields), timeout=RPC_TIMEOUT_S)


async def release_rpc(target: str, activity_id: str, outcome: str, *, peer: str = PROJECT) -> bool:
    """ReleaseActivity at Signals. Never raises: a failed release is logged with
    its guru and the lease TTL (no more heartbeats) expires the activity."""
    try:
        resp = await _scheduler_call(target, "ReleaseActivity", peer=peer, activity_id=activity_id, outcome=str(outcome)[:200])
    except Exception as e:  # noqa: BLE001
        logger.warning("%s ReleaseActivity(%s) on %s: %s — the lease TTL will expire it", GURU_RELEASEFAIL, activity_id, target, e)
        return False
    if not resp.accepted:
        logger.warning("%s ReleaseActivity(%s) refused: %s", GURU_RELEASEFAIL, activity_id, resp.error)
        return False
    logger.info("coordination: released activity %s (%s)", activity_id, outcome)
    return True


async def release_for_task(payload: Any, status: str, task_type: str, task_id: int) -> bool:
    """Called by the task processor when a row books a TERMINAL outcome.

    A row carrying ``payload.activity_id`` belongs to an Airflow-ordered
    workload: releasing the activity completes the Airflow ``hold`` sensor and
    Signals retracts the workload's queue configuration. Deferred / yielded
    outcomes are not terminal here (the watcher retries while in force).
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    aid = str((payload or {}).get("activity_id") or "") if isinstance(payload, dict) else ""
    if not aid or str(status) not in RELEASE_STATUSES:
        return False
    outcome = f"{status}: {task_type} #{task_id}"
    co = get_coordination()
    if co is not None:
        ok = await co.release_activity(aid, outcome)
        wl = co._workloads.get(aid)
        if wl is not None:
            wl["state"] = str(status)
        return ok
    return await release_rpc(signals_target(), aid, outcome)


def schedule_hints() -> list[Any]:
    """ServerQuery kind=SCHEDULES: the classes whose schedule lives in the Signals
    Airflow (source=airflow, the DAG that declares them). pg_cron classes are not
    listed here (honest: the catalog for those has not landed)."""
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    cron_by_class: dict[str, str] = {}
    try:
        from gaius.engine.supervision_spec import load_spec

        spec = load_spec()
        if spec is not None:
            for cls in AIRFLOW_SOURCED_CLASSES:
                proc = spec.process(f"task.{cls}")
                cadence = getattr(proc, "cadence", None) if proc is not None else None
                cron = str(getattr(cadence, "cron", "") or "") if cadence is not None else ""
                if cron:
                    cron_by_class[cls] = cron
    except Exception:  # noqa: BLE001 — the hint is discovery, not truth
        logger.debug("schedule_hints: supervision spec unavailable", exc_info=True)
    return [
        zpb.ScheduleHint(
            id=f"task.{cls}",
            cron=cron_by_class.get(cls, ""),
            airflow_dag_id=dag_id,
            source="airflow",
            enabled=True,
        )
        for cls, dag_id in AIRFLOW_SOURCED_CLASSES.items()
    ]


# ── singleton ────────────────────────────────────────────────────────────────
_COORD: CoordinationWatcher | None = None


def init_coordination(
    orchestrator: Any, bus: Any = None, target: str | None = None, pool_getter: Any = None
) -> CoordinationWatcher:
    global _COORD
    if _COORD is None:
        _COORD = CoordinationWatcher(
            orchestrator=orchestrator, bus=bus, target=target or signals_target(), pool_getter=pool_getter
        )
    elif pool_getter is not None and _COORD.pool_getter is None:
        _COORD.pool_getter = pool_getter
    return _COORD


def get_coordination() -> CoordinationWatcher | None:
    return _COORD


def reset_coordination_for_tests() -> None:
    global _COORD
    _COORD = None
