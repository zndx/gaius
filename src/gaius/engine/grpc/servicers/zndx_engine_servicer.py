"""zndx.engine.v1.Engine — Signals lattice federation face.

Registered *beside* native GaiusService + KServe OIP on :50051. Lattice accept
is Engine/Status (project=gaius, capability=cognition). Native GaiusService
stays the product surface; this stub is the shared service path so a foreign
engine does not get UNIMPLEMENTED against a wire-identical peer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import grpc
from grpc import aio

from ...generated.zndx.engine.v1 import engine_pb2 as zpb
from ...generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

if TYPE_CHECKING:
    from ..server import ServiceRegistry

logger = logging.getLogger(__name__)

PROJECT = "gaius"
CAPABILITY_COGNITION = "cognition"
CAPABILITY_THINKING = "thinking"


ASK_REPLICAS = ("interpretable", "interpretable-b")
ASK_SAE = ("ask-sae",)
_HEALTHY_STATUSES = frozenset({"healthy", "running", "ready"})

_MESSAGE_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})


def parse_messages_json(raw: str) -> list[dict] | None:
    """Validate CompleteRequest.messages_json into an OpenAI messages[].

    Empty returns None, meaning "use the system_prompt/prompt pair". A tool
    loop must send this: flattening assistant tool_calls and tool results into
    one prompt string drops the pairing the chat template renders, and the
    model re-issues calls it has already made.
    """
    import json as _json

    value = (raw or "").strip()
    if not value:
        return None
    try:
        messages = _json.loads(value)
    except _json.JSONDecodeError as e:
        raise ValueError(
            f"messages_json is not valid JSON: {e}\n"
            "  Guru: #GR.00000013.MESSAGES"
        ) from e
    if not isinstance(messages, list) or not messages:
        raise ValueError(
            "messages_json must be a non-empty OpenAI messages[] array; send "
            "an empty string to use prompt/system_prompt.\n"
            "  Guru: #GR.00000013.MESSAGES"
        )
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise ValueError(
                f"messages_json[{i}] must be an object.\n"
                "  Guru: #GR.00000013.MESSAGES"
            )
        role = m.get("role")
        if role not in _MESSAGE_ROLES:
            raise ValueError(
                f"messages_json[{i}].role={role!r} is not one of "
                f"{sorted(_MESSAGE_ROLES)}.\n"
                "  Guru: #GR.00000013.MESSAGES"
            )
        # A tool turn without its id cannot be paired with the call it answers.
        if role == "tool" and not (m.get("tool_call_id") or "").strip():
            raise ValueError(
                f"messages_json[{i}] is a tool turn with no tool_call_id; the "
                "chat template cannot pair it with the call it answers.\n"
                "  Guru: #GR.00000013.MESSAGES"
            )
    return messages


_TOOL_CHOICE_MODES = frozenset({"auto", "required", "none"})


def normalize_tool_choice(raw: str) -> str | dict:
    """Map a CompleteRequest.tool_choice string onto an OpenAI tool_choice.

    Empty means "auto": a capability handed tools[] should be free to call
    them. ``required`` forces a call every turn — the caller owns the loop.
    A JSON object selects one named function and is forwarded verbatim.
    """
    import json as _json

    value = (raw or "").strip()
    if not value:
        return "auto"
    if value in _TOOL_CHOICE_MODES:
        return value
    if value.startswith("{"):
        try:
            named = _json.loads(value)
        except _json.JSONDecodeError:
            named = None
        if isinstance(named, dict):
            return named
    raise ValueError(
        f"tool_choice must be auto | required | none | named-tool JSON, got {value!r}.\n"
        "  Guru: #GR.00000012.TOOLCHOICE"
    )


def resolve_complete_alias(capability: str, services: object | None = None) -> str:
    """Empty / lattice cognition face → standing thinking endpoint.

    Ask prefers light (1.7B) or medium (SAE) if HEALTHY, then thinking.
    STARTING is occupied — skip, do not wait 900s.
    """
    raw = (capability or "").strip()
    if raw in ("", CAPABILITY_COGNITION):
        return CAPABILITY_THINKING
    if raw in ("ask", "ask-sae", "interpretable", "interpretable-b"):
        return pick_ask_cascade(raw, services)
    return raw


def _alias_healthy(services: object | None, alias: str) -> bool:
    orch = getattr(services, "orchestrator_service", None) if services else None
    if orch is None:
        return False
    st = orch.get_endpoint_status(alias)
    if st is None:
        return False
    return str(getattr(st, "status", "") or "").lower() in _HEALTHY_STATUSES


def pick_ask_cascade(requested: str, services: object | None) -> str:
    """Prefer light (1.7B) or medium (SAE) if already HEALTHY.

    If those are down, Complete on standing thinking. Never return a
    STARTING alias so Complete does not start vLLM without a YK
    light/medium admit (OOM / contention).
    """
    if requested == "ask-sae":
        small = list(ASK_SAE) + list(ASK_REPLICAS)
    else:
        small = list(ASK_REPLICAS) + list(ASK_SAE)
    for alias in small:
        if _alias_healthy(services, alias):
            return alias
    if _alias_healthy(services, CAPABILITY_THINKING):
        return CAPABILITY_THINKING
    from ...sentinel_claim import light_wait_available

    if light_wait_available():
        return small[0]
    return CAPABILITY_THINKING


def pick_ask_replica(services: object | None) -> str:
    return pick_ask_cascade("ask", services)


def _alias_to_capability(orchestrator: object) -> dict[str, str]:
    """Invert orchestrator capability_map (capability → aliases) to alias → cap."""
    cap_map = getattr(orchestrator, "_capability_map", {}) or {}
    inverted: dict[str, str] = {}
    for cap, aliases in cap_map.items():
        for alias in aliases:
            inverted[alias] = cap
    return inverted


def _endpoint_healthy(status: str) -> bool:
    return status.lower() in _HEALTHY_STATUSES


def build_status_response(services: "ServiceRegistry") -> zpb.StatusResponse:
    """Project orchestrator + engine identity onto zndx.engine.v1.StatusResponse.

    Always advertises capability=cognition so lattice-ci soft checks pass even
    when no vLLM endpoint is resident yet. Live endpoints are appended.
    """
    endpoints: list[zpb.Endpoint] = [
        zpb.Endpoint(
            capability=CAPABILITY_COGNITION,
            model="gaius-engine",
            healthy=True,
            gpu_ids=[],
            detail="lattice face; native GaiusService + OIP on :50051",
        )
    ]

    total_gpus = 0
    config = getattr(services, "config", None)
    if config is not None:
        gpus = getattr(config, "gpus", None)
        if gpus is not None:
            total_gpus = int(getattr(gpus, "total", 0) or 0)

    orchestrator = getattr(services, "orchestrator_service", None)
    if orchestrator is not None and hasattr(orchestrator, "get_status"):
        status = orchestrator.get_status() or {}
        alias_caps = _alias_to_capability(orchestrator)
        for alias, ep in (status.get("endpoints") or {}).items():
            if not isinstance(ep, dict):
                continue
            cap = alias_caps.get(alias) or ep.get("capability") or alias
            caps: list[str] = []
            if config is not None:
                agent = getattr(config, "agents", {}).get(alias)
                if agent is not None:
                    caps = list(getattr(agent, "capabilities", []) or [])
            detail = f"alias={alias}"
            if caps:
                detail += f" capabilities=[{','.join(caps)}]"
            endpoints.append(
                zpb.Endpoint(
                    capability=str(cap),
                    model=str(ep.get("model") or ""),
                    healthy=_endpoint_healthy(str(ep.get("status") or "")),
                    gpu_ids=list(ep.get("gpu_ids") or []),
                    detail=detail,
                )
            )

    from ...s2s import local_surfaces

    return zpb.StatusResponse(
        project=PROJECT,
        endpoints=endpoints,
        total_gpus=total_gpus,
        surfaces=local_surfaces(),
    )


class GaiusZndxEngineServicer(zpb_grpc.EngineServicer):
    """Shared federation face: Status + Complete + Yield + ServerQuery.

    Remediate is Aegir-owned.
    """

    def __init__(self, services: "ServiceRegistry") -> None:
        self._services = services

    async def Status(
        self,
        request: zpb.StatusRequest,
        context: aio.ServicerContext,
    ) -> zpb.StatusResponse:
        return build_status_response(self._services)

    async def Complete(
        self,
        request: zpb.CompleteRequest,
        context: aio.ServicerContext,
    ) -> zpb.CompleteResponse:
        router = self._services.backend_router
        if router is None:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Backend router not initialized.\n"
                "  Try: /health fix engine\n"
                "  Or:  just restart-clean",
            )

        agent_alias = resolve_complete_alias(request.capability, self._services)
        tz = (getattr(request, "timezone", "") or "").strip()
        if tz or (getattr(request, "clock_json", "") or "").strip():
            logger.info(
                "zndx Complete clock timezone=%s clock_chars=%s",
                tz or "-",
                len(getattr(request, "clock_json", "") or ""),
            )

        import json as _json

        raw_tools = (getattr(request, "tools_json", "") or "").strip()
        if raw_tools and request.json_schema:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "tools_json and json_schema are mutually exclusive: guided_json "
                "disables thinking and suppresses tool_calls.\n"
                "  Guru: #GR.00000010.TOOLSCHEMA",
            )

        extra_body: dict | None = None
        if request.json_schema:
            try:
                schema = _json.loads(request.json_schema)
            except _json.JSONDecodeError as e:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    f"json_schema is not valid JSON: {e}",
                )
            extra_body = {
                "guided_json": schema,
                "chat_template_kwargs": {
                    # guided_json + thinking dumps the inner monologue as
                    # Complete.text and never emits the JSON object.
                    "enable_thinking": False,
                },
            }
        elif raw_tools:
            try:
                tools = _json.loads(raw_tools)
            except _json.JSONDecodeError as e:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    f"tools_json is not valid JSON: {e}\n"
                    "  Guru: #GR.00000011.TOOLSJSON",
                )
            if not isinstance(tools, list) or not tools:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "tools_json must be a non-empty OpenAI tools[] array; send "
                    "an empty string for a text-only Complete.\n"
                    "  Guru: #GR.00000011.TOOLSJSON",
                )
            try:
                choice = normalize_tool_choice(getattr(request, "tool_choice", ""))
            except ValueError as e:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
            extra_body = {"tools": tools, "tool_choice": choice}
            logger.info(
                "zndx Complete tools capability=%s n_tools=%s tool_choice=%s chars=%s",
                agent_alias,
                len(tools),
                choice if isinstance(choice, str) else "named",
                len(raw_tools),
            )

        try:
            messages = parse_messages_json(getattr(request, "messages_json", ""))
        except ValueError as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        if messages is not None:
            logger.info(
                "zndx Complete messages capability=%s n_messages=%s roles=%s",
                agent_alias,
                len(messages),
                ",".join(m.get("role", "?") for m in messages[-4:]),
            )

        try:
            result = await router.complete(
                prompt=request.prompt,
                agent_alias=agent_alias,
                system_prompt=request.system_prompt or None,
                messages=messages,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens or 2048,
                task_type="zndx_complete",
                enable_thinking=not bool(request.json_schema),
                preserve_thinking=not bool(request.json_schema),
                extra_body=extra_body,
            )
        except Exception as e:
            logger.exception("zndx Complete failed capability=%s", agent_alias)
            await context.abort(
                grpc.StatusCode.INTERNAL,
                f"complete[{agent_alias}] failed: {e}\n  Try: /health fix engine",
            )

        # ``error=""`` is still a failure (httpx.ReadTimeout stringifies empty).
        if getattr(result, "error", None) is not None:
            await context.abort(
                grpc.StatusCode.INTERNAL,
                f"complete[{agent_alias}] failed: {result.error}\n"
                "  Try: /health fix engine",
            )

        return zpb.CompleteResponse(
            text=result.content or "",
            model=result.model or "",
            prompt_tokens=int(getattr(result, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(result, "output_tokens", 0) or 0),
            latency_ms=float(getattr(result, "latency_ms", 0.0) or 0.0),
            reasoning_content=getattr(result, "reasoning_content", "") or "",
            finish_reason=getattr(result, "finish_reason", "") or "stop",
        )

    async def Remediate(
        self,
        request: zpb.RemediationRequest,
        context: aio.ServicerContext,
    ) -> zpb.RemediationResponse:
        await context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Remediate is served by Aegir (instruct / ontology adaptation) on :50151.\n"
            "  Gaius lattice capability is cognition; use Complete or native GaiusService.",
        )
        return zpb.RemediationResponse()  # pragma: no cover — abort raises

    async def Yield(
        self,
        request: zpb.YieldRequest,
        context: aio.ServicerContext,
    ) -> zpb.YieldResponse:
        from ...sentinel_yield import yield_workload

        return await yield_workload(self._services, request)

    async def ServerQuery(
        self,
        request: zpb.ServerQueryRequest,
        context: aio.ServicerContext,
    ) -> zpb.ServerQueryResponse:
        from ...s2s import ServerQueryError, local_response

        try:
            from ...s2s import attach_local_note

            resp = local_response(int(request.kind), self._services)
            if int(request.kind) == zpb.SERVER_QUERY_KIND_NOTE:
                attach_local_note(resp, request.note_id)
            if int(request.kind) == zpb.SERVER_QUERY_KIND_SCHEDULES:
                from ...services.summary_schedule import list_schedule_catalog

                db = getattr(self._services, "cognition_service", None)
                pool = getattr(db, "_db_pool", None) if db is not None else None
                try:
                    cards = await list_schedule_catalog(pool)
                except Exception:
                    cards = []
                resp.schedules.extend(
                    zpb.ScheduleHint(
                        id=c.id,
                        cron=c.cron,
                        airflow_dag_id="",
                        source=c.source,
                        enabled=c.enabled,
                    )
                    for c in cards
                )
            return resp
        except ServerQueryError as e:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
            return zpb.ServerQueryResponse()  # pragma: no cover — abort raises

    async def RecordLineage(
        self,
        request: zpb.LineageRequest,
        context: aio.ServicerContext,
    ) -> zpb.LineageResponse:
        """POST OL RunEvent to Signals Atlas. Not a Gaius-local catalog."""
        import json as _json
        import os

        import httpx

        guru = "#LN.00000001.NOATLAS"
        raw = (request.event_json or "").strip()
        if not raw:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{guru} LineageRequest.event_json is empty.",
            )
        try:
            body = _json.loads(raw)
        except _json.JSONDecodeError as e:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{guru} event_json is not JSON: {e}",
            )
        want = (request.event_type or "").strip().upper()
        got = str(body.get("eventType") or "").upper()
        if want and got and want != got:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{guru} event_type={want!r} != event_json.eventType={got!r}",
            )
        url = (
            os.environ.get("SIGNALS_ATLAS_OL_URL")
            or "http://127.0.0.1:21010/api/v1/lineage"
        ).rstrip("/")
        if not url.endswith("/lineage"):
            url = url + "/lineage"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=body)
        except Exception as e:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"{guru} Atlas OpenLineage POST {url} failed: {e}\n"
                "  Signals Atlas :21010 is the lineage SoR.",
            )
        if resp.status_code >= 400:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"{guru} Atlas OpenLineage POST {url} HTTP {resp.status_code}: "
                f"{resp.text[:300]}\n"
                "  Signals Atlas :21010 is the lineage SoR.",
            )
        return zpb.LineageResponse(accepted=True, error="")
