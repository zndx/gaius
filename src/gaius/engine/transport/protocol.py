"""Message protocol for Aeron IPC communication.

This module handles serialization/deserialization of messages between
gaius-engine and clients. It includes OpenTelemetry trace context
propagation for distributed tracing across IPC boundaries.

Initial implementation uses JSON for simplicity. Can be upgraded to
FlatBuffers for zero-copy performance when needed.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Service enumeration (matches gaius.fbs)
class Service(IntEnum):
    ORCHESTRATOR = 0
    SCHEDULER = 1
    EVOLUTION = 2
    GRID = 3
    TDA = 4
    HEALTH = 5
    COGNITION = 6


# Event types (matches gaius.fbs)
class EventType(IntEnum):
    EVOLUTION_PROGRESS = 0
    GRID_UPDATED = 1
    ENDPOINT_CHANGED = 2
    HEALTH_UPDATE = 3
    AGENT_SCORE_CHANGED = 4
    MODEL_LOADED = 5
    MODEL_UNLOADED = 6
    COGNITION_CYCLE = 7
    THOUGHT_GENERATED = 8


@dataclass
class TraceContext:
    """OpenTelemetry W3C trace context for distributed tracing."""

    trace_id: str = ""
    span_id: str = ""
    trace_flags: int = 0

    @classmethod
    def from_current(cls) -> "TraceContext":
        """Create TraceContext from current OpenTelemetry span.

        Extracts trace context from the current span for propagation
        across IPC boundaries.
        """
        try:
            from opentelemetry import trace
            from opentelemetry.propagate import inject

            # Get current span context
            span = trace.get_current_span()
            ctx = span.get_span_context()

            if ctx.is_valid:
                return cls(
                    trace_id=format(ctx.trace_id, "032x"),
                    span_id=format(ctx.span_id, "016x"),
                    trace_flags=ctx.trace_flags,
                )
        except ImportError:
            pass  # OpenTelemetry not installed
        except Exception as e:
            logger.debug(f"Failed to extract trace context: {e}")

        return cls()

    def to_carrier(self) -> dict[str, str]:
        """Convert to W3C traceparent carrier for extraction."""
        if not self.trace_id or not self.span_id:
            return {}

        # W3C Trace Context format: version-traceid-spanid-flags
        traceparent = f"00-{self.trace_id}-{self.span_id}-{self.trace_flags:02x}"
        return {"traceparent": traceparent}

    @classmethod
    def from_carrier(cls, carrier: dict[str, str]) -> "TraceContext":
        """Parse from W3C traceparent carrier."""
        traceparent = carrier.get("traceparent", "")
        if not traceparent:
            return cls()

        try:
            parts = traceparent.split("-")
            if len(parts) >= 4:
                return cls(
                    trace_id=parts[1],
                    span_id=parts[2],
                    trace_flags=int(parts[3], 16),
                )
        except Exception as e:
            logger.debug(f"Failed to parse traceparent: {e}")

        return cls()


@dataclass
class Error:
    """Error response."""

    code: int
    message: str
    details: str = ""


@dataclass
class Request:
    """Request message envelope."""

    id: str
    service: Service
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    trace_context: TraceContext = field(default_factory=TraceContext)

    @classmethod
    def create(
        cls,
        service: Service,
        action: str,
        params: Optional[dict[str, Any]] = None,
        trace_context: Optional[TraceContext] = None,
    ) -> "Request":
        """Create a new request with generated ID and current trace context."""
        return cls(
            id=str(uuid.uuid4()),
            service=service,
            action=action,
            params=params or {},
            trace_context=trace_context or TraceContext.from_current(),
        )


@dataclass
class Response:
    """Response message envelope."""

    id: str
    result: Optional[dict[str, Any]] = None
    error: Optional[Error] = None

    @classmethod
    def success(cls, request_id: str, result: dict[str, Any]) -> "Response":
        """Create a successful response."""
        return cls(id=request_id, result=result)

    @classmethod
    def failure(
        cls, request_id: str, code: int, message: str, details: str = ""
    ) -> "Response":
        """Create an error response."""
        return cls(id=request_id, error=Error(code=code, message=message, details=details))


@dataclass
class Event:
    """Event broadcast message."""

    event_type: EventType
    timestamp_ms: int
    data: dict[str, Any] = field(default_factory=dict)
    trace_context: TraceContext = field(default_factory=TraceContext)

    @classmethod
    def create(
        cls,
        event_type: EventType,
        data: Optional[dict[str, Any]] = None,
        trace_context: Optional[TraceContext] = None,
    ) -> "Event":
        """Create a new event with current timestamp."""
        return cls(
            event_type=event_type,
            timestamp_ms=int(time.time() * 1000),
            data=data or {},
            trace_context=trace_context or TraceContext.from_current(),
        )


@dataclass
class GPUMetrics:
    """GPU health metrics."""

    gpu_id: int
    utilization: float  # 0.0-1.0
    memory_used_gb: float
    memory_total_gb: float
    temperature_c: int
    power_watts: int


@dataclass
class EndpointStatus:
    """vLLM endpoint status."""

    name: str
    model: str
    healthy: bool
    requests_served: int
    avg_latency_ms: float
    gpu_ids: list[int] = field(default_factory=list)


@dataclass
class HealthMetrics:
    """Health broadcast metrics."""

    timestamp_ms: int
    gpus: list[GPUMetrics] = field(default_factory=list)
    endpoints: list[EndpointStatus] = field(default_factory=list)
    queue_depth: int = 0
    evolution_running: bool = False
    evolution_agent: str = ""

    @classmethod
    def create(
        cls,
        gpus: Optional[list[GPUMetrics]] = None,
        endpoints: Optional[list[EndpointStatus]] = None,
        queue_depth: int = 0,
        evolution_running: bool = False,
        evolution_agent: str = "",
    ) -> "HealthMetrics":
        """Create health metrics with current timestamp."""
        return cls(
            timestamp_ms=int(time.time() * 1000),
            gpus=gpus or [],
            endpoints=endpoints or [],
            queue_depth=queue_depth,
            evolution_running=evolution_running,
            evolution_agent=evolution_agent,
        )


# =============================================================================
# Serialization Functions
# =============================================================================


def serialize_request(request: Request) -> bytes:
    """Serialize request to bytes for Aeron transmission."""
    data = {
        "id": request.id,
        "service": int(request.service),
        "action": request.action,
        "params": request.params,
        "trace_context": asdict(request.trace_context),
    }
    return json.dumps(data).encode("utf-8")


def deserialize_request(data: bytes) -> Request:
    """Deserialize request from bytes."""
    obj = json.loads(data.decode("utf-8"))
    return Request(
        id=obj["id"],
        service=Service(obj["service"]),
        action=obj["action"],
        params=obj.get("params", {}),
        trace_context=TraceContext(**obj.get("trace_context", {})),
    )


def serialize_response(response: Response) -> bytes:
    """Serialize response to bytes."""
    data = {
        "id": response.id,
        "result": response.result,
        "error": asdict(response.error) if response.error else None,
    }
    return json.dumps(data).encode("utf-8")


def deserialize_response(data: bytes) -> Response:
    """Deserialize response from bytes."""
    obj = json.loads(data.decode("utf-8"))
    error = None
    if obj.get("error"):
        error = Error(**obj["error"])
    return Response(
        id=obj["id"],
        result=obj.get("result"),
        error=error,
    )


def serialize_event(event: Event) -> bytes:
    """Serialize event to bytes."""
    data = {
        "event_type": int(event.event_type),
        "timestamp_ms": event.timestamp_ms,
        "data": event.data,
        "trace_context": asdict(event.trace_context),
    }
    return json.dumps(data).encode("utf-8")


def deserialize_event(data: bytes) -> Event:
    """Deserialize event from bytes."""
    obj = json.loads(data.decode("utf-8"))
    return Event(
        event_type=EventType(obj["event_type"]),
        timestamp_ms=obj["timestamp_ms"],
        data=obj.get("data", {}),
        trace_context=TraceContext(**obj.get("trace_context", {})),
    )


def serialize_health_metrics(metrics: HealthMetrics) -> bytes:
    """Serialize health metrics to bytes."""
    data = {
        "timestamp_ms": metrics.timestamp_ms,
        "gpus": [asdict(g) for g in metrics.gpus],
        "endpoints": [asdict(e) for e in metrics.endpoints],
        "queue_depth": metrics.queue_depth,
        "evolution_running": metrics.evolution_running,
        "evolution_agent": metrics.evolution_agent,
    }
    return json.dumps(data).encode("utf-8")


def deserialize_health_metrics(data: bytes) -> HealthMetrics:
    """Deserialize health metrics from bytes."""
    obj = json.loads(data.decode("utf-8"))
    return HealthMetrics(
        timestamp_ms=obj["timestamp_ms"],
        gpus=[GPUMetrics(**g) for g in obj.get("gpus", [])],
        endpoints=[EndpointStatus(**e) for e in obj.get("endpoints", [])],
        queue_depth=obj.get("queue_depth", 0),
        evolution_running=obj.get("evolution_running", False),
        evolution_agent=obj.get("evolution_agent", ""),
    )


# =============================================================================
# OpenTelemetry Context Extraction/Injection
# =============================================================================


def extract_trace_context(request: Request):
    """Extract OpenTelemetry context from request for span creation.

    Returns a context that can be used with trace.start_as_current_span().
    """
    try:
        from opentelemetry.propagate import extract

        carrier = request.trace_context.to_carrier()
        if carrier:
            return extract(carrier)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Failed to extract trace context: {e}")

    return None


def start_span_from_request(request: Request, operation_name: Optional[str] = None):
    """Start a new span linked to the request's trace context.

    Args:
        request: Request containing trace context
        operation_name: Span name (defaults to "{service}.{action}")

    Returns:
        Context manager for the span, or None if OpenTelemetry unavailable
    """
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("gaius-engine")
        ctx = extract_trace_context(request)

        span_name = operation_name or f"{request.service.name}.{request.action}"

        span = tracer.start_as_current_span(
            span_name,
            context=ctx,
            attributes={
                "request.id": request.id,
                "service": request.service.name,
                "action": request.action,
            },
        )
        return span
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"Failed to start span: {e}")
        return None
