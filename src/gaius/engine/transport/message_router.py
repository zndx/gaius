"""Message router for dispatching IPC requests to services.

Routes incoming Aeron IPC requests to the appropriate service handlers
based on the service type in the request envelope.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

# OpenTelemetry is a required dependency (defensive import for robustness)
try:
    from opentelemetry import trace as otel_trace
    OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None  # type: ignore[assignment] - defensive fallback if otel import fails
    OTEL_AVAILABLE = False

from .protocol import (
    EventType,
    Request,
    Response,
    Service,
    TraceContext,
    deserialize_request,
    serialize_event,
    serialize_response,
    start_span_from_request,
)

logger = logging.getLogger(__name__)

# Type alias for service handlers
ServiceHandler = Callable[[str, dict[str, Any], Optional[TraceContext]], Any]


@dataclass
class RouteMetrics:
    """Metrics for a service route."""

    service: Service
    total_requests: int = 0
    total_errors: int = 0
    total_latency_ms: int = 0

    @property
    def avg_latency_ms(self) -> float:
        """Average latency."""
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests


class MessageRouter:
    """Routes IPC messages to service handlers.

    Dispatches requests based on service type and action, tracks metrics,
    and propagates OpenTelemetry trace context.
    """

    def __init__(self):
        """Initialize message router."""
        # Service handlers: {Service: {action: handler}}
        self._handlers: dict[Service, dict[str, ServiceHandler]] = {}

        # Default handlers for services
        for service in Service:
            self._handlers[service] = {}

        # Metrics per service
        self._metrics: dict[Service, RouteMetrics] = {
            service: RouteMetrics(service=service) for service in Service
        }

        # Tracer for distributed tracing (optional)
        self._tracer = otel_trace.get_tracer("gaius-engine.router") if OTEL_AVAILABLE and otel_trace else None

        logger.info("MessageRouter initialized")

    def register(
        self,
        service: Service,
        action: str,
        handler: ServiceHandler,
    ) -> None:
        """Register a handler for a service action.

        Args:
            service: Service type
            action: Action name
            handler: Async handler function(action, params, trace_ctx) -> result
        """
        self._handlers[service][action] = handler
        logger.debug(f"Registered handler: {service.name}.{action}")

    def register_service(
        self,
        service: Service,
        handler: ServiceHandler,
    ) -> None:
        """Register a catch-all handler for a service.

        Args:
            service: Service type
            handler: Handler for all actions on this service
        """
        self._handlers[service]["*"] = handler
        logger.debug(f"Registered catch-all handler for {service.name}")

    async def route(self, data: bytes) -> bytes:
        """Route a serialized request to the appropriate handler.

        Args:
            data: Serialized request bytes

        Returns:
            Serialized response bytes
        """
        start_time = datetime.now()
        request = None

        try:
            # Deserialize request
            request = deserialize_request(data)

            # Route to handler (with optional tracing)
            if OTEL_AVAILABLE and self._tracer:
                with start_span_from_request(request) as span:
                    result = await self._dispatch(request)
                    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    span.set_attribute("response.success", True)
                    span.set_attribute("response.latency_ms", latency_ms)
            else:
                result = await self._dispatch(request)
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Build response
            response = Response(
                id=request.id,
                result=result,
            )

            # Record metrics
            self._record_metrics(request.service, latency_ms, error=False)

            return serialize_response(response)

        except Exception as e:
            logger.error(f"Route error: {e}")

            # Build error response
            response = Response.failure(
                request_id=request.id if request else "unknown",
                code=-1,
                message=str(e),
            )

            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            if request:
                self._record_metrics(request.service, latency_ms, error=True)

            return serialize_response(response)

    async def _dispatch(self, request: Request) -> Any:
        """Dispatch request to handler.

        Args:
            request: Parsed request

        Returns:
            Handler result
        """
        service = request.service
        action = request.action
        params = request.params or {}

        # Look for specific handler
        handlers = self._handlers.get(service, {})
        handler = handlers.get(action)

        # Fall back to catch-all
        if handler is None:
            handler = handlers.get("*")

        if handler is None:
            raise ValueError(f"No handler for {service.name}.{action}")

        # Call handler
        if asyncio.iscoroutinefunction(handler):
            result = await handler(action, params, request.trace_context)
        else:
            result = handler(action, params, request.trace_context)

        return result

    def _record_metrics(
        self, service: Service, latency_ms: int, error: bool
    ) -> None:
        """Record metrics for a request."""
        metrics = self._metrics[service]
        metrics.total_requests += 1
        metrics.total_latency_ms += latency_ms
        if error:
            metrics.total_errors += 1

    def get_metrics(self) -> dict[str, dict[str, Any]]:
        """Get routing metrics."""
        return {
            service.name: {
                "total_requests": m.total_requests,
                "total_errors": m.total_errors,
                "avg_latency_ms": m.avg_latency_ms,
                "error_rate": m.total_errors / max(1, m.total_requests),
            }
            for service, m in self._metrics.items()
        }


def create_service_handlers(
    orchestrator_service,
    scheduler_service,
    evolution_service=None,
    health_service=None,  # HealthService instance for comprehensive monitoring
) -> dict[Service, dict[str, ServiceHandler]]:
    """Create standard service handlers.

    Args:
        orchestrator_service: OrchestratorService instance
        scheduler_service: SchedulerService instance
        evolution_service: Optional EvolutionService
        health_service: Optional HealthService

    Returns:
        Dict mapping services to action handlers
    """
    handlers: dict[Service, dict[str, ServiceHandler]] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Orchestrator Service
    # ─────────────────────────────────────────────────────────────────────────

    async def orchestrator_handler(
        action: str, params: dict, trace_ctx: Optional[TraceContext]
    ) -> Any:
        if action == "start":
            endpoint = params.get("endpoint", "reasoning")
            status = await orchestrator_service.start_endpoint(endpoint)
            return {
                "agent_alias": status.agent_alias,
                "port": status.port,
                "gpu_ids": status.gpu_ids,
                "status": status.status,
            }

        elif action == "stop":
            endpoint = params.get("endpoint")
            success = await orchestrator_service.stop_endpoint(endpoint)
            return {"success": success}

        elif action == "restart":
            endpoint = params.get("endpoint")
            status = await orchestrator_service.restart_endpoint(endpoint)
            return {
                "agent_alias": status.agent_alias,
                "status": status.status,
            }

        elif action == "clean_start":
            endpoints = params.get("endpoints", ["reasoning"])
            result = await orchestrator_service.clean_start(endpoints)
            return result

        elif action == "status":
            return orchestrator_service.get_status()

        elif action == "logs":
            endpoint = params.get("endpoint")
            lines = params.get("lines", 50)
            return {"logs": orchestrator_service.get_endpoint_logs(endpoint, lines)}

        elif action == "gpu_health":
            return {"utilization": orchestrator_service.get_gpu_utilization()}

        else:
            raise ValueError(f"Unknown orchestrator action: {action}")

    handlers[Service.ORCHESTRATOR] = {"*": orchestrator_handler}

    # ─────────────────────────────────────────────────────────────────────────
    # Scheduler Service
    # ─────────────────────────────────────────────────────────────────────────

    async def scheduler_handler(
        action: str, params: dict, trace_ctx: Optional[TraceContext]
    ) -> Any:
        if action == "complete":
            response = await scheduler_service.complete(
                prompt=params["prompt"],
                agent_alias=params.get("agent", "instruct"),
                system_prompt=params.get("system_prompt"),
                temperature=params.get("temperature", 0.7),
                max_tokens=params.get("max_tokens", 2048),
                technique=params.get("technique"),
            )
            return {
                "content": response.content,
                "model": response.model,
                "backend": response.backend,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
                "error": response.error,
            }

        elif action == "evaluate":
            response = await scheduler_service.tiered_evaluate(
                prompt=params["prompt"],
                force_xai=params.get("force_xai", False),
            )
            return {
                "content": response.content,
                "model": response.model,
                "error": response.error,
            }

        elif action == "status":
            return scheduler_service.get_status()

        elif action == "metrics":
            return scheduler_service.get_all_metrics()

        elif action == "budget":
            return scheduler_service.get_xai_budget()

        elif action == "job_status":
            job_id = params.get("job_id")
            return scheduler_service.get_job_status(job_id)

        else:
            raise ValueError(f"Unknown scheduler action: {action}")

    handlers[Service.SCHEDULER] = {"*": scheduler_handler}

    # ─────────────────────────────────────────────────────────────────────────
    # Evolution Service (if provided)
    # BDD: Start/stop evolution daemon, manual trigger, budget management
    # ─────────────────────────────────────────────────────────────────────────

    if evolution_service:
        async def evolution_handler(
            action: str, params: dict, trace_ctx: Optional[TraceContext]
        ) -> Any:
            if action == "start":
                # BDD: "Start evolution daemon with '/evolve start'"
                await evolution_service.start()
                return {"status": "started"}

            elif action == "stop":
                # BDD: "Stop evolution daemon with '/evolve stop'"
                await evolution_service.stop()
                return {"status": "stopped"}

            elif action == "trigger":
                # BDD: "Manual evolution trigger with '/evolve trigger'"
                agent_id = params.get("agent_id")
                result = await evolution_service.trigger(agent_id)
                return result

            elif action == "status":
                # BDD: "Evolution panel shows daemon status"
                return evolution_service.get_status()

            elif action == "recent_cycles":
                # BDD: "Evolution panel shows recent cycles"
                limit = params.get("limit", 10)
                return {"cycles": evolution_service.get_recent_cycles(limit)}

            elif action == "agent_scores":
                # BDD: "Evolution panel shows agent scores"
                return {"scores": evolution_service.get_agent_scores()}

            else:
                raise ValueError(f"Unknown evolution action: {action}")

        handlers[Service.EVOLUTION] = {"*": evolution_handler}

    # ─────────────────────────────────────────────────────────────────────────
    # Health Service
    # ─────────────────────────────────────────────────────────────────────────

    async def health_handler(
        action: str, params: dict, trace_ctx: Optional[TraceContext]
    ) -> Any:
        if action == "check":
            # Use HealthService if available for comprehensive monitoring
            if health_service:
                return health_service.get_health()
            else:
                return {
                    "orchestrator": orchestrator_service.get_status(),
                    "scheduler": scheduler_service.get_status(),
                    "gpu_utilization": orchestrator_service.get_gpu_utilization(),
                }

        elif action == "gpu":
            if health_service:
                return {"utilization": health_service.get_gpu_utilization()}
            else:
                return {"utilization": orchestrator_service.get_gpu_utilization()}

        elif action == "gpu_detailed":
            # Detailed GPU health (temperature, VRAM, etc.)
            if health_service:
                return {"gpus": health_service.get_gpu_health()}
            else:
                return {"gpus": {}}

        elif action == "endpoints":
            # Endpoint health status
            if health_service:
                return {"endpoints": health_service.get_endpoint_health()}
            else:
                return {"endpoints": orchestrator_service.get_all_endpoint_status()}

        elif action == "status":
            # Health service status
            if health_service:
                return health_service.get_status()
            else:
                return {"running": True, "gpu_count": 0, "endpoint_count": 0}

        else:
            raise ValueError(f"Unknown health action: {action}")

    handlers[Service.HEALTH] = {"*": health_handler}

    return handlers
