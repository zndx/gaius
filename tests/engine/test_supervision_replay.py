"""Replay derivation from the engine's own rows — pure, no database.

The load-bearing case: a deferral is a clean row (error NULL) whose
result.status is 'deferred'; it MUST surface as DEFERRED plus a synthetic
NOTADMITTED admission (the Backlog's slot-0 entry). `error IS NULL` is not
success — that is how a 6 h objective stayed green through 28 deferrals.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gaius.engine.services.supervision_replay import (
    events_from_forecast_row,
    events_from_healing_row,
    events_from_task_row,
    events_from_verification_row,
    order_events,
)

T0 = datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 4, 15, 41, tzinfo=timezone.utc)


def _row(**kw):
    base = {"id": 29260, "task_type": "clt_skos_admit", "source": "pg_cron", "scheduled_for": T0,
            "picked_up_at": T0, "heartbeat_at": None, "completed_at": T1, "result": None, "error": None}
    base.update(kw)
    return base


def test_deferred_row_yields_deferred_and_admission() -> None:
    evs = order_events(events_from_task_row(_row(result={"status": "deferred", "reason": "yk_admission", "workload_id": "w"}), 0))
    kinds = [(e.kind, e.payload.get("state") or e.payload.get("phase")) for e in evs]
    assert kinds == [("task", "CLAIMED"), ("task", "DEFERRED"), ("admission", "NOTADMITTED")]
    assert all(e.replayed for e in evs)
    assert evs[1].payload["reason"] == "yk_admission" and evs[1].at_unix_ms == int(T1.timestamp() * 1000)


def test_error_text_without_status_is_error_not_completed() -> None:
    evs = events_from_task_row(_row(result=None, error="Step start failed"), 0)
    assert [e.payload["state"] for _, e in evs] == ["CLAIMED", "ERROR"]


def test_completed_status_wins_and_since_filters() -> None:
    evs = events_from_task_row(_row(result={"status": "completed"}), since_ms=int(T1.timestamp() * 1000) - 1)
    assert [e.payload["state"] for _, e in evs] == ["COMPLETED"]  # the claim predates `since`


def test_heartbeat_only_when_after_claim() -> None:
    hb = datetime(2026, 9, 4, 15, 35, tzinfo=timezone.utc)
    evs = events_from_task_row(_row(heartbeat_at=hb, completed_at=None), 0)
    assert [e.payload["state"] for _, e in evs] == ["CLAIMED", "HEARTBEAT"]


def test_watchdog_forecast_is_a_reset() -> None:
    evs = events_from_forecast_row({"id": 1, "created_at": T1, "observer": "watchdog:pg_cron.task_reset",
                                    "proposition": "a live worker owns task 29346", "task_class": "fmp_roll", "task_id": 29346})
    assert evs[0][1].payload["state"] == "RESET" and evs[0][1].payload["reason"] == "watchdog"


def test_verification_and_healing_rows() -> None:
    v = events_from_verification_row({"id": 5, "objective_name": "content_currency", "run_id": "r", "verdict": "inconclusive",
                                      "gates_passed": 2, "gates_total": 3, "gate_results": [{"gate": "a", "verdict": "pass", "evidence": "e"}],
                                      "started_at": T0, "completed_at": T1})
    assert v[0][1].payload["verdict"] == "INCONCLUSIVE" and v[0][1].payload["gates"][0]["name"] == "a"
    h = events_from_healing_row({"id": 9, "created_at": T1, "event_type": "sequence_started", "endpoint": "thinking",
                                 "tier": 1, "sequence_id": "s", "sequence_num": 1, "payload": {"failure_mode_id": "EP.GPUOOM"}})
    assert h[0][1].payload["fingerprint"] == "EP.GPUOOM:thinking" and h[0][1].payload["state"] == "ACTIVE"


def test_ordering_key_interleaves_sources_by_time() -> None:
    keyed = events_from_task_row(_row(result={"status": "completed"}), 0)
    keyed += events_from_healing_row({"id": 1, "created_at": T0, "event_type": "sequence_started", "endpoint": "e",
                                      "tier": 0, "sequence_id": "s", "sequence_num": 1, "payload": {}})
    evs = order_events(keyed)
    assert [e.at_unix_ms for e in evs] == sorted(e.at_unix_ms for e in evs)
    assert evs[0].kind == "task" and evs[1].kind == "incident"  # same time: scheduled_tasks ranks first
