"""decisions means thinking + dual-d3-flash. No GPU, no d3_server."""

from types import SimpleNamespace

import httpx
import pytest

from gaius.engine.backends.decisions import (
    DECISIONS_MODEL_ID,
    D3_FLASH_REPLICAS,
    DecisionError,
    DecisionResult,
    GURU_BADDECISION,
    GURU_NODECISION,
    MAX_CHOICE_OPTIONS,
    build_systemone_body,
    decisions_replicas,
    parse_decision_response,
    post_decision_replicas,
    _raise_for_status,
)
from gaius.engine.resources.manager import ResourceManager
from gaius.engine.scheduling.types import SchedulingTask
from gaius.engine.services.orchestrator_service import OrchestratorService
from gaius.models.registry import TaskType


def _question(n: int) -> dict:
    return {f"o{i}": None for i in range(n)}


def test_body_is_model_state_questions_only() -> None:
    body = build_systemone_body(
        "the parcel arrived",
        [("q", "noul", "", None)],
        instructions="be brief",
        model=DECISIONS_MODEL_ID,
    )
    assert set(body) == {"model", "state", "questions"}
    assert body["state"] == "be brief\n\nthe parcel arrived"
    assert body["questions"]["q"] == {"type": "noul", "criteria": None}
    assert "chat_template_kwargs" not in body


def test_instructions_require_a_string_state() -> None:
    with pytest.raises(DecisionError, match="string state"):
        build_systemone_body(
            {"parcel": "arrived"},
            [("q", "noul", "", None)],
            instructions="be brief",
        )


def test_cache_salt_is_rejected() -> None:
    with pytest.raises(DecisionError, match="cache_salt") as exc:
        build_systemone_body(
            "x",
            [("q", "noul", "", None)],
            cache_salt="salt",
        )
    assert exc.value.guru == GURU_BADDECISION
    assert exc.value.retryable is False


def test_choice_limit_is_the_d3_runtime_max() -> None:
    ok = build_systemone_body(
        "x",
        [("q", "choice", "pick", _question(27))],
    )
    assert len(ok["questions"]["q"]["criteria"]) == 27
    with pytest.raises(DecisionError, match=str(MAX_CHOICE_OPTIONS)):
        build_systemone_body(
            "x",
            [("q", "choice", "pick", _question(MAX_CHOICE_OPTIONS + 1))],
        )


def test_score_levels_must_be_distinct() -> None:
    build_systemone_body("x", [("q", "score", "", ["low", "high"])])
    with pytest.raises(DecisionError, match="distinct"):
        build_systemone_body("x", [("q", "score", "", ["low", "low"])])


def test_d3_response_without_object_is_accepted() -> None:
    result = parse_decision_response(
        {
            "model": DECISIONS_MODEL_ID,
            "answers": {"q": {"noul": 0.8}},
            "usage": {"input_tokens": 12, "output_tokens": 0},
        }
    )
    assert result.model == DECISIONS_MODEL_ID
    assert result.answers["q"]["noul"] == 0.8
    assert result.diagnostics == {}
    assert result.input_tokens == 12
    assert result.output_tokens == 0


def test_status_mapping() -> None:
    with pytest.raises(DecisionError) as bad:
        _raise_for_status(httpx.Response(422, text="unknown field"))
    assert bad.value.guru == GURU_BADDECISION
    assert bad.value.retryable is False
    with pytest.raises(DecisionError) as busy:
        _raise_for_status(httpx.Response(503, text="busy"))
    assert busy.value.guru == GURU_NODECISION
    assert busy.value.retryable is True


def test_decisions_target_is_thinking_plus_both_replicas() -> None:
    thinking = SchedulingTask(
        task_id="thinking",
        endpoint_name="thinking",
        model_id="Qwen/Qwen3.8-27B",
        required_gpus=4,
        capability="thinking",
        fixed_gpu_ids=[0, 1, 2, 3],
        is_current=True,
    )
    embedding = SchedulingTask(
        task_id="embedding",
        endpoint_name="embedding",
        model_id="lightonai/ColBERT-Zero",
        required_gpus=1,
        capability="open-embedding",
        fixed_gpu_ids=[4],
        is_current=True,
    )
    request = SimpleNamespace(
        required_capabilities=[TaskType.DECISIONS],
        priority=SimpleNamespace(value=2),
    )
    target = OrchestratorService._build_target_scheduling_tasks(
        None, request, [thinking, embedding]
    )
    names = [task.endpoint_name for task in target]
    assert names.count("thinking") == 1
    assert list(D3_FLASH_REPLICAS) == [n for n in names if n.startswith("d3-flash")]
    assert "embedding" not in names
    assert "cap_decisions" not in names
    flash = next(task for task in target if task.endpoint_name == "d3-flash-0")
    assert flash.required_gpus == 1
    assert flash.model_id == DECISIONS_MODEL_ID
    assert flash.capability == "decisions"


def test_decisions_plan_yields_clt_and_assigns_whole_cards() -> None:
    from gaius.engine.scheduling.makespan_scheduler import MakespanScheduler
    from gaius.engine.scheduling.types import TransitionType

    thinking = SchedulingTask(
        task_id="thinking",
        endpoint_name="thinking",
        model_id="Qwen/Qwen3.8-27B",
        required_gpus=4,
        capability="thinking",
        fixed_gpu_ids=[0, 1, 2, 3],
        is_current=True,
    )
    clt = SchedulingTask(
        task_id="clt",
        endpoint_name="clt",
        model_id="Qwen/Qwen3-1.7B",
        required_gpus=1,
        capability="clt",
        prefer_contiguous=False,
        fixed_gpu_ids=[4],
        is_current=True,
    )
    request = SimpleNamespace(
        required_capabilities=[TaskType.DECISIONS],
        priority=SimpleNamespace(value=2),
    )
    target = OrchestratorService._build_target_scheduling_tasks(
        None, request, [thinking, clt]
    )
    result = MakespanScheduler(total_gpus=6).plan_transition([thinking, clt], target)
    assert result.success, result.error
    plan = result.plan
    assert plan is not None
    assert "clt" in plan.evicted_endpoints
    assert "thinking" not in plan.evicted_endpoints
    stops = [
        step.endpoint_name
        for step in plan.steps
        if step.transition_type == TransitionType.STOP_ENDPOINT
    ]
    assert stops == ["clt"]
    assert plan.gpu_assignments["thinking"] == [0, 1, 2, 3]
    light = set(plan.gpu_assignments["d3-flash-0"]) | set(plan.gpu_assignments["d3-flash-1"])
    assert light == {4, 5}
    flat = [gpu for gpus in plan.gpu_assignments.values() for gpu in gpus]
    assert len(flat) == len(set(flat))


def test_both_up_mode_is_mixed() -> None:
    both = ResourceManager.get_current_mode(
        SimpleNamespace(
            allocations={"thinking": object(), "d3-flash-0": object(), "d3-flash-1": object()}
        )
    )
    flash_only = ResourceManager.get_current_mode(
        SimpleNamespace(allocations={"d3-flash-0": object(), "d3-flash-1": object()})
    )
    thinking_only = ResourceManager.get_current_mode(
        SimpleNamespace(allocations={"thinking": object()})
    )
    assert both == "mixed"
    assert flash_only == "decisions"
    assert thinking_only == "default"


class _Status:
    def __init__(self, status: str, port: int) -> None:
        self.status = status
        self.port = port


def test_replicas_prefer_flash_order_and_skip_starting() -> None:
    class _Orch:
        _capability_map = {"decisions": ["d3-flash-1", "extra-decider"]}

        def get_endpoint_status(self, alias: str):
            table = {
                "d3-flash-0": _Status("healthy", 8096),
                "d3-flash-1": _Status("starting", 8097),
                "extra-decider": _Status("ready", 8098),
            }
            return table.get(alias)

    found = decisions_replicas(SimpleNamespace(orchestrator_service=_Orch()))
    assert found == [
        ("http://127.0.0.1:8096", "d3-flash-0"),
        ("http://127.0.0.1:8098", "extra-decider"),
    ]


@pytest.mark.asyncio
async def test_fanout_fails_over_only_when_retryable() -> None:
    calls: list[str] = []

    async def poster(base: str, body: dict, *, timeout_s: float = 180.0):
        calls.append(base)
        if base.endswith("8096"):
            raise DecisionError(GURU_NODECISION, "busy", retryable=True)
        return DecisionResult(
            id="d1",
            model=DECISIONS_MODEL_ID,
            answers={"q": {"noul": 1}},
            diagnostics={},
            input_tokens=1,
            output_tokens=0,
            raw={},
        )

    replicas = [
        ("http://127.0.0.1:8096", "d3-flash-0"),
        ("http://127.0.0.1:8097", "d3-flash-1"),
    ]
    result, base, alias, cursor = await post_decision_replicas(
        replicas, {"state": "x"}, cursor=0, poster=poster
    )
    assert result.id == "d1"
    assert alias == "d3-flash-1"
    assert base.endswith("8097")
    assert cursor == 2
    assert calls == [
        "http://127.0.0.1:8096",
        "http://127.0.0.1:8097",
    ]

    calls.clear()

    async def bad(base: str, body: dict, *, timeout_s: float = 180.0):
        calls.append(base)
        raise DecisionError(GURU_BADDECISION, "nope")

    with pytest.raises(DecisionError, match="nope") as exc:
        await post_decision_replicas(replicas, {"state": "x"}, cursor=1, poster=bad)
    assert exc.value.retryable is False
    assert calls == ["http://127.0.0.1:8097"]


def test_decisions_handover_asks_the_federation_to_yield() -> None:
    from gaius.engine.services.coordination import decisions_handover_declaration

    declaration = decisions_handover_declaration()
    assert declaration["kind"] == "decisions"
    assert declaration["postures"] == {"federation.gpu": "yield"}
    assert {c["leaf"]: c["gpu"] for c in declaration["claims"]} == {
        "root.internal.inference.heavy": 4,
        "root.internal.inference.light": 2,
    }
    precluded = declaration["precludes"]
    assert "root.internal.inference.agent-rtc" in precluded
    assert "root.internal.inference.medium" in precluded
    assert "root.internal.inference.extract" in precluded
    assert "root.internal.inference.light" not in precluded
    assert "root.internal.inference.heavy" not in precluded
