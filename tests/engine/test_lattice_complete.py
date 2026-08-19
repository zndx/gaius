"""Complete must use the intended capability model and fail immediately."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaius.flows.lattice import (
    GURU_TRUNCATED,
    GURU_UNHEALTHY,
    GURU_WRONGMODEL,
    _require_healthy_capability,
)
from gaius.hx.lineage.events import Job, Run, RunEvent, RunState


def test_require_healthy_thinking_fails_when_down() -> None:
    ep = SimpleNamespace(capability="thinking", healthy=False, model="Qwen3.8-27B", detail="stopped")
    stub = SimpleNamespace(Status=lambda *_a, **_k: SimpleNamespace(endpoints=[ep]))
    with pytest.raises(RuntimeError, match=GURU_UNHEALTHY):
        _require_healthy_capability(stub, "thinking", "127.0.0.1:50051", timeout_s=1.0)


def test_require_healthy_thinking_returns_status_model() -> None:
    ep = SimpleNamespace(
        capability="thinking", healthy=True, model="Qwen/Qwen3.8-27B", detail=""
    )
    stub = SimpleNamespace(Status=lambda *_a, **_k: SimpleNamespace(endpoints=[ep]))
    assert (
        _require_healthy_capability(stub, "thinking", "127.0.0.1:50051", timeout_s=1.0)
        == "Qwen/Qwen3.8-27B"
    )


def test_ol_event_type_is_run_state() -> None:
    job = Job(namespace="gaius.flows", name="clt_skos_label")
    ev = RunEvent.start(job, [])
    body = ev.to_ol_dict()
    assert body["eventType"] == "START"
    fail = RunEvent.fail(Run(), job, [], "boom")
    assert fail.to_ol_dict()["eventType"] == "FAIL"
    assert fail.run_state == RunState.FAIL


def test_truncated_guru_constant() -> None:
    assert GURU_TRUNCATED.startswith("#EP.")
    assert GURU_WRONGMODEL.startswith("#EP.")
