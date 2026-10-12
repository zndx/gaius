"""An admitted model takes the whole GPU. The resident model yields first."""

from __future__ import annotations

import os

import pytest

from gaius.engine.resources.gpu_occupancy import (
    GpuOccupant,
    GpuStillShared,
    classify_workload,
    occupants_to_yield,
    prepare_exclusive_gpu,
    scheduling_tasks_for,
    terminate_occupant,
)


def test_classify_names_the_model_mix() -> None:
    assert classify_workload("python -m gaius.engine.services.clt_worker", gpu=4, pid=7) == "clt"
    assert classify_workload("VLLM::Worker_TP0", gpu=0, pid=8) == "thinking"
    assert (
        classify_workload("d3-runtime/bin/python d3_server.py --port 8096", gpu=5, pid=9)
        == "d3-flash-0"
    )
    assert classify_workload("d3_server.py --port 8097", gpu=4, pid=10) == "d3-flash-1"
    assert classify_workload("flows/docling/flow.py step extract_topics", gpu=4, pid=11) == (
        "resident-11"
    )


def test_yield_list_keeps_the_admitted_owner() -> None:
    rows = [
        GpuOccupant(0, 1, 21000, "VLLM::Worker_TP0", "thinking"),
        GpuOccupant(4, 2, 6000, "clt_worker", "clt"),
        GpuOccupant(4, 3, 700, "flow.py", "resident-3"),
        GpuOccupant(5, 4, 4, "idle", "resident-4"),
    ]
    yielded = occupants_to_yield(rows, keep={"thinking", "d3-flash-0", "d3-flash-1"})
    assert [row.workload for row in yielded] == ["clt", "resident-3"]


def test_scheduler_sees_clt_and_not_a_dead_resident_pid() -> None:
    rows = [
        GpuOccupant(0, 1, 21000, "VLLM::Worker_TP0", "thinking"),
        GpuOccupant(4, 2, 6000, "python -m gaius.engine.services.clt_worker", "clt"),
        GpuOccupant(4, 3, 700, "flow.py", "resident-3"),
    ]
    tasks = scheduling_tasks_for(rows, already={"thinking"})
    assert [task.endpoint_name for task in tasks] == ["clt"]
    assert tasks[0].fixed_gpu_ids == [4]
    assert tasks[0].is_current is True


def test_prepare_stops_clt_and_waits_for_the_card() -> None:
    shots = [
        [GpuOccupant(4, 2, 6000, "clt_worker", "clt")],
        [],
    ]
    stopped: list[str] = []

    def list_fn():
        return shots.pop(0) if shots else []

    victims = prepare_exclusive_gpu(
        4,
        owner="d3-flash-1",
        list_fn=list_fn,
        stop_clt=lambda: stopped.append("clt"),
        terminate=lambda pid: (_ for _ in ()).throw(AssertionError(pid)),
        sleep=lambda _s: None,
        timeout_s=1,
    )
    assert stopped == ["clt"]
    assert [row.pid for row in victims] == [2]


def test_prepare_refuses_to_share_with_thinking() -> None:
    def list_fn():
        return [GpuOccupant(0, 1, 21000, "VLLM::Worker_TP0", "thinking")]

    with pytest.raises(GpuStillShared, match="thinking"):
        prepare_exclusive_gpu(
            0,
            owner="d3-flash-0",
            list_fn=list_fn,
            stop_clt=lambda: (_ for _ in ()).throw(AssertionError("clt")),
            sleep=lambda _s: None,
        )


def test_prepare_terminates_a_resident_and_fails_closed_if_it_stays() -> None:
    occupant = GpuOccupant(4, 99, 764, "flow.py", "resident-99")
    terminated: list[int] = []

    def list_fn():
        return [occupant]

    with pytest.raises(GpuStillShared, match="resident-99"):
        prepare_exclusive_gpu(
            4,
            owner="d3-flash-1",
            list_fn=list_fn,
            stop_clt=lambda: (_ for _ in ()).throw(AssertionError("clt")),
            terminate=terminated.append,
            sleep=lambda _s: None,
            timeout_s=0,
        )
    assert terminated == [99]


def test_terminate_refuses_the_engine() -> None:
    with pytest.raises(RuntimeError, match="refusing"):
        terminate_occupant(os.getpid())
    with pytest.raises(RuntimeError, match="refusing"):
        terminate_occupant(1)
