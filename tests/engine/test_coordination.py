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
