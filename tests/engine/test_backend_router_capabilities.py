"""Router-level tests for dual-constraint fulfilment (mocked backends)."""

from types import SimpleNamespace

import pytest

from gaius.engine.backends.backend_router import (
    BackendRouter,
    InferenceRequest,
    InferenceResponse,
)
from gaius.engine.capabilities import (
    GURU_NOMIX,
    CapabilityPlan,
    resolve_capabilities,
)

SCAFFOLDED = (
    "<thinking>\nstep 1: consider\n<reflection>\nchecks out\n</reflection>\nadjusted\n</thinking>\n"
    "<output>\nParis\n</output>"
)


def _router(vllm_response=None, optillm_response=None):
    """A BackendRouter shell with mocked I/O surfaces (no controllers)."""
    router = BackendRouter.__new__(BackendRouter)
    router.vllm = SimpleNamespace(
        get_process=lambda alias: SimpleNamespace(port=8081)
    )

    calls = {"vllm": [], "optillm": []}

    async def fake_route_to_vllm(request, agent_config):
        calls["vllm"].append(request)
        return vllm_response

    router._route_to_vllm = fake_route_to_vllm

    async def fake_optillm_complete(optillm_request):
        calls["optillm"].append(optillm_request)
        return optillm_response

    router.optillm = SimpleNamespace(complete=fake_optillm_complete)
    router._calls = calls
    return router


def _agent_config():
    return SimpleNamespace(
        model="Qwen/Qwen3.8-27B", backend="vllm", optillm_technique=None
    )


class TestEngineNativeFulfilment:
    @pytest.mark.asyncio
    async def test_both_layers_captured(self):
        vllm_response = InferenceResponse(
            content=SCAFFOLDED,
            model="Qwen/Qwen3.8-27B",
            backend="vllm",
            output_tokens=100,
            reasoning_content="<think>native model trace</think>",
            finish_reason="stop",
        )
        router = _router(vllm_response=vllm_response)
        request = InferenceRequest(
            messages=[
                {"role": "system", "content": "You are a curator."},
                {"role": "user", "content": "Pick the capital of France."},
            ],
            agent_alias="thinking",
            plan=resolve_capabilities(["cot_reasoning", "thinking"]),
        )

        result = await router._fulfil_engine_native(request, _agent_config())

        assert result.error is None
        assert result.content == "Paris"
        layers = result.reasoning_layers
        assert [l["layer"] for l in layers] == ["model", "method"]
        assert layers[0]["text"] == "<think>native model trace</think>"
        assert layers[0]["producer"] == "Qwen/Qwen3.8-27B"
        assert layers[1]["text"].startswith("<thinking>")
        assert "<reflection>" in layers[1]["text"]
        assert result.technique == "cot_reflection"
        assert result.fulfilled_by == "cot_reflection@engine/Qwen/Qwen3.8-27B@vllm:8081"

        # The inner vLLM call carries the exact optillm scaffold assembly.
        inner = router._calls["vllm"][0]
        assert inner.plan is None and inner.technique is None
        assert inner.enable_thinking and inner.preserve_thinking
        assert inner.messages[0]["role"] == "system"
        assert "Chain of Thought (CoT) approach with reflection" in inner.messages[0]["content"]
        assert "You are a curator." in inner.messages[0]["content"]
        assert inner.messages[1] == {
            "role": "user",
            "content": "Pick the capital of France.",
        }

    @pytest.mark.asyncio
    async def test_vllm_error_passes_through(self):
        vllm_response = InferenceResponse(
            content="", model="m", backend="vllm", error="boom"
        )
        router = _router(vllm_response=vllm_response)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "q"}],
            agent_alias="thinking",
            plan=resolve_capabilities(["cot_reasoning"]),
        )
        result = await router._fulfil_engine_native(request, _agent_config())
        assert result.error == "boom"
        assert result.reasoning_layers == []

    @pytest.mark.asyncio
    async def test_scaffoldless_output_never_fabricates_method_layer(self):
        vllm_response = InferenceResponse(
            content="plain answer",
            model="m",
            backend="vllm",
            reasoning_content="",
        )
        router = _router(vllm_response=vllm_response)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "q"}],
            agent_alias="thinking",
            plan=resolve_capabilities(["cot_reasoning"]),
        )
        result = await router._fulfil_engine_native(request, _agent_config())
        assert result.content == "plain answer"
        assert result.reasoning_layers == []


class TestPlannedOptillmPath:
    @pytest.mark.asyncio
    async def test_planned_unknown_technique_fails_fast(self):
        router = _router()
        request = InferenceRequest(
            messages=[{"role": "user", "content": "q"}],
            agent_alias="thinking",
            technique="not_a_technique",
        )
        result = await router._route_to_optillm(request, _agent_config(), planned=True)
        assert result.error is not None
        assert GURU_NOMIX in result.error
        assert "cot_reflection" in result.error  # offered methods listed
        assert router._calls["optillm"] == []  # never dispatched

    @pytest.mark.asyncio
    async def test_unplanned_unknown_technique_degrades_legacy(self):
        optillm_response = SimpleNamespace(
            content="answer",
            model="m",
            technique="",
            input_tokens=1,
            output_tokens=2,
            latency_ms=3,
            error=None,
            reasoning_content="",
            finish_reason="stop",
        )
        router = _router(optillm_response=optillm_response)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "q"}],
            agent_alias="leader",
            technique="not_a_technique",
        )
        result = await router._route_to_optillm(request, _agent_config(), planned=False)
        assert result.error is None
        # degraded to NONE, dispatched anyway (legacy behavior preserved)
        assert router._calls["optillm"][0].technique.value == ""

    @pytest.mark.asyncio
    async def test_planned_scaffold_yields_method_layer(self):
        optillm_response = SimpleNamespace(
            content=SCAFFOLDED,
            model="m",
            technique="cot_reflection",
            input_tokens=1,
            output_tokens=2,
            latency_ms=3,
            error=None,
            reasoning_content="",
            finish_reason="stop",
        )
        router = _router(optillm_response=optillm_response)
        plan = CapabilityPlan(
            method="bon",
            model_capability="thinking",
            model_alias="thinking",
            engine_native=False,
            fulfilled_by="bon@optillm",
        )
        request = InferenceRequest(
            messages=[{"role": "user", "content": "q"}],
            agent_alias="thinking",
            technique="bon",
            plan=plan,
        )
        result = await router._route_to_optillm(request, _agent_config(), planned=True)
        assert result.error is None
        assert result.content == "Paris"
        assert len(result.reasoning_layers) == 1
        assert result.reasoning_layers[0]["layer"] == "method"
        assert result.fulfilled_by == "bon@optillm/m"

    @pytest.mark.asyncio
    async def test_passthrough_forwards_finish_reason_and_reasoning(self):
        optillm_response = SimpleNamespace(
            content="partial",
            model="m",
            technique="bon",
            input_tokens=1,
            output_tokens=2,
            latency_ms=3,
            error=None,
            reasoning_content="native",
            finish_reason="length",
        )
        router = _router(optillm_response=optillm_response)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "q"}],
            agent_alias="leader",
            technique="bon",
        )
        result = await router._route_to_optillm(request, _agent_config())
        assert result.finish_reason == "length"  # truncation visible again
        assert result.reasoning_content == "native"
