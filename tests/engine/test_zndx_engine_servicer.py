"""Tests for the zndx.engine.v1.Engine federation face.

Lattice accept is Engine/Status: project=gaius and capability=cognition must
appear in the body. Tests operate at the protobuf boundary with mocked services.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.grpc.servicers.zndx_engine_servicer import (
    CAPABILITY_COGNITION,
    PROJECT,
    GaiusZndxEngineServicer,
    build_status_response,
    normalize_tool_choice,
    pick_ask_replica,
    resolve_complete_alias,
)


def _services(**kwargs):
    defaults = {
        "config": SimpleNamespace(gpus=SimpleNamespace(total=6, reserved=[])),
        "orchestrator_service": None,
        "backend_router": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestBuildStatusResponse:
    def test_always_advertises_gaius_and_cognition(self):
        resp = build_status_response(_services())
        assert resp.project == PROJECT
        assert resp.total_gpus == 6
        caps = [ep.capability for ep in resp.endpoints]
        assert CAPABILITY_COGNITION in caps
        cognition = next(ep for ep in resp.endpoints if ep.capability == CAPABILITY_COGNITION)
        assert cognition.healthy is True
        assert any(s.kind == "primary" and s.url for s in resp.surfaces)

    def test_ask_picks_healthy_replica(self):
        orch = MagicMock()
        def status(name):
            if name == "interpretable":
                return SimpleNamespace(status="starting")
            if name == "interpretable-b":
                return SimpleNamespace(status="healthy")
            return None
        orch.get_endpoint_status.side_effect = status
        svc = _services(orchestrator_service=orch)
        assert resolve_complete_alias("ask", svc) == "interpretable-b"
        assert pick_ask_replica(svc) == "interpretable-b"

    def test_ask_sae_falls_through_to_thinking(self):
        orch = MagicMock()
        def status(name):
            if name == "thinking":
                return SimpleNamespace(status="healthy")
            return SimpleNamespace(status="starting")
        orch.get_endpoint_status.side_effect = status
        svc = _services(orchestrator_service=orch)
        assert resolve_complete_alias("ask-sae", svc) == "thinking"
        assert resolve_complete_alias("ask", svc) == "thinking"

    def test_includes_live_orchestrator_endpoints(self):
        orch = MagicMock()
        orch._capability_map = {"reasoning": ["qwq"]}
        orch.get_status.return_value = {
            "endpoints": {
                "qwq": {
                    "model": "Qwen/QwQ-32B",
                    "status": "healthy",
                    "gpu_ids": [4, 5],
                }
            }
        }
        resp = build_status_response(_services(orchestrator_service=orch))
        by_cap = {ep.capability: ep for ep in resp.endpoints}
        assert "reasoning" in by_cap
        assert by_cap["reasoning"].model == "Qwen/QwQ-32B"
        assert by_cap["reasoning"].healthy is True
        assert list(by_cap["reasoning"].gpu_ids) == [4, 5]

    def test_unhealthy_endpoint_not_marked_healthy(self):
        orch = MagicMock()
        orch._capability_map = {}
        orch.get_status.return_value = {
            "endpoints": {
                "fast": {"model": "mistral", "status": "starting", "gpu_ids": [0]}
            }
        }
        resp = build_status_response(_services(orchestrator_service=orch))
        fast = next(ep for ep in resp.endpoints if ep.capability == "fast")
        assert fast.healthy is False


class TestZndxServicerRpcs:
    @pytest.mark.asyncio
    async def test_status_rpc(self):
        servicer = GaiusZndxEngineServicer(_services())
        resp = await servicer.Status(zpb.StatusRequest(), MagicMock())
        assert resp.project == "gaius"
        assert any(ep.capability == "cognition" for ep in resp.endpoints)

    @pytest.mark.asyncio
    async def test_complete_forwards_to_router(self):
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=SimpleNamespace(
                content="ok",
                model="test-model",
                input_tokens=3,
                output_tokens=2,
                latency_ms=12.5,
                error=None,
            )
        )
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        req = zpb.CompleteRequest(capability="cognition", prompt="hello")
        resp = await servicer.Complete(req, MagicMock())
        router.complete.assert_awaited_once()
        assert resp.text == "ok"
        assert resp.model == "test-model"
        assert resp.prompt_tokens == 3
        assert resp.completion_tokens == 2

    @pytest.mark.asyncio
    async def test_complete_rejects_json_schema(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=MagicMock()))
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("unimplemented"))
        req = zpb.CompleteRequest(prompt="x", json_schema='{"type":"object"}')
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(req, ctx)
        ctx.abort.assert_awaited()

    @pytest.mark.asyncio
    async def test_complete_aborts_on_empty_error_string(self):
        """httpx.ReadTimeout stringifies to '' — must not look like success."""
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=SimpleNamespace(
                content="",
                model="Qwen/Qwen3.8-27B",
                input_tokens=0,
                output_tokens=0,
                latency_ms=30000,
                error="",
            )
        )
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("internal"))
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(zpb.CompleteRequest(prompt="sitrep"), ctx)
        ctx.abort.assert_awaited()
        detail = ctx.abort.await_args.args[1]
        assert "complete[" in detail

    @pytest.mark.asyncio
    async def test_complete_unavailable_without_router(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=None))
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("unavailable"))
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(zpb.CompleteRequest(prompt="x"), ctx)

    @pytest.mark.asyncio
    async def test_remediate_unimplemented(self):
        servicer = GaiusZndxEngineServicer(_services())
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("unimplemented"))
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Remediate(zpb.RemediationRequest(), ctx)


TOOLS_JSON = (
    '[{"type":"function","function":{"name":"run_terminal_command",'
    '"description":"Run a shell command",'
    '"parameters":{"type":"object","properties":{"command":{"type":"string"}}}}}]'
)


def _ok_router():
    router = MagicMock()
    router.complete = AsyncMock(
        return_value=SimpleNamespace(
            content='<tool_call>{"name":"run_terminal_command",'
            '"arguments":{"command":"ss -ltnp"}}</tool_call>',
            model="Qwen/Qwen3.8-27B",
            input_tokens=10,
            output_tokens=20,
            latency_ms=900.0,
            error=None,
            reasoning_content="check the ports",
            finish_reason="tool_calls",
        )
    )
    return router


class TestCompleteToolCalling:
    """Web Terminal turns must carry the harness tools[] into Complete.

    The thinking endpoint runs an engine-level tool parser: markup emitted
    without a tools[] declaration is swallowed and the turn ends after one
    step with bare reasoning.
    """

    def test_tool_choice_defaults_to_auto(self):
        assert normalize_tool_choice("") == "auto"
        assert normalize_tool_choice("   ") == "auto"

    def test_tool_choice_modes_pass_through(self):
        assert normalize_tool_choice("auto") == "auto"
        assert normalize_tool_choice("required") == "required"
        assert normalize_tool_choice("none") == "none"

    def test_tool_choice_named_tool_is_forwarded(self):
        named = normalize_tool_choice(
            '{"type":"function","function":{"name":"read_file"}}'
        )
        assert named["function"]["name"] == "read_file"

    def test_tool_choice_rejects_garbage(self):
        with pytest.raises(ValueError, match="TOOLCHOICE"):
            normalize_tool_choice("maybe")

    @pytest.mark.asyncio
    async def test_tools_reach_the_backend_with_auto(self):
        router = _ok_router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        req = zpb.CompleteRequest(
            capability="thinking", prompt="what port?", tools_json=TOOLS_JSON
        )
        resp = await servicer.Complete(req, MagicMock())
        kwargs = router.complete.await_args.kwargs
        assert kwargs["extra_body"]["tool_choice"] == "auto"
        assert kwargs["extra_body"]["tools"][0]["function"]["name"] == (
            "run_terminal_command"
        )
        # Thinking stays on for a tool turn — only guided_json disables it.
        assert kwargs["enable_thinking"] is True
        assert kwargs["preserve_thinking"] is True
        assert resp.finish_reason == "tool_calls"
        assert "<tool_call>" in resp.text

    @pytest.mark.asyncio
    async def test_required_is_forwarded(self):
        router = _ok_router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        req = zpb.CompleteRequest(
            capability="thinking",
            prompt="what port?",
            tools_json=TOOLS_JSON,
            tool_choice="required",
        )
        await servicer.Complete(req, MagicMock())
        assert router.complete.await_args.kwargs["extra_body"]["tool_choice"] == (
            "required"
        )

    @pytest.mark.asyncio
    async def test_no_tools_sends_no_extra_body(self):
        router = _ok_router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        await servicer.Complete(
            zpb.CompleteRequest(capability="thinking", prompt="hi"), MagicMock()
        )
        assert router.complete.await_args.kwargs["extra_body"] is None

    @pytest.mark.asyncio
    async def test_tools_with_json_schema_is_rejected(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=MagicMock()))
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("invalid"))
        req = zpb.CompleteRequest(
            prompt="x", tools_json=TOOLS_JSON, json_schema='{"type":"object"}'
        )
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(req, ctx)
        assert "TOOLSCHEMA" in ctx.abort.await_args.args[1]

    @pytest.mark.asyncio
    async def test_malformed_tools_json_is_rejected(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=MagicMock()))
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("invalid"))
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(
                zpb.CompleteRequest(prompt="x", tools_json="{not json"), ctx
            )
        assert "TOOLSJSON" in ctx.abort.await_args.args[1]

    @pytest.mark.asyncio
    async def test_empty_tools_array_is_rejected(self):
        servicer = GaiusZndxEngineServicer(_services(backend_router=MagicMock()))
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("invalid"))
        with pytest.raises(grpc.aio.AbortError):
            await servicer.Complete(
                zpb.CompleteRequest(prompt="x", tools_json="[]"), ctx
            )
        assert "TOOLSJSON" in ctx.abort.await_args.args[1]
