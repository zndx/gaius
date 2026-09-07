"""Coordination Activities on the gaius side (2026-09-06).

The engine watches Signals for peers' declared intent (Activities), cedes
endpoints named by `hold-uptime` postures, defers admission into precluded
leaves, and re-exposes the view locally. Pure logic here — no gRPC.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from gaius.engine.services import coordination as co
from gaius.engine.services.coordination import (
    KIND_ACTIVITY,
    CoordinationView,
    CoordinationWatcher,
    activity_to_dict,
    dict_to_proto,
    hold_aliases,
    init_coordination,
    reset_coordination_for_tests,
)

NOW = time.time_ns()
H = 3_600 * 1_000_000_000


def _act(aid="a1", state="running", run_id="act-a1-1", horizon=NOW + H, **kw):
    a = {
        "activity_id": aid,
        "kind": "interactive_session",
        "peer": "hermes",
        "owner": "rtc-42",
        "dag_id": "coord_activity",
        "run_id": run_id,
        "state": state,
        "declared_ns": NOW - 60 * 1_000_000_000,
        "horizon_ns": horizon,
        "renewed_ns": 0,
        "ended_ns": 0,
        "claims": [{"leaf": "root.internal.inference.agent-rtc", "gpu": 1}],
        "precludes": [],
        "postures": {"gaius.endpoint.thinking": "hold-uptime"},
        "reason": "interactive session",
        "note": "",
    }
    a.update(kw)
    return a


class FakeOrch:
    def __init__(self) -> None:
        self.ceded: dict[str, dict] = {}
        self.calls: list[tuple] = []

    def cede_endpoint(self, alias, *, owner, activity_id, horizon_ns, kind=""):
        self.ceded[alias] = {"owner": owner, "activity_id": activity_id, "horizon_ns": horizon_ns, "kind": kind}
        self.calls.append(("cede", alias, activity_id))

    def restore_endpoint(self, alias, *, activity_id=""):
        self.calls.append(("restore", alias, activity_id))
        return self.ceded.pop(alias, None) is not None


class FakeBus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, kind, **payload):
        self.events.append({"kind": kind, **payload})


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_coordination_for_tests()
    yield
    reset_coordination_for_tests()


# ── pure view ────────────────────────────────────────────────────────────────
def test_replace_derives_transitions_started_renewed_released_ended() -> None:
    v = CoordinationView()
    t = v.replace([_act()], NOW)
    assert [(a["activity_id"], tr) for a, tr in t] == [("a1", "started")]
    # renewal = same activity_id, new run
    t = v.replace([_act(run_id="act-a1-2")], NOW + 1)
    assert [tr for _, tr in t] == ["renewed"]
    # released by the owner
    t = v.replace([_act(run_id="act-a1-2", state="released", ended_ns=NOW + 2)], NOW + 2)
    assert [tr for _, tr in t] == ["released"]
    # a running activity that simply disappears from the snapshot has ended:
    # before its horizon that is a release, at/after it an expiry
    v.replace([_act(aid="b", postures={})], NOW + 3)
    t = v.replace([], NOW + 4)
    assert [(a["activity_id"], tr, a["state"]) for a, tr in t] == [("b", "released", "released")]
    assert v.snapshot() == []
    v.replace([_act(aid="c", postures={}, horizon=NOW + 10)], NOW + 5)
    t = v.replace([], NOW + 10)
    assert [(a["activity_id"], tr) for a, tr in t] == [("c", "expired")]


def test_queued_is_observed_not_started_and_does_not_hold() -> None:
    v = CoordinationView()
    t = v.replace([_act(state="queued")], NOW)
    assert [tr for _, tr in t] == ["observed"]
    assert v.holds() == {}
    t = v.replace([_act(state="running")], NOW + 1)
    assert [tr for _, tr in t] == ["started"]
    assert v.holds() == {"thinking": "a1"}


def test_horizon_is_the_safety_on_replace_and_sweep() -> None:
    v = CoordinationView()
    # Signals says running but the horizon has passed → expired locally
    t = v.replace([_act(horizon=NOW - 1)], NOW)
    assert [tr for _, tr in t] == ["expired"]
    assert v.holds() == {}
    # in force now, then the clock passes the horizon with Signals dark
    v = CoordinationView()
    v.replace([_act(horizon=NOW + 10)], NOW)
    assert v.holds() == {"thinking": "a1"}
    assert v.sweep(NOW + 5) == []
    t = v.sweep(NOW + 10)
    assert [tr for _, tr in t] == ["expired"]
    assert v.holds() == {}


def test_precluded_leaves_only_from_running() -> None:
    v = CoordinationView()
    v.replace(
        [
            _act(aid="r", precludes=["root.internal.inference.light"]),
            _act(aid="q", state="queued", precludes=["root.internal.inference.medium"]),
            _act(aid="x", state="released", precludes=["root.internal.inference.extract"]),
        ],
        NOW,
    )
    assert set(v.precluded()) == {"root.internal.inference.light"}
    assert v.precluded()["root.internal.inference.light"]["activity_id"] == "r"


def test_hold_aliases_reads_only_our_project() -> None:
    view = {
        "a": _act(aid="a", postures={"gaius.endpoint.thinking": "hold-uptime", "aegir.endpoint.render": "hold-uptime"}),
        "b": _act(aid="b", postures={"gaius.endpoint.clt": "something-else"}),
    }
    assert hold_aliases(view, "gaius") == {"thinking": "a"}
    assert hold_aliases(view, "aegir") == {"render": "a"}


# ── watcher: cessions + bus ──────────────────────────────────────────────────
def test_watcher_cedes_on_running_restores_on_end_and_publishes() -> None:
    orch, bus = FakeOrch(), FakeBus()
    w = CoordinationWatcher(orchestrator=orch, bus=bus, target="test:0")
    w.ingest([_act()], NOW)
    assert orch.calls == [("cede", "thinking", "a1")]
    assert w.is_ceded("thinking") and w.ceded() == {"thinking": "a1"}
    ev = bus.events[-1]
    assert ev["kind"] == KIND_ACTIVITY and ev["transition"] == "started"
    # the activity's kind rides as activity_kind (bus `kind` = event kind) — Hermes shape
    assert ev["activity_kind"] == "interactive_session" and "kind" not in {k for k in ev if k == "activity_kind"}
    assert ev["ceded"] == ["endpoint.thinking"] and ev["postures"] == {"gaius.endpoint.thinking": "hold-uptime"}

    w.ingest([_act(state="released", ended_ns=NOW + 1)], NOW + 1)
    assert orch.calls[-1] == ("restore", "thinking", "a1")
    assert not w.is_ceded("thinking")
    assert bus.events[-1]["transition"] == "released" and bus.events[-1]["ceded"] == []


def test_watcher_restores_when_signals_is_dark_and_horizon_passes() -> None:
    orch = FakeOrch()
    w = CoordinationWatcher(orchestrator=orch, bus=FakeBus(), target="test:0")
    w.ingest([_act(horizon=NOW + 10)], NOW)
    assert orch.ceded.keys() == {"thinking"}
    w.sweep(NOW + 10)
    assert orch.calls[-1] == ("restore", "thinking", "a1")
    assert orch.ceded == {}


def test_watcher_renewal_keeps_the_cession_without_a_second_cede() -> None:
    orch = FakeOrch()
    w = CoordinationWatcher(orchestrator=orch, bus=FakeBus(), target="test:0")
    w.ingest([_act()], NOW)
    w.ingest([_act(run_id="act-a1-2", horizon=NOW + 2 * H)], NOW + 1)
    assert [c for c in orch.calls if c[0] == "cede"] == [("cede", "thinking", "a1")]
    assert w.is_ceded("thinking")


def test_watcher_precluded_leaves_and_status() -> None:
    w = CoordinationWatcher(orchestrator=FakeOrch(), bus=None, target="test:0")
    w.ingest([_act(precludes=["root.internal.inference.light"])], NOW)
    assert w.precluded_leaves() == {"root.internal.inference.light"}
    assert w.precluding_activity("root.internal.inference.light")["activity_id"] == "a1"
    assert w.precluding_activity("root.internal.inference.medium") is None
    st = w.status()
    assert st["activities"] == 1 and st["ceded"] == {"thinking": "a1"} and st["connected"] is False


# ── proto ↔ dict ─────────────────────────────────────────────────────────────
def test_dict_to_proto_and_back_roundtrip() -> None:
    d = _act(precludes=["root.internal.inference.light"], note="hello")
    p = dict_to_proto(d)
    assert p.state == 2 and p.claims[0].leaf == "root.internal.inference.agent-rtc" and p.claims[0].gpu == 1
    back = activity_to_dict(p)
    assert back == d


# ── workload profile: ceded leaves the intended set ──────────────────────────
def test_compute_intents_excludes_ceded_like_evicted() -> None:
    from gaius.engine.services.workload_profile import WorkloadProfilePublisher

    orch = SimpleNamespace(
        config=SimpleNamespace(startup=SimpleNamespace(preload_endpoints=["thinking"])),
        _evicted_endpoints=set(),
        _ceded={},
        get_status=lambda: {"endpoints": {"thinking": {"status": "healthy", "model": "q", "port": 8081, "gpu_ids": [0], "capabilities": ["thinking"]}}},
    )
    wp = WorkloadProfilePublisher(orch)
    assert [i["alias"] for i in wp.compute_intents()] == ["thinking"]
    orch._ceded = {"thinking": {"activity_id": "a1", "owner": "hermes:rtc", "until_ms": 0, "kind": "interactive_session"}}
    assert wp.compute_intents() == []
    assert wp.snapshot()["ceded"] == ["thinking"]
    # an absent baseline endpoint is ABSENT (a miss) only while not ceded
    orch.get_status = lambda: {"endpoints": {}}
    assert wp.compute_intents() == []
    orch._ceded = {}
    assert [(i["alias"], i["actual"]) for i in wp.compute_intents()] == [("thinking", "absent")]


# ── orchestrator methods (unbound on a stand-in; the constructor needs GPUs) ─
class _WP:
    def __init__(self) -> None:
        self.details: list[str] = []

    def settle(self, detail: str) -> None:
        self.details.append(detail)


def test_orchestrator_cede_restore_and_hold_restart() -> None:
    from gaius.engine.services.orchestrator_service import OrchestratorService as OS

    me = SimpleNamespace(_ceded={}, _workload_profile=_WP(), _auto_restart_enabled=True, _restart_attempts={}, _max_restart_attempts=3)
    OS.cede_endpoint(me, "thinking", owner="hermes:rtc-42", activity_id="a1", horizon_ns=NOW + H, kind="interactive_session")
    assert me._ceded["thinking"]["activity_id"] == "a1" and me._workload_profile.details[-1].startswith("ceded thinking")
    # idempotent re-cede does not re-settle
    OS.cede_endpoint(me, "thinking", owner="hermes:rtc-42", activity_id="a1", horizon_ns=NOW + H, kind="interactive_session")
    assert len(me._workload_profile.details) == 1

    def boom(alias):  # would be called only if the hold did not fire
        raise AssertionError("auto-restart chased a ceded endpoint")

    me.get_endpoint_status = boom
    asyncio.run(OS._maybe_restart_endpoint(me, "thinking"))

    assert OS.restore_endpoint(me, "thinking", activity_id="other") is False
    assert OS.restore_endpoint(me, "thinking", activity_id="a1") is True
    assert me._ceded == {} and me._workload_profile.details[-1].startswith("restored thinking")
    assert OS.restore_endpoint(me, "thinking") is False


# ── supervision: bus event → ActivityEvent proto ─────────────────────────────
def test_event_to_proto_activity() -> None:
    from gaius.engine.grpc.servicers.supervision_servicer import event_to_proto
    from gaius.engine.services.supervision_bus import SupervisionBus

    bus = SupervisionBus()
    ev = bus.publish(
        KIND_ACTIVITY, activity_id="a1", activity_kind="interactive_session", peer="hermes", owner="rtc", dag_id="coord_activity",
        run_id="act-a1-1", state="running", declared_ns=1, horizon_ns=2, ended_ns=0, precludes=["root.internal.inference.light"],
        postures={"gaius.endpoint.thinking": "hold-uptime"}, reason="r", transition="started", ceded=["endpoint.thinking"],
    )
    out = event_to_proto(ev, "epoch")
    assert out.WhichOneof("event") == "activity"
    a = out.activity
    assert (a.activity_id, a.kind, a.state, a.transition, list(a.ceded)) == (
        "a1", "interactive_session", "running", "started", ["endpoint.thinking"]
    )
    assert a.postures["gaius.endpoint.thinking"] == "hold-uptime" and list(a.precludes) == ["root.internal.inference.light"]


# ── admission: a precluded leaf is a DEFERRAL ────────────────────────────────
def test_admission_precluded_raises_deferral_guru() -> None:
    from gaius.engine.sentinel_claim import GURU_PRECLUDED, LIGHT, YkAdmitError, assert_not_precluded

    # no watcher → nothing precluded
    assert_not_precluded(LIGHT, "clt-skos-admit", "wid")
    w = init_coordination(FakeOrch(), bus=None, target="test:0")
    w.ingest([_act(precludes=["root.internal.inference.light"])], NOW)
    with pytest.raises(YkAdmitError) as ei:
        assert_not_precluded(LIGHT, "clt-skos-admit", "wid")
    assert ei.value.code == GURU_PRECLUDED and "a1" in str(ei.value) and "deferral" in str(ei.value)
    # the activity ends → admission resumes
    w.ingest([], NOW + 1)
    assert_not_precluded(LIGHT, "clt-skos-admit", "wid")


# ── the Engine-First view ────────────────────────────────────────────────────
def test_servicer_activities_view_and_render() -> None:
    from gaius.cli_render.activities import render_activities
    from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer

    me = SimpleNamespace(_services=SimpleNamespace())
    resp = asyncio.run(GaiusServicer.Activities(me, SimpleNamespace(include_ended=False, kind="", peer=""), None))
    assert resp.error.startswith(co.GURU_NOWATCHER)

    w = init_coordination(FakeOrch(), bus=None, target="127.0.0.1:50551")
    w.ingest([_act(precludes=["root.internal.inference.light"]), _act(aid="z", state="released", postures={})], NOW)
    resp = asyncio.run(GaiusServicer.Activities(me, SimpleNamespace(include_ended=False, kind="", peer=""), None))
    assert resp.error == "" and [r.activity_id for r in resp.rows] == ["a1"]
    row = resp.rows[0]
    assert row.state == "running" and list(row.ceded) == ["endpoint.thinking"] and row.claims[0] == "root.internal.inference.agent-rtc:1"
    assert row.postures["gaius.endpoint.thinking"] == "hold-uptime" and row.horizon_at.endswith("+00:00")
    resp_all = asyncio.run(GaiusServicer.Activities(me, SimpleNamespace(include_ended=True, kind="", peer="hermes"), None))
    assert [r.activity_id for r in resp_all.rows] == ["a1", "z"]

    text = render_activities(
        [{"activity_id": "a1", "kind": "interactive_session", "peer": "hermes", "owner": "rtc", "state": "running",
          "horizon_at": "2026-09-06T23:00:00+00:00", "ceded": ["endpoint.thinking"], "precludes": ["root.internal.inference.light"],
          "claims": ["root.internal.inference.agent-rtc:1"], "reason": "rtc"}],
        watcher_connected=True, signals_target="127.0.0.1:50551",
    )
    assert "● running" in text and "holds endpoint.thinking" in text and "watching 127.0.0.1:50551" in text


# ── 2026-09-07: Airflow orders our workloads — own activity in force → run ──────

import json as _json
from datetime import datetime, timedelta, timezone


def _own(aid="w1", kind="article_curate", state="running", horizon=NOW + H):
    return _act(aid=aid, kind=kind, peer="gaius", owner="airflow:gaius_article_curate",
                state=state, run_id=f"act-{aid}", horizon=horizon, postures={}, claims=[
                    {"leaf": "root.internal.inference.extract", "gpu": 1}])


class FakePool:
    """Just enough of asyncpg for the workload pass; SQL matched by shape."""

    def __init__(self, gate=True):
        self.rows: list[dict] = []
        self.gate = gate
        self.sql: list[str] = []
        self._next = 100

    def add(self, task_type, payload, *, picked=False, completed=None, result=None, error=None):
        self._next += 1
        row = {"id": self._next, "task_type": task_type, "payload": dict(payload), "source": "pg_cron",
               "picked_up_at": datetime.now(timezone.utc) if picked else None,
               "completed_at": completed, "result": result, "error": error}
        self.rows.append(row)
        return row

    def _latest_for(self, aid):
        for r in reversed(self.rows):
            if (r["payload"] or {}).get("activity_id") == aid:
                return r
        return None

    async def fetchrow(self, sql, *args):
        self.sql.append(sql)
        if "payload->>'activity_id' = $1" in sql:
            return self._latest_for(args[0])
        if "task_type = $1 AND completed_at IS NULL" in sql:
            # the attach key: class + catalogue payload contained + not yet stamped
            assert "@> $2::jsonb" in sql and "payload->>'activity_id' IS NULL" in sql
            want = _json.loads(args[1])
            for r in reversed(self.rows):
                p = r["payload"] or {}
                if (r["task_type"] == args[0] and r["completed_at"] is None
                        and all(p.get(k) == v for k, v in want.items()) and "activity_id" not in p):
                    return {"id": r["id"], "picked_up_at": r["picked_up_at"]}
            return None
        raise AssertionError(f"unexpected fetchrow {sql}")

    async def fetchval(self, sql, *args):
        self.sql.append(sql)
        if "should_run_curation" in sql:
            return self.gate
        if sql.startswith("INSERT INTO scheduled_tasks"):
            self._next += 1
            self.rows.append({"id": self._next, "task_type": args[0], "payload": _json.loads(args[1]), "source": args[2],
                              "picked_up_at": None, "completed_at": None, "result": None, "error": None})
            return self._next
        raise AssertionError(f"unexpected fetchval {sql}")

    async def execute(self, sql, *args):
        self.sql.append(sql)
        if sql.startswith("UPDATE scheduled_tasks SET payload"):
            for r in self.rows:
                if r["id"] == args[0]:
                    r["payload"] = {**(r["payload"] or {}), **_json.loads(args[1])}
                    return "UPDATE 1"
            raise AssertionError("no such row")
        raise AssertionError(f"unexpected execute {sql}")

    def inserts(self):
        return [r for r in self.rows if r["source"] == "airflow"]


class FakeScheduler:
    def __init__(self, accepted=True):
        self.calls: list[tuple[str, dict]] = []
        self.accepted = accepted

    async def __call__(self, target, method, **fields):
        self.calls.append((method, fields))
        return SimpleNamespace(accepted=self.accepted, error="" if self.accepted else "refused")

    def named(self, method):
        return [f for m, f in self.calls if m == method]


def _watcher(pool, monkeypatch, sched=None):
    sched = sched or FakeScheduler()
    monkeypatch.setattr(co, "_scheduler_call", sched)
    w = CoordinationWatcher(orchestrator=FakeOrch(), bus=FakeBus(), target="signals:1", pool_getter=lambda: pool)
    return w, sched


def test_own_running_activity_enqueues_exactly_once_and_heartbeats(monkeypatch):
    pool = FakePool()
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_own()], NOW)
        acts = await w.workload_pass(NOW)
        assert acts == [("w1", "started_workload")]
        # repeated events / passes / a "restart" (new watcher over the same pool) never double-run
        await w.workload_pass(NOW + 5 * 10**9)
        w.ingest([_own()], NOW + 6 * 10**9)
        await w.workload_pass(NOW + 6 * 10**9)
        w2, _ = _watcher(pool, monkeypatch, sched)
        w2.ingest([_own()], NOW + 7 * 10**9)
        await w2.workload_pass(NOW + 7 * 10**9)
        rows = pool.inserts()
        assert len(rows) == 1
        assert rows[0]["task_type"] == "article_curate"
        assert rows[0]["payload"] == {"check_cooldown": True, "activity_id": "w1",
                                      "activity_kind": "article_curate", "source": "airflow"}
        # heartbeat: once at start; not again inside 60 s on the same watcher; a
        # restarted engine (w2) heartbeats at once — it cannot know the last one.
        assert len(sched.named("RenewActivity")) == 2
        await w.workload_pass(NOW + 30 * 10**9)
        assert len(sched.named("RenewActivity")) == 2
        await w.workload_pass(NOW + 61 * 10**9)
        renews = sched.named("RenewActivity")
        assert len(renews) == 3 and renews[-1]["peer"] == "gaius" and renews[-1]["activity_id"] == "w1"
        assert renews[-1]["horizon_ns"] > NOW + 61 * 10**9
        assert w.workload_label("w1").startswith("article_curate #") and w.workload_label("w1").endswith("queued")
        assert any((ev.get("transition") if isinstance(ev, dict) else getattr(ev, "payload", {}).get("transition")) == "started_workload" for ev in w.bus.events)

    asyncio.run(run())


def test_attaches_to_inflight_row_instead_of_second_enqueue(monkeypatch):
    pool = FakePool()
    live = pool.add("article_curate", {"check_cooldown": True}, picked=True)  # pg_cron's run, in flight
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_own()], NOW)
        acts = await w.workload_pass(NOW)
        assert acts == [("w1", "attached_workload")]
        assert pool.inserts() == []
        assert live["payload"]["activity_id"] == "w1"
        assert w.workload_label("w1") == f"article_curate #{live['id']} running"
        assert len(sched.named("RenewActivity")) == 1

    asyncio.run(run())


def _slot(aid, slot, declared=NOW - 10 * 60 * 10**9):
    """An own RUNNING publish-slot activity declared 10 min ago (past the coexistence grace)."""
    a = _act(aid=aid, kind=f"publish_cards_{slot}", peer="gaius", owner=f"airflow:gaius_publish_cards_{slot}",
             state="running", run_id=f"act-{aid}", horizon=NOW + H, postures={}, claims=[])
    a["declared_ns"] = declared
    return a


def test_attach_is_keyed_by_payload_not_task_type_alone(monkeypatch):
    """The four publish slots share one task_type: a predawn activity must not
    attach to pg_cron's AFTERNOON row, and a row another activity already
    stamped is not attached twice."""
    pool = FakePool()
    afternoon = pool.add("publish_cards", {"count": 1, "slot": "afternoon"}, picked=True)
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_slot("p1", "predawn")], NOW)
        assert await w.workload_pass(NOW) == [("p1", "started_workload")]  # no predawn row → its own run
        assert "activity_id" not in afternoon["payload"]
        rows = pool.inserts()
        assert len(rows) == 1 and rows[0]["payload"]["slot"] == "predawn" and rows[0]["payload"]["count"] == 3
        # the afternoon activity attaches to pg_cron's afternoon row …
        w.ingest([_slot("p1", "predawn"), _slot("a1", "afternoon")], NOW + 10**9)
        assert await w.workload_pass(NOW + 10**9) == [("a1", "attached_workload")]
        assert afternoon["payload"]["activity_id"] == "a1" and afternoon["payload"]["activity_kind"] == "publish_cards_afternoon"
        # … and a second afternoon activity (a re-declared run) cannot claim the same stamped row
        w.ingest([_slot("p1", "predawn"), _slot("a1", "afternoon"), _slot("a2", "afternoon")], NOW + 2 * 10**9)
        acts = await w.workload_pass(NOW + 2 * 10**9)
        assert acts == [("a2", "started_workload")]
        assert afternoon["payload"]["activity_id"] == "a1"
        assert len(pool.inserts()) == 2

    asyncio.run(run())


def test_coexisting_class_waits_the_grace_for_pg_cron_row_then_runs(monkeypatch):
    """publish_cards still has an active pg_cron job: a fresh Airflow activity
    waits ATTACH_GRACE_S for pg_cron's row (attach), and only enqueues its own
    run once the grace has passed with no row. A retired class (article_curate)
    never waits."""
    pool = FakePool()
    w, sched = _watcher(pool, monkeypatch)
    declared = NOW

    async def run():
        w.ingest([_slot("m1", "morning", declared=declared)], NOW)
        assert await w.workload_pass(NOW) == [("m1", "awaiting_pg_cron")]
        assert pool.inserts() == [] and len(sched.named("RenewActivity")) == 1  # the lease is kept alive
        assert w.workload_label("m1").endswith("awaiting_pg_cron")
        # pg_cron's row lands 4 s later → attached, no second run
        live = pool.add("publish_cards", {"count": 1, "slot": "morning"})
        assert await w.workload_pass(NOW + 4 * 10**9) == [("m1", "attached_workload")]
        assert live["payload"]["activity_id"] == "m1" and pool.inserts() == []
        # a slot whose pg_cron row never comes: runs after the grace
        w.ingest([_slot("m1", "morning", declared=declared), _slot("e1", "evening", declared=declared)], NOW + 5 * 10**9)
        assert await w.workload_pass(NOW + 5 * 10**9) == [("e1", "awaiting_pg_cron")]
        at = NOW + int(co.ATTACH_GRACE_S * 10**9) + 10**9
        assert await w.workload_pass(at) == [("e1", "started_workload")]
        assert [r["payload"]["slot"] for r in pool.inserts()] == ["evening"]
        # article_curate (pg_cron retired) enqueues at once — declared 60 s ago, no coexistence
        w.ingest([_own(aid="c1")], at)
        assert ("c1", "started_workload") in await w.workload_pass(at)

    asyncio.run(run())


def test_gate_false_releases_as_skipped(monkeypatch):
    pool = FakePool(gate=False)
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_own()], NOW)
        assert await w.workload_pass(NOW) == [("w1", "skipped")]
        assert pool.inserts() == []
        rel = sched.named("ReleaseActivity")
        assert len(rel) == 1 and rel[0]["outcome"].startswith("skipped:")
        assert await w.workload_pass(NOW + 10**9) == []  # released: never reconsidered

    asyncio.run(run())


def test_deferred_row_is_retried_while_in_force(monkeypatch):
    pool = FakePool()
    old = datetime.now(timezone.utc) - timedelta(seconds=200)
    pool.add("article_curate", {"check_cooldown": True, "activity_id": "w1"}, picked=True,
             completed=old, result={"status": "deferred", "reason": "yk_admission"})
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_own()], NOW)
        assert await w.workload_pass(NOW) == [("w1", "retried_workload")]
        assert len(pool.inserts()) == 1
        assert len(sched.named("ReleaseActivity")) == 0

    asyncio.run(run())


def test_terminal_row_outside_the_processor_is_released_once(monkeypatch):
    # 2026-09-07 21:26: three operator-skipped rows (never picked, so the processor's
    # release_for_task never ran) left their Airflow runs waiting the full lease TTL.
    pool = FakePool()
    pool.add("article_curate", {"check_cooldown": True, "activity_id": "w1"}, picked=False,
             completed=datetime.now(timezone.utc),
             result={"status": "skipped", "reason": "airflow_unpause_catchup"})
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_own()], NOW)
        assert await w.workload_pass(NOW) == [("w1", "released_workload")]
        rel = sched.named("ReleaseActivity")
        assert len(rel) == 1
        assert rel[0]["outcome"].startswith("skipped: article_curate #")
        assert "terminal outside the processor" in rel[0]["outcome"]
        assert pool.inserts() == []
        assert await w.workload_pass(NOW + 10**9) == []  # released once, never again
        assert len(sched.named("ReleaseActivity")) == 1

    asyncio.run(run())


def test_peer_activity_never_starts_a_workload(monkeypatch):
    pool = FakePool()
    w, sched = _watcher(pool, monkeypatch)

    async def run():
        w.ingest([_act(aid="h1")], NOW)  # hermes interactive session
        assert await w.workload_pass(NOW) == []
        assert pool.sql == [] and sched.calls == []

    asyncio.run(run())


def test_release_for_task_terminal_outcomes_only(monkeypatch):
    sched = FakeScheduler()
    monkeypatch.setattr(co, "_scheduler_call", sched)

    async def run():
        assert await co.release_for_task({"activity_id": "w1"}, "deferred", "article_curate", 7) is False
        assert await co.release_for_task({"activity_id": "w1"}, "yielded", "article_curate", 7) is False
        assert await co.release_for_task({"check_cooldown": True}, "completed", "article_curate", 7) is False
        assert sched.calls == []
        assert await co.release_for_task('{"activity_id": "w1"}', "completed", "article_curate", 7) is True
        rel = sched.named("ReleaseActivity")
        assert rel[0]["peer"] == "gaius" and rel[0]["outcome"] == "completed: article_curate #7"
        assert await co.release_for_task({"activity_id": "w2"}, "failed", "article_curate", 8) is True

    asyncio.run(run())


def test_schedule_hints_publish_the_whole_catalogue():
    hints = co.schedule_hints()
    by_id = {h.id: h for h in hints}
    h = by_id["task.article_curate"]
    assert h.source == "airflow" and h.airflow_dag_id == "gaius_article_curate" and h.enabled
    # (2026-09-07) pg_cron classes ARE catalogued now — source pg_cron, paused in Airflow
    roll = by_id["task.fmp_roll"]
    assert roll.source == "pg_cron" and not roll.enabled and roll.airflow_dag_id == "gaius_fmp_roll"
    assert roll.cron == "7,37 * * * *" and roll.runner == "metaflow"
    assert list(by_id["task.clt_skos_label"].after) == ["task.clt_skos_admit"]


def test_watcher_starts_any_catalogued_kind(monkeypatch):
    """The watcher is not curate-specific: an own RUNNING activity of ANY
    catalogued kind (here fmp_roll — no gate) is enqueued with pg_cron's
    task_type/payload plus the activity stamp."""
    pool = FakePool()
    w, sched = _watcher(pool, monkeypatch)
    aid = "a-roll"
    w.view.activities[aid] = {
        "activity_id": aid, "kind": "fmp_roll", "peer": "gaius", "state": "running",
        "horizon_ns": co.now_ns() + 3_600_000_000_000,
    }
    actions = asyncio.run(w.workload_pass())
    assert actions == [(aid, "started_workload")]
    rows = pool.inserts()
    assert len(rows) == 1
    assert rows[0]["task_type"] == "fmp_roll"
    assert rows[0]["payload"]["activity_id"] == aid and rows[0]["payload"]["activity_kind"] == "fmp_roll"
    assert rows[0]["payload"]["source"] == "airflow"
    # a second pass finds the row and heartbeats instead of enqueueing again
    asyncio.run(w.workload_pass(at_ns=co.now_ns() + 61_000_000_000))
    assert len(pool.inserts()) == 1
    assert len(sched.named("RenewActivity")) >= 1
    # an uncatalogued kind is never started
    w.view.activities["a-x"] = {
        "activity_id": "a-x", "kind": "no_such_kind", "peer": "gaius", "state": "running",
        "horizon_ns": co.now_ns() + 3_600_000_000_000,
    }
    assert w.own_running() and all(a["kind"] != "no_such_kind" for a in w.own_running())
