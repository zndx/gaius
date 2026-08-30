"""zndx Complete capabilities[] wiring: planner, layers, NOMIX, restrictions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from gaius.engine.capabilities import GURU_NOMIX
from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.grpc.servicers.zndx_engine_servicer import GaiusZndxEngineServicer


def _services(**kwargs):
    defaults = {
        "config": SimpleNamespace(gpus=SimpleNamespace(total=6, reserved=[])),
        "orchestrator_service": None,
        "backend_router": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _router(**overrides):
    fields = {
        "content": "Paris",
        "model": "Qwen/Qwen3.8-27B",
        "input_tokens": 10,
        "output_tokens": 20,
        "latency_ms": 900.0,
        "error": None,
        "reasoning_content": "<think>native</think>",
        "finish_reason": "stop",
        "reasoning_layers": [
            {"layer": "model", "producer": "Qwen/Qwen3.8-27B", "text": "<think>native</think>", "tokens": 0},
            {"layer": "method", "producer": "cot_reflection@engine", "text": "<thinking>t</thinking>", "tokens": 20},
        ],
        "fulfilled_by": "cot_reflection@engine/Qwen/Qwen3.8-27B@vllm:8081",
    }
    fields.update(overrides)
    router = MagicMock()
    router.complete = AsyncMock(return_value=SimpleNamespace(**fields))
    return router


def _abort_ctx():
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("aborted"))
    return ctx


class TestCompleteCapabilities:
    @pytest.mark.asyncio
    async def test_dual_cap_maps_layers_and_fulfilled_by(self):
        router = _router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        req = zpb.CompleteRequest(
            capabilities=["cot_reasoning", "thinking"], prompt="capital of France?"
        )
        resp = await servicer.Complete(req, MagicMock())
        assert resp.text == "Paris"
        assert resp.fulfilled_by.startswith("cot_reflection@engine/")
        assert [l.layer for l in resp.reasoning] == ["model", "method"]
        assert resp.reasoning[0].text == "<think>native</think>"
        assert resp.reasoning[1].tokens == 20

        # The plan reached the router, and the alias came from the planner.
        kwargs = router.complete.await_args.kwargs
        assert kwargs["agent_alias"] == "thinking"
        assert kwargs["plan"] is not None
        assert kwargs["plan"].method == "cot_reflection"
        assert kwargs["plan"].engine_native is True
        # optillm-parity defaults applied when the request left them unset
        assert kwargs["temperature"] == pytest.approx(0.6)
        assert kwargs["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_nomix_aborts_failed_precondition(self):
        servicer = GaiusZndxEngineServicer(
            _services(backend_router=_router())
        )
        ctx = _abort_ctx()
        req = zpb.CompleteRequest(capabilities=["cot_reasoning", "sae"], prompt="x")
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(req, ctx)
        code, detail = ctx.abort.await_args.args[:2]
        assert code == grpc.StatusCode.FAILED_PRECONDITION
        assert GURU_NOMIX in detail
        assert "offered methods:" in detail

    @pytest.mark.asyncio
    async def test_method_plus_tools_is_invalid(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=_router()))
        ctx = _abort_ctx()
        req = zpb.CompleteRequest(
            capabilities=["cot_reasoning"],
            prompt="x",
            tools_json='[{"type":"function"}]',
        )
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(req, ctx)
        code, detail = ctx.abort.await_args.args[:2]
        assert code == grpc.StatusCode.INVALID_ARGUMENT
        assert "one-shot" in detail

    @pytest.mark.asyncio
    async def test_method_plus_messages_json_is_invalid(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=_router()))
        ctx = _abort_ctx()
        req = zpb.CompleteRequest(
            capabilities=["cot_reasoning"],
            prompt="x",
            messages_json='[{"role":"user","content":"hi"}]',
        )
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(req, ctx)
        assert ctx.abort.await_args.args[0] == grpc.StatusCode.INVALID_ARGUMENT

    @pytest.mark.asyncio
    async def test_empty_capabilities_keeps_legacy_path(self):
        router = _router(reasoning_layers=[], fulfilled_by="")
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        req = zpb.CompleteRequest(capability="cognition", prompt="hello")
        resp = await servicer.Complete(req, MagicMock())
        assert resp.text == "Paris"
        assert resp.fulfilled_by == ""
        assert len(resp.reasoning) == 0
        kwargs = router.complete.await_args.kwargs
        assert kwargs["plan"] is None
        assert kwargs["agent_alias"] == "thinking"  # cognition → thinking cascade
        assert kwargs["temperature"] == pytest.approx(0.7)  # legacy defaults

    @pytest.mark.asyncio
    async def test_model_only_capabilities_no_method_defaults(self):
        router = _router(reasoning_layers=[], fulfilled_by="direct@thinking")
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        req = zpb.CompleteRequest(capabilities=["thinking"], prompt="hello")
        resp = await servicer.Complete(req, MagicMock())
        assert resp.text == "Paris"
        kwargs = router.complete.await_args.kwargs
        assert kwargs["plan"].method is None
        assert kwargs["max_tokens"] == 2048  # legacy defaults for model-only
