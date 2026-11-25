"""Agenda Ask declares an interactive_session and runs its own tool loop."""

from __future__ import annotations

import pytest

from gaius.engine.backends.backend_router import InferenceResponse
from gaius.engine.sentinel_claim import HEAVY, LIGHT, MEDIUM
from gaius.engine.services.ask_session import (
    GURU_NOCALL,
    GURU_NODECLARE,
    AskSessionError,
    claims_for_alias,
    deployment_for,
    is_ask_face,
    release_held,
    serve,
)


class Scheduler:
    def __init__(self, *, state: str = "running", note: str = "", refuse: bool = False) -> None:
        self.state = state
        self.note = note
        self.refuse = refuse
        self.declared: list[dict] = []
        self.released: list[dict] = []

    async def declare(self, **kwargs):
        self.declared.append(kwargs)
        if self.refuse:
            raise AskSessionError(f"{GURU_NODECLARE} refused")
        return {
            "activity_id": "act-ask-1",
            "state": self.state,
            "note": self.note,
            "claims": [{"leaf": leaf, "gpu": gpu} for leaf, gpu in kwargs["claims"]],
        }

    async def renew(self, **kwargs):
        return None

    async def release(self, **kwargs):
        self.released.append(kwargs)

    async def fetch(self, **kwargs):
        return {"activity_id": kwargs["activity_id"], "state": "running", "note": ""}


class Router:
    def __init__(self, replies: list[tuple[str, str]]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        content, reasoning = self.replies.pop(0)
        return InferenceResponse(
            content=content,
            model="ask",
            backend="vllm",
            reasoning_content=reasoning,
        )


def _serve_kwargs(router, scheduler, **overrides):
    base = dict(
        capability="ask-sae",
        agent_alias="ask-sae",
        prompt="What are today's top market movers?",
        system_prompt="You are the Gaius Ask panel.",
        temperature=0.2,
        max_tokens=256,
        enable_thinking=True,
        reasoning_effort="xhigh",
        extra_body=None,
        plan=None,
        scheduler=scheduler,
    )
    base.update(overrides)
    return base


def test_claims_follow_the_endpoint_signals_allocates():
    assert deployment_for("ask") == ("ask-sae", [(MEDIUM.queue, 2)])
    assert deployment_for("ask-sae")[1] == [(MEDIUM.queue, 2)]
    assert claims_for_alias("interpretable") == [(LIGHT.queue, 1)]
    assert HEAVY.queue not in {leaf for leaf, _ in claims_for_alias("ask-sae")}
    with pytest.raises(AskSessionError, match="NODECLARE"):
        claims_for_alias("thinking")
    assert is_ask_face("ask-sae")
    assert is_ask_face("interpretable")
    assert not is_ask_face("thinking")


@pytest.mark.asyncio
async def test_refused_declare_does_not_complete():
    router = Router([])
    scheduler = Scheduler(refuse=True)
    with pytest.raises(AskSessionError, match="NODECLARE"):
        await serve(router, **_serve_kwargs(router, scheduler))
    assert router.calls == []
    assert scheduler.released == []


@pytest.mark.asyncio
async def test_rejected_queue_floor_does_not_complete():
    router = Router([])
    scheduler = Scheduler(note="queue config REJECTED: medium full")
    with pytest.raises(AskSessionError, match="NODECLARE"):
        await serve(router, **_serve_kwargs(router, scheduler))
    assert router.calls == []
    assert scheduler.released == [{"activity_id": "act-ask-1", "outcome": "aborted"}]


@pytest.mark.asyncio
async def test_tool_call_runs_and_the_answer_is_returned():
    router = Router([
        (
            '<tool_call>{"name":"gaius__fmp_news","arguments":{"kind":"stock","limit":8}}</tool_call>',
            "",
        ),
        ("NVDA led the stock headlines.", ""),
    ])
    ran: list[tuple[str, dict]] = []

    async def execute(name, arguments):
        ran.append((name, arguments))
        return {"ok": True, "items": [{"title": "NVDA rises"}]}

    scheduler = Scheduler()
    result = await serve(
        router,
        execute=execute,
        **_serve_kwargs(router, scheduler),
    )
    assert ran == [("gaius__fmp_news", {"kind": "stock", "limit": 8})]
    assert result.content == "NVDA led the stock headlines."
    assert result.tool_calls == []
    assert "Tool result for gaius__fmp_news" in router.calls[1]["messages"][-1]["content"]
    assert scheduler.declared[0]["claims"] == [(MEDIUM.queue, 2)]
    assert scheduler.released == [{"activity_id": "act-ask-1", "outcome": "completed"}]


@pytest.mark.asyncio
async def test_prose_plan_is_repaired_then_executed():
    router = Router([
        ("Let me call gaius__fmp_news with kind=stock.", "Let me call gaius__fmp_news with kind=stock."),
        (
            '<tool_call>{"name":"gaius__fmp_news","arguments":{"kind":"stock"}}</tool_call>',
            "",
        ),
        ("Latest stock headlines are in.", ""),
    ])

    async def execute(name, arguments):
        return {"ok": True, "items": [{"title": "headline"}]}

    result = await serve(
        router,
        execute=execute,
        **_serve_kwargs(router, Scheduler()),
    )
    assert result.content == "Latest stock headlines are in."
    assert len(router.calls) == 3


@pytest.mark.asyncio
async def test_a_plan_that_never_emits_a_call_fails_closed():
    router = Router([
        ("Let me call gaius__fmp_news with kind=stock.", ""),
        ("I will call gaius__fmp_news again.", ""),
    ])
    scheduler = Scheduler()
    with pytest.raises(AskSessionError, match=GURU_NOCALL.split(".")[-1]):
        await serve(router, execute=_unused, **_serve_kwargs(router, scheduler))
    assert scheduler.released == [{"activity_id": "act-ask-1", "outcome": "no-call"}]


async def _unused(name, arguments):
    raise AssertionError(f"tool ran: {name}")


@pytest.mark.asyncio
async def test_the_named_endpoint_starts_before_complete():
    order: list[str] = []
    router = Router([("ready", "")])

    async def ensure(alias):
        order.append(alias)
        assert router.calls == []

    result = await serve(router, ensure=ensure, **_serve_kwargs(router, Scheduler()))
    assert order == ["ask-sae"]
    assert result.content == "ready"
    assert router.calls


@pytest.mark.asyncio
async def test_a_missing_endpoint_does_not_complete_on_another_model():
    router = Router([("should-not-run", "")])

    async def ensure(alias):
        raise AskSessionError(f"{GURU_NODECLARE} {alias} was not allocated")

    scheduler = Scheduler()
    with pytest.raises(AskSessionError, match="not allocated"):
        await serve(router, ensure=ensure, **_serve_kwargs(router, scheduler))
    assert router.calls == []
    assert scheduler.released[0]["outcome"] == "aborted"


@pytest.mark.asyncio
async def test_a_held_session_reuses_the_activity():
    router = Router([("one", ""), ("two", "")])
    scheduler = Scheduler()
    kwargs = _serve_kwargs(router, scheduler)
    try:
        await serve(router, hold=True, **kwargs)
        await serve(router, hold=True, **kwargs)
        assert len(scheduler.declared) == 1
        assert scheduler.released == []
    finally:
        await release_held("ask-sae", "test")
    assert scheduler.released == [{"activity_id": "act-ask-1", "outcome": "test"}]


@pytest.mark.asyncio
async def test_agenda_write_declares_the_session_and_skips_the_tool_loop():
    router = Router([(":::gaius-handoff\n{}\n:::", "")])
    scheduler = Scheduler()

    async def execute(name, arguments):
        raise AssertionError(name)

    result = await serve(
        router,
        execute=execute,
        **_serve_kwargs(
            router,
            scheduler,
            system_prompt='{"to":"thinking","task":"agenda.write"}',
        ),
    )
    assert "gaius-handoff" in result.content
    assert router.calls[0]["messages"] is None
    assert scheduler.released[0]["outcome"] == "completed"
