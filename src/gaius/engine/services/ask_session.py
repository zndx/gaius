"""Agenda Ask as a Signals interactive session.

The Ask panel is a local process. It speaks only to this engine. This
engine declares kind ``interactive_session`` to the Signals engine, and
Signals materialises ``coord_interactive_session`` so Airflow observes the
lease and the claims are the YuniKorn floor while the activity is RUNNING.

A turn that cannot be declared does not complete. The panel used to attach
the terminal tool card and then strip ``tools[]``, so ask-sae narrated
``gaius__fmp_news`` inside its think trace and nothing ran. The tool loop
lives here: markup is parsed, FMP and AskPresent run, and the panel receives
the answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from gaius.engine.backends.vllm_controller import (
    parse_qwen_tool_call_markup,
    qwen_tool_call_markup,
)
from gaius.engine.sentinel_claim import COMPUTE, LIGHT, MEDIUM
from gaius.engine.services.coordination import (
    GURU_RENEWFAIL,
    PROJECT,
    activity_to_dict,
    now_ns,
    release_rpc,
    signals_target,
)

log = logging.getLogger(__name__)

KIND = "interactive_session"
GURU_NODECLARE = "#CO.00000011.NODECLARE"
GURU_NOCALL = "#AS.00000001.NOCALL"

ASK_FACES = frozenset({"ask", "ask-sae", "interpretable", "interpretable-b"})
_MEDIUM = frozenset({"ask-sae", "ask_sae", "ask-medium"})
_LIGHT = frozenset({"ask-agent", "ask_agent", "ask-light", "interpretable", "interpretable-b"})

HORIZON_S = 3600
HEARTBEAT_S = 60
RUNNING_WAIT_S = 45.0
TOOL_ROUNDS = 4
RESULT_CLIP = 4000

# Names the engine will execute. Anything else is an error result, not a guess.
_FMP = frozenset({"fmp_search", "fmp_quote", "fmp_profile", "fmp_news", "fmp_employees"})

CONTRACT = (
    "This turn is an interactive_session. The engine executes tool calls. "
    "When you need data, emit exactly one block and nothing else:\n"
    "<tool_call>\n"
    '{"name":"gaius__fmp_news","arguments":{"kind":"stock","limit":8}}\n'
    "</tool_call>\n"
    "Tools: gaius__fmp_news (kind=stock|general, optional symbol), "
    "gaius__fmp_search (query), gaius__fmp_quote (symbol), "
    "gaius__fmp_employees (symbol), gaius__fmp_profile (symbol), "
    "gaius__ask_present (kind=ohlc|table|links|markdown, symbol). "
    "There is no top-movers feed. For movers, call gaius__fmp_news with "
    "kind=stock and report only headlines the tool returned. "
    "Do not describe a call. Do not invent prices, tickers, or headlines. "
    "After a tool result, answer in markdown."
)

_PLAN = re.compile(
    r"\b(?:let me call|i(?:'ll| will) call|going to call|call gaius__)\b",
    re.IGNORECASE,
)
_THINK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


class AskSessionError(RuntimeError):
    """The interactive session did not reach a runnable activity or a real call."""


def is_ask_face(capability: str) -> bool:
    return (capability or "").strip() in ASK_FACES


def claims_for_alias(alias: str) -> list[tuple[str, int]]:
    """YK leaves this turn occupies while its activity is RUNNING.

    The resolved endpoint decides the leaf. Standing thinking is already
    admitted on heavy; this session must not set that floor. Medium is the
    ask-sae pair. Light is the 1.7B ask replica. A thinking fallback records
    compute at gpu 0 so Signals can see the session without taking a GPU.
    The live YuniKorn config does not know ``root.external.rate-metered``,
    and claiming it is ``#CO.00000009.OVERCLAIM``.
    """
    name = (alias or "").strip()
    if name in _MEDIUM:
        return [(MEDIUM.queue, MEDIUM.gpu_tokens)]
    if name in _LIGHT:
        return [(LIGHT.queue, LIGHT.gpu_tokens)]
    return [(COMPUTE.queue, 0)]


def wants_tool_loop(system_prompt: str, tools_json: str, messages_json: str) -> bool:
    """Panel turns run the loop here. A caller that brought tools or messages
    owns the harness. An agenda write emits a fence, not an FMP call."""
    if (tools_json or "").strip() or (messages_json or "").strip():
        return False
    blob = system_prompt or ""
    if "agenda.write" in blob or "You are filling one Agenda write" in blob:
        return False
    return True


def looks_like_unrun_plan(text: str) -> bool:
    return bool(_PLAN.search(text or ""))


def _strip_think(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def visible_answer(content: str, reasoning: str) -> str:
    """User text. A bare plan is not an answer; the loop raises instead."""
    body, _ = parse_qwen_tool_call_markup(_strip_think(content))
    body = body.strip()
    if body and not looks_like_unrun_plan(body):
        return body
    thought = _strip_think(reasoning).strip()
    if thought and not looks_like_unrun_plan(thought) and not body:
        return thought
    return body


def _calls_from(result: Any) -> list[dict[str, Any]]:
    native = getattr(result, "tool_calls", None) or []
    found: list[dict[str, Any]] = []
    if isinstance(native, list) and native and "arguments_json" in (native[0] or {}):
        found = [c for c in native if isinstance(c, dict) and c.get("name")]
    else:
        from gaius.engine.backends.vllm_controller import structured_tool_calls

        found = structured_tool_calls(native, getattr(result, "content", "") or "")
    if found:
        return found
    _, parsed = parse_qwen_tool_call_markup(getattr(result, "reasoning_content", "") or "")
    out = []
    for call in parsed:
        name = str(call.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "id": "",
            "name": name,
            "arguments_json": json.dumps(call.get("arguments") or {}, separators=(",", ":")),
        })
    return out


def _args(call: dict[str, Any]) -> dict[str, Any]:
    raw = call.get("arguments_json", call.get("arguments", {}))
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _clip(payload: Any) -> str:
    text = json.dumps(payload, default=str)
    if len(text) <= RESULT_CLIP:
        return text
    return text[:RESULT_CLIP] + "…(truncated)"


def _fence(artifact: dict[str, Any]) -> str:
    return ":::gaius-artifact\n" + json.dumps(artifact, separators=(",", ":")) + "\n:::"


class _GrpcScheduler:
    """Signals Scheduler RPCs. The only process that dials Signals for Ask."""

    def __init__(self, target: str | None = None) -> None:
        self.target = target or signals_target()

    async def declare(
        self,
        *,
        owner: str,
        request_id: str,
        claims: list[tuple[str, int]],
        reason: str,
        horizon_ns: int,
    ) -> dict[str, Any]:
        from grpc import aio
        from grpc import RpcError

        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

        req = spb.DeclareActivityRequest(
            peer=PROJECT,
            request_id=request_id,
            kind=KIND,
            owner=owner,
            horizon_ns=horizon_ns,
            reason=reason,
        )
        for leaf, gpu in claims:
            req.claims.add(leaf=leaf, gpu=int(gpu))
        try:
            async with aio.insecure_channel(self.target) as channel:
                stub = spb_grpc.SchedulerStub(channel)
                resp = await stub.DeclareActivity(req, timeout=15.0)
        except RpcError as e:
            raise AskSessionError(
                f"{GURU_NODECLARE} DeclareActivity for the Ask session failed at {self.target}: {e}\n"
                "  Agenda Ask completes only inside an interactive_session.\n"
                "  Signals materialises coord_interactive_session; Airflow observes the lease;\n"
                "  the claims are the YuniKorn floor while RUNNING.\n"
                "  Try: /activities"
            ) from e
        if not resp.accepted or not str(resp.activity.activity_id or ""):
            raise AskSessionError(
                f"{GURU_NODECLARE} Signals refused the Ask interactive_session: "
                f"{resp.error or 'no activity id'}\n"
                "  Try: /activities"
            )
        return activity_to_dict(resp.activity)

    async def renew(self, *, activity_id: str, horizon_ns: int) -> None:
        from gaius.engine.services.coordination import _scheduler_call

        resp = await _scheduler_call(
            self.target,
            "RenewActivity",
            peer=PROJECT,
            activity_id=activity_id,
            horizon_ns=horizon_ns,
        )
        if not resp.accepted:
            raise RuntimeError(resp.error or "renew refused")

    async def release(self, *, activity_id: str, outcome: str) -> None:
        await release_rpc(self.target, activity_id, outcome)

    async def fetch(self, *, activity_id: str) -> dict[str, Any] | None:
        from gaius.engine.services.coordination import _scheduler_call

        resp = await _scheduler_call(
            self.target,
            "ListActivities",
            peer=PROJECT,
            kind=KIND,
            active_only=True,
            limit=20,
        )
        for activity in resp.activities:
            view = activity_to_dict(activity)
            if view["activity_id"] == activity_id:
                return view
        return None


def _reject_note(view: dict[str, Any]) -> None:
    note = str(view.get("note") or "")
    if "REJECTED" in note:
        raise AskSessionError(
            f"{GURU_NODECLARE} Signals left the Ask activity in force but refused its "
            f"YuniKorn claims: {note}\n"
            "  The turn does not complete on a rejected queue floor.\n"
            "  Try: /activities"
        )


async def _wait_running(scheduler: Any, view: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + RUNNING_WAIT_S
    current = view
    while True:
        if str(current.get("state") or "") == "running":
            _reject_note(current)
            return current
        if time.monotonic() >= deadline:
            raise AskSessionError(
                f"{GURU_NODECLARE} Ask activity {current.get('activity_id') or '?'} "
                f"did not reach RUNNING within {int(RUNNING_WAIT_S)}s "
                f"(state={current.get('state') or 'absent'}).\n"
                "  Airflow's hold sensor is the session. Completing before RUNNING\n"
                "  skips the YuniKorn floor.\n"
                "  Try: /activities"
            )
        await asyncio.sleep(2)
        try:
            fetched = await scheduler.fetch(activity_id=str(current.get("activity_id") or ""))
        except Exception as e:  # noqa: BLE001 — keep waiting until the deadline
            log.warning("%s list Ask activity failed: %s", GURU_NODECLARE, e)
            fetched = None
        if fetched is not None:
            current = fetched


async def _beat(scheduler: Any, activity_id: str, stop: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_S)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await scheduler.renew(
                activity_id=activity_id,
                horizon_ns=now_ns() + HORIZON_S * 1_000_000_000,
            )
        except Exception as e:  # noqa: BLE001 — TTL bounds a missed heartbeat
            log.warning("%s Ask activity %s: %s", GURU_RENEWFAIL, activity_id, e)


async def _execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    short = (name or "").strip()
    if short.startswith("gaius__"):
        short = short[len("gaius__") :]
    if short == "ask_present":
        from gaius.engine.services.ask_present import AskPresentError, build_artifact

        payload = arguments.get("payload_json") or arguments.get("payload") or ""
        if not payload:
            for key in ("rows", "bars", "links", "body"):
                if key in arguments:
                    val = arguments[key]
                    payload = val if isinstance(val, str) else json.dumps(val)
                    break
        try:
            artifact = await build_artifact(
                kind=str(arguments.get("kind") or "ohlc"),
                symbol=str(arguments.get("symbol") or ""),
                title=str(arguments.get("title") or ""),
                from_date=str(arguments.get("from_date") or ""),
                to_date=str(arguments.get("to_date") or ""),
                payload_json=str(payload or ""),
            )
        except AskPresentError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "artifact": artifact}
    tool = short if short in _FMP else f"fmp_{short}" if f"fmp_{short}" in _FMP else ""
    if not tool:
        return {
            "ok": False,
            "error": (
                f"Ask session does not run {name!r}. "
                f"Tools: {', '.join(sorted(_FMP))}, ask_present."
            ),
            "items": [],
        }
    from gaius.engine.services.fmp_tools import call_tool

    return await call_tool(tool, arguments)


def _assistant_turn(result: Any, calls: list[dict[str, Any]]) -> str:
    content = getattr(result, "content", "") or ""
    if "<tool_call>" in content:
        return content
    shaped = []
    for call in calls:
        args = _args(call)
        shaped.append({
            "id": call.get("id") or "",
            "function": {"name": call.get("name") or "", "arguments": json.dumps(args)},
        })
    return qwen_tool_call_markup(shaped)


async def _tool_loop(router: Any, *, agent_alias: str, prompt: str, system_prompt: str,
                      temperature: float, max_tokens: int, enable_thinking: bool,
                      reasoning_effort: str, extra_body: dict | None, plan: Any,
                      execute) -> Any:
    from gaius.engine.backends.backend_router import InferenceResponse

    system = (system_prompt or "").rstrip()
    system = f"{system}\n\n{CONTRACT}" if system else CONTRACT
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    artifacts: list[dict[str, Any]] = []
    last = None
    repaired = False
    for round_i in range(TOOL_ROUNDS + 1):
        last = await router.complete(
            prompt="",
            agent_alias=agent_alias,
            system_prompt=None,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            plan=plan,
            task_type="zndx_complete",
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            preserve_thinking=enable_thinking,
            extra_body=extra_body,
        )
        if getattr(last, "error", None):
            return last
        calls = _calls_from(last)
        if not calls:
            text = f"{getattr(last, 'content', '') or ''}\n{getattr(last, 'reasoning_content', '') or ''}"
            if looks_like_unrun_plan(text) and not repaired and round_i < TOOL_ROUNDS:
                repaired = True
                messages.append({"role": "assistant", "content": _strip_think(getattr(last, "content", "") or "") or "(plan)"})
                messages.append({
                    "role": "user",
                    "content": (
                        "That turn described a tool call and did not emit one. "
                        "Emit exactly one <tool_call> block. Do not describe it."
                    ),
                })
                continue
            if looks_like_unrun_plan(text):
                raise AskSessionError(
                    f"{GURU_NOCALL} Ask described a tool call and did not emit one.\n"
                    "  The engine runs <tool_call> blocks. A prose plan is not a call.\n"
                    "  Try the question again."
                )
            answer = visible_answer(getattr(last, "content", "") or "", getattr(last, "reasoning_content", "") or "")
            for artifact in artifacts:
                fence = _fence(artifact)
                if fence not in answer:
                    answer = f"{answer}\n\n{fence}".strip()
            last.content = answer
            last.tool_calls = []
            return last
        if round_i >= TOOL_ROUNDS:
            raise AskSessionError(
                f"{GURU_NOCALL} Ask was still calling tools after {TOOL_ROUNDS} rounds.\n"
                "  Try a narrower question."
            )
        messages.append({"role": "assistant", "content": _assistant_turn(last, calls)})
        for call in calls[:3]:
            name = str(call.get("name") or "")
            result = await execute(name, _args(call))
            if isinstance(result, dict) and result.get("artifact"):
                artifacts.append(result["artifact"])
            log.info("ask session tool %s ok=%s", name, bool(isinstance(result, dict) and result.get("ok", True)))
            messages.append({
                "role": "user",
                "content": f"Tool result for {name}:\n{_clip(result)}",
            })
    if last is None:
        return InferenceResponse(content="", model="", backend="vllm", error=f"{GURU_NOCALL} no completion")
    return last


async def serve(
    router: Any,
    *,
    capability: str,
    agent_alias: str,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    enable_thinking: bool,
    reasoning_effort: str,
    extra_body: dict | None,
    plan: Any,
    tools_json: str = "",
    messages_json: str = "",
    messages: list[dict[str, Any]] | None = None,
    scheduler: Any | None = None,
    execute=None,
) -> Any:
    """Declare the session, complete, release. Fail closed if Signals refuses."""
    if not is_ask_face(capability):
        raise AskSessionError(
            f"{GURU_NODECLARE} {capability!r} is not an Ask face.\n  Try: /activities"
        )
    from gaius.engine.queue_share import mint_uuid7

    sched = scheduler or _GrpcScheduler()
    claims = claims_for_alias(agent_alias)
    owner = f"ask:{mint_uuid7()}"
    reason = (
        f"agenda ask on {agent_alias} ("
        + ", ".join(f"{leaf} gpu={gpu}" for leaf, gpu in claims)
        + "). Signals observes the lease; claims are the YuniKorn floor while RUNNING."
    )
    view = await sched.declare(
        owner=owner,
        request_id=mint_uuid7(),
        claims=claims,
        reason=reason,
        horizon_ns=now_ns() + HORIZON_S * 1_000_000_000,
    )
    activity_id = str(view.get("activity_id") or "")
    stop = asyncio.Event()
    beater: asyncio.Task | None = None
    outcome = "aborted"
    try:
        view = await _wait_running(sched, view)
        activity_id = str(view["activity_id"])
        outcome = "running"
        log.info(
            "ask session %s RUNNING owner=%s alias=%s claims=%s",
            activity_id, owner, agent_alias, claims,
        )
        beater = asyncio.create_task(
            _beat(sched, activity_id, stop), name=f"ask-activity-{activity_id}"
        )
        if wants_tool_loop(system_prompt, tools_json, messages_json):
            result = await _tool_loop(
                router,
                agent_alias=agent_alias,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort,
                extra_body=extra_body,
                plan=plan,
                execute=execute or _execute,
            )
        else:
            result = await router.complete(
                prompt=prompt,
                agent_alias=agent_alias,
                system_prompt=system_prompt or None,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                plan=plan,
                task_type="zndx_complete",
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort,
                preserve_thinking=enable_thinking,
                extra_body=extra_body,
            )
        outcome = "completed"
        return result
    except AskSessionError:
        if outcome == "running":
            outcome = "no-call"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        stop.set()
        if beater is not None:
            beater.cancel()
            try:
                await beater
            except asyncio.CancelledError:
                pass
        if activity_id:
            try:
                await sched.release(activity_id=activity_id, outcome=outcome)
            except Exception as e:  # noqa: BLE001 — lease TTL expires a missed release
                log.warning("%s Ask release %s: %s", GURU_RENEWFAIL, activity_id, e)
