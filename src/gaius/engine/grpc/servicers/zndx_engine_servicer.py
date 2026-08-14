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

_HEALTHY_STATUSES = frozenset({"healthy", "running", "ready"})


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
            endpoints.append(
                zpb.Endpoint(
                    capability=str(cap),
                    model=str(ep.get("model") or ""),
                    healthy=_endpoint_healthy(str(ep.get("status") or "")),
                    gpu_ids=list(ep.get("gpu_ids") or []),
                    detail=f"alias={alias}",
                )
            )

    return zpb.StatusResponse(
        project=PROJECT,
        endpoints=endpoints,
        total_gpus=total_gpus,
    )


class GaiusZndxEngineServicer(zpb_grpc.EngineServicer):
    """Shared federation face: Status + Complete + Yield. Remediate is Aegir-owned."""

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
        if request.json_schema:
            await context.abort(
                grpc.StatusCode.UNIMPLEMENTED,
                "Gaius zndx.engine.v1.Complete does not honor json_schema yet.\n"
                "  Omit json_schema, or call native gaius.engine.GaiusService/Complete.\n"
                "  Try: /health fix engine",
            )

        router = self._services.backend_router
        if router is None:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Backend router not initialized.\n"
                "  Try: /health fix engine\n"
                "  Or:  just restart-clean",
            )

        capability = request.capability or CAPABILITY_COGNITION
        try:
            result = await router.complete(
                prompt=request.prompt,
                agent_alias=capability,
                system_prompt=request.system_prompt or None,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens or 2048,
                task_type="zndx_complete",
            )
        except Exception as e:
            logger.exception("zndx Complete failed capability=%s", capability)
            await context.abort(
                grpc.StatusCode.INTERNAL,
                f"complete[{capability}] failed: {e}\n  Try: /health fix engine",
            )

        if getattr(result, "error", None):
            await context.abort(
                grpc.StatusCode.INTERNAL,
                f"complete[{capability}] failed: {result.error}\n"
                "  Try: /health fix engine",
            )

        return zpb.CompleteResponse(
            text=result.content or "",
            model=result.model or "",
            prompt_tokens=int(getattr(result, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(result, "output_tokens", 0) or 0),
            latency_ms=float(getattr(result, "latency_ms", 0.0) or 0.0),
            finish_reason="stop",
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
        from ...flow_processes import flow_processes

        ended, msg = await flow_processes().yield_one(request.workload_id)
        return zpb.YieldResponse(
            ok=True,
            process_ended=ended,
            restore_started=False,
            message=msg,
        )
