"""Operating profiles (capabilities.md §Operating profiles): instruct = the thinking model at effort low.

The SERVING engine aligns thinking / reasoning_effort to the requested model capability, reports the
applied profile on CompleteResponse.profile, advertises profiled capabilities in Status and in
WorkloadOffer.profiles. Ægir (a non-hosting peer) resolves `instruct` by our Status.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gaius.engine.capabilities import OPERATING_PROFILES, operating_profile, profiles_for
from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.grpc.servicers.zndx_engine_servicer import (
    GaiusZndxEngineServicer,
    build_status_response,
)


def _services(**kwargs):
    defaults = {
        "config": SimpleNamespace(gpus=SimpleNamespace(total=6, reserved=[]), agents={}),
        "orchestrator_service": None,
        "backend_router": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _router(**overrides):
    fields = {
        "content": "Paris", "model": "Qwen/Qwen3.8-27B", "input_tokens": 10, "output_tokens": 20,
        "latency_ms": 900.0, "error": None, "reasoning_content": "<think>brief</think>",
        "finish_reason": "stop", "reasoning_layers": [], "fulfilled_by": "direct@thinking",
    }
    fields.update(overrides)
    router = MagicMock()
    router.complete = AsyncMock(return_value=SimpleNamespace(**fields))
    return router


def test_vocabulary():
    assert operating_profile("instruct") == OPERATING_PROFILES["instruct"]
    assert OPERATING_PROFILES["instruct"].thinking is True  # thinking stays ON — same layer structure
    assert OPERATING_PROFILES["instruct"].reasoning_effort == "low"
    assert OPERATING_PROFILES["thinking"].reasoning_effort == "xhigh"
    assert operating_profile("vision") is None and operating_profile("") is None
    assert [p.capability for p in profiles_for(("thinking", "instruct", "vision", "complete"))] == ["thinking", "instruct"]


class TestCompleteAlignsToProfile:
    @pytest.mark.asyncio
    async def test_instruct_runs_the_model_at_effort_low_with_thinking_on(self):
        router = _router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        resp = await servicer.Complete(zpb.CompleteRequest(capability="instruct", prompt="q"), MagicMock())
        kw = router.complete.await_args.kwargs
        assert kw["agent_alias"] == "instruct"  # the router's alias table maps it onto the thinking endpoint
        assert kw["enable_thinking"] is True and kw["preserve_thinking"] is True
        assert kw["reasoning_effort"] == "low"
        assert resp.HasField("profile")
        assert (resp.profile.capability, resp.profile.thinking, resp.profile.reasoning_effort) == ("instruct", True, "low")
        assert resp.reasoning_content == "<think>brief</think>"  # a model layer still arrives

    @pytest.mark.asyncio
    async def test_thinking_keeps_xhigh(self):
        router = _router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        resp = await servicer.Complete(zpb.CompleteRequest(capability="thinking", prompt="q"), MagicMock())
        assert router.complete.await_args.kwargs["reasoning_effort"] == "xhigh"
        assert resp.profile.reasoning_effort == "xhigh" and resp.profile.thinking is True

    @pytest.mark.asyncio
    async def test_guided_json_still_disables_thinking_and_reports_it(self):
        router = _router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        resp = await servicer.Complete(
            zpb.CompleteRequest(capability="instruct", prompt="q", json_schema='{"type":"object"}'), MagicMock())
        assert router.complete.await_args.kwargs["enable_thinking"] is False
        assert resp.profile.thinking is False and resp.profile.reasoning_effort == ""

    @pytest.mark.asyncio
    async def test_unprofiled_capability_runs_at_model_default(self):
        router = _router()
        servicer = GaiusZndxEngineServicer(_services(backend_router=router))
        resp = await servicer.Complete(zpb.CompleteRequest(capability="cognition", prompt="q"), MagicMock())
        kw = router.complete.await_args.kwargs
        assert kw["enable_thinking"] is True and kw["reasoning_effort"] == "xhigh"
        assert resp.profile.capability == "cognition" and resp.profile.note == ""


def test_status_advertises_instruct_on_the_thinking_endpoint():
    orch = SimpleNamespace(
        _capability_map={},
        get_status=lambda: {"endpoints": {"thinking": {
            "status": "healthy", "model": "Qwen/Qwen3.8-27B", "gpu_ids": [0, 1, 2, 3]}}},
    )
    cfg = SimpleNamespace(gpus=SimpleNamespace(total=6, reserved=[]),
                          agents={"thinking": SimpleNamespace(capabilities=["thinking", "instruct", "vision"])})
    resp = build_status_response(_services(orchestrator_service=orch, config=cfg))
    by_cap = {ep.capability: ep for ep in resp.endpoints}
    assert "thinking" in by_cap and "instruct" in by_cap
    assert by_cap["instruct"].model == "Qwen/Qwen3.8-27B"
    assert by_cap["instruct"].healthy == by_cap["thinking"].healthy
    assert list(by_cap["instruct"].gpu_ids) == [0, 1, 2, 3]
    assert "effort=low" in by_cap["instruct"].detail
    assert "vision" not in by_cap  # no operating profile → not a separately advertised capability


def test_workload_offer_carries_profiles():
    from gaius.engine.s2s import declared_workloads

    offers = {o.model: o for o in declared_workloads()}
    thinking = offers["Qwen/Qwen3.8-27B"]
    assert "instruct" in list(thinking.capabilities)
    prof = {p.capability: p for p in thinking.profiles}
    assert prof["instruct"].reasoning_effort == "low" and prof["instruct"].thinking is True
    assert prof["thinking"].reasoning_effort == "xhigh"
