"""BackendRouter must record split prompt/completion tokens.

The yield tape and gaius.inference.tokens_{in,out} stay at 0 if route()
only passes the legacy tokens= sum.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaius.engine.backends.backend_router import (
    BackendRouter,
    InferenceRequest,
    _metrics_provider,
)
from gaius.engine.backends.vllm_controller import VLLMResponse
from gaius.engine.config import AgentConfig, EngineConfig
from gaius.engine.resources.manager import ResourceManager


class _FakeMetrics:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record_inference(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _HealthyProc:
    status = SimpleNamespace(value="healthy")


class _FakeVllm:
    def __init__(self, response: VLLMResponse) -> None:
        self._response = response
        self.last_request = None

    def get_process(self, agent_alias: str) -> _HealthyProc:
        assert agent_alias == "thinking"
        return _HealthyProc()

    async def complete(self, request) -> VLLMResponse:
        self.last_request = request
        return self._response


def _thinking_router(vllm: _FakeVllm) -> BackendRouter:
    config = EngineConfig()
    config.agents["thinking"] = AgentConfig(
        name="thinking",
        alias="thinking",
        description="heavy",
        model="Qwen/Qwen3.8-27B",
        backend="vllm",
    )
    return BackendRouter(
        config=config,
        resource_manager=ResourceManager(config),
        vllm_controller=vllm,  # type: ignore[arg-type]
        optillm_controller=SimpleNamespace(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_route_records_tokens_in_and_out(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = _FakeMetrics()
    monkeypatch.setattr(
        "gaius.engine.backends.backend_router.EngineMetrics.get_instance",
        lambda: metrics,
    )
    vllm = _FakeVllm(
        VLLMResponse(
            content="ok",
            model="Qwen/Qwen3.8-27B",
            input_tokens=61,
            output_tokens=141,
            latency_ms=5230,
        )
    )
    router = _thinking_router(vllm)
    response = await router.route(
        InferenceRequest(
            messages=[{"role": "user", "content": "hi"}],
            agent_alias="thinking",
        )
    )
    assert response.input_tokens == 61
    assert response.output_tokens == 141
    assert len(metrics.calls) == 1
    rec = metrics.calls[0]
    assert rec["model"] == "thinking"
    assert rec["tokens_in"] == 61
    assert rec["tokens_out"] == 141
    assert rec["tokens"] == 202
    assert rec["success"] is True
    assert rec["provider"] == "local"


@pytest.mark.asyncio
async def test_instruct_alias_records_as_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = _FakeMetrics()
    monkeypatch.setattr(
        "gaius.engine.backends.backend_router.EngineMetrics.get_instance",
        lambda: metrics,
    )
    vllm = _FakeVllm(
        VLLMResponse(
            content="ok",
            model="Qwen/Qwen3.8-27B",
            input_tokens=10,
            output_tokens=20,
            latency_ms=100,
        )
    )
    router = _thinking_router(vllm)
    await router.route(
        InferenceRequest(
            messages=[{"role": "user", "content": "hi"}],
            agent_alias="instruct",
        )
    )
    assert metrics.calls[0]["model"] == "thinking"
    assert metrics.calls[0]["tokens_in"] == 10
    assert metrics.calls[0]["tokens_out"] == 20


def test_metrics_provider_maps_backends() -> None:
    assert _metrics_provider("vllm") == "local"
    assert _metrics_provider("optillm") == "local"
    assert _metrics_provider("external:xai") == "xai"
    assert _metrics_provider("cerebras") == "cerebras"
    assert _metrics_provider("") == ""
