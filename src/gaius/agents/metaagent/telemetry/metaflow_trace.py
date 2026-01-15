"""Metaflow tracing integration for MetaAgent.

Provides TracedFlow base class and @traced_step decorator for automatic
OTel instrumentation of Metaflow pipelines.

Usage:
    from gaius.agents.metaagent.telemetry import TracedFlow, traced_step

    class ArxivFetchFlow(TracedFlow):
        @traced_step
        @step
        def fetch_pdf(self):
            # Span created with metaflow.step_name="fetch_pdf"
            # correlation_id available for NiFi linking
            self.emit_event("pdf.extraction.started", {"arxiv_id": self.arxiv_id})
            ...
            self.emit_event("pdf.extraction.completed", {"pages": page_count})
            self.next(self.extract_text)

        @traced_step(heartbeat_interval=10.0)
        @step
        def long_running_step(self):
            # Heartbeats emitted every 10s with meaningful metrics
            pass
"""

from __future__ import annotations

import functools
import logging
import threading
import time
import uuid
from typing import Any, Callable, TypeVar, cast, overload

from gaius.core.telemetry import get_tracer

from .attributes import EventNames, GaiusAttrs, MetaflowAttrs, NiFiAttrs, HeartbeatAttrs

logger = logging.getLogger(__name__)

# Type variable for preserving function signatures
F = TypeVar("F", bound=Callable[..., Any])


def _emit_sync_heartbeat(
    span: Any,
    step_name: str,
    flow_name: str,
    start_time: float,
    heartbeat_count: int,
    baseline: Any | None = None,
) -> dict[str, Any]:
    """Emit a synchronous heartbeat event with meaningful metrics.

    Returns updated state dict for the next heartbeat.
    """
    elapsed = time.time() - start_time
    elapsed_ms = elapsed * 1000

    # Build attributes with meaningful observability value
    attrs: dict[str, Any] = {
        HeartbeatAttrs.SEQUENCE: heartbeat_count,
        HeartbeatAttrs.OPERATION: f"metaflow.{flow_name}.{step_name}",
        HeartbeatAttrs.ELAPSED_S: round(elapsed, 3),
        MetaflowAttrs.STEP_NAME: step_name,
        MetaflowAttrs.FLOW_NAME: flow_name,
    }

    # Include baseline statistics for observability value
    if baseline:
        attrs[HeartbeatAttrs.BASELINE_COUNT] = baseline.count
        if baseline.count > 0:
            attrs[HeartbeatAttrs.BASELINE_MEAN] = round(baseline.mean, 3)
            attrs[HeartbeatAttrs.BASELINE_STDDEV] = round(baseline.stddev, 3)

            if baseline.count >= baseline.min_samples:
                z_score = baseline.z_score(elapsed)
                is_anomaly = baseline.is_anomaly(elapsed)
                attrs[HeartbeatAttrs.Z_SCORE] = round(z_score, 2)
                attrs[HeartbeatAttrs.ANOMALY] = is_anomaly

                # Rate metric: elapsed vs expected
                if baseline.mean > 0:
                    attrs["heartbeat.elapsed_vs_mean_ratio"] = round(elapsed / baseline.mean, 2)

                if is_anomaly:
                    logger.warning(
                        f"Step anomaly detected: step={step_name} elapsed={elapsed:.1f}s "
                        f"Z={z_score:.2f} (mean={baseline.mean:.1f}s)"
                    )

    if hasattr(span, "add_event"):
        span.add_event(EventNames.HEARTBEAT, attrs)

    logger.debug(f"Step heartbeat #{heartbeat_count}: {step_name} elapsed={elapsed:.1f}s")
    return {"count": heartbeat_count}


def _heartbeat_thread(
    span: Any,
    step_name: str,
    flow_name: str,
    start_time: float,
    interval: float,
    stop_event: threading.Event,
    baseline: Any | None = None,
) -> None:
    """Background thread for emitting heartbeats during sync step execution."""
    count = 0
    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            break
        count += 1
        _emit_sync_heartbeat(span, step_name, flow_name, start_time, count, baseline)


# Overload signatures for both usage patterns:
# @traced_step  and  @traced_step(heartbeat_interval=10.0)
@overload
def traced_step(func: F) -> F: ...
@overload
def traced_step(*, heartbeat_interval: float = 0.0) -> Callable[[F], F]: ...


def traced_step(
    func: F | None = None,
    *,
    heartbeat_interval: float = 0.0,
) -> F | Callable[[F], F]:
    """Decorator for tracing Metaflow step execution.

    Creates an OTel span with standard Metaflow attributes.
    Should be applied BEFORE the @step decorator.

    Supports both decorator styles:
        @traced_step
        @step
        def my_step(self):
            pass

        @traced_step(heartbeat_interval=10.0)
        @step
        def long_step(self):
            # Heartbeats emitted every 10s with meaningful metrics
            pass

    Args:
        heartbeat_interval: If > 0, emit heartbeats every N seconds.
            Each heartbeat includes baseline stats, Z-score, and
            elapsed vs expected ratio for meaningful observability.

    The span will have attributes:
        - metaflow.flow_name: Flow class name
        - metaflow.step_name: Step function name
        - metaflow.run_id: Current run ID (if available)
        - nifi.correlation_id: Correlation ID for NiFi linking
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(self: "TracedFlow", *args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            step_name = fn.__name__
            flow_name = self.__class__.__name__

            span_name = f"metaflow/{flow_name}/{step_name}"

            # Get baseline for heartbeat metrics
            baseline = None
            if heartbeat_interval > 0:
                try:
                    from gaius.core.operation_baseline import get_baseline_registry
                    registry = get_baseline_registry()
                    baseline = registry.get_or_create(
                        f"metaflow.{flow_name}.{step_name}"
                    )
                except ImportError:
                    pass

            with tracer.start_as_current_span(span_name) as span:
                # Set standard attributes
                if hasattr(span, "set_attribute"):
                    span.set_attribute(MetaflowAttrs.FLOW_NAME, flow_name)
                    span.set_attribute(MetaflowAttrs.STEP_NAME, step_name)
                    span.set_attribute(GaiusAttrs.COMPONENT, "metaagent")

                    if heartbeat_interval > 0:
                        span.set_attribute(HeartbeatAttrs.INTERVAL_S, heartbeat_interval)

                    # Set correlation ID for NiFi linking
                    if hasattr(self, "correlation_id"):
                        span.set_attribute(NiFiAttrs.CORRELATION_ID, self.correlation_id)

                    # Set run_id if available (from Metaflow context)
                    if hasattr(self, "_graph") and hasattr(self._graph, "run_id"):
                        span.set_attribute(MetaflowAttrs.RUN_ID, self._graph.run_id)

                    # Record any Parameters defined on the flow
                    for param_name in getattr(self.__class__, "_parameters", {}).keys():
                        if hasattr(self, param_name):
                            value = getattr(self, param_name)
                            if isinstance(value, (str, int, float, bool)):
                                span.set_attribute(
                                    f"{MetaflowAttrs.PARAM_PREFIX}{param_name}", value
                                )

                # Emit step.started event with baseline context
                start_attrs: dict[str, Any] = {"step": step_name}
                if baseline and baseline.count > 0:
                    start_attrs["baseline_mean_s"] = round(baseline.mean, 3)
                    start_attrs["baseline_count"] = baseline.count
                if hasattr(span, "add_event"):
                    span.add_event(EventNames.STEP_STARTED, start_attrs)

                start_time = time.time()
                heartbeat_thread = None
                stop_event = threading.Event()

                # Start heartbeat thread if interval > 0
                if heartbeat_interval > 0:
                    heartbeat_thread = threading.Thread(
                        target=_heartbeat_thread,
                        args=(span, step_name, flow_name, start_time, heartbeat_interval, stop_event, baseline),
                        daemon=True,
                    )
                    heartbeat_thread.start()

                try:
                    result = fn(self, *args, **kwargs)

                    # Emit step.completed event with metrics
                    elapsed_s = time.time() - start_time
                    elapsed_ms = elapsed_s * 1000
                    complete_attrs: dict[str, Any] = {
                        "step": step_name,
                        "duration_ms": elapsed_ms,
                    }

                    # Include baseline comparison in completion event
                    if baseline:
                        complete_attrs["baseline_count"] = baseline.count
                        if baseline.count >= baseline.min_samples:
                            complete_attrs["z_score"] = round(baseline.z_score(elapsed_s), 2)
                            complete_attrs["vs_baseline_ratio"] = round(elapsed_s / baseline.mean, 2) if baseline.mean > 0 else 0

                        # Update baseline with this execution
                        baseline.update(elapsed_s)

                    if hasattr(span, "add_event"):
                        span.add_event(EventNames.STEP_COMPLETED, complete_attrs)

                    return result

                except Exception as e:
                    # Emit step.failed event
                    elapsed_ms = (time.time() - start_time) * 1000
                    if hasattr(span, "add_event"):
                        span.add_event(
                            EventNames.STEP_FAILED,
                            {
                                "step": step_name,
                                "duration_ms": elapsed_ms,
                                "error": str(e),
                            },
                        )
                    if hasattr(span, "record_exception"):
                        span.record_exception(e)
                    raise

                finally:
                    # Stop heartbeat thread
                    if heartbeat_thread is not None:
                        stop_event.set()
                        heartbeat_thread.join(timeout=1.0)

        # Cast is safe: wrapper preserves fn's signature via @wraps
        return cast(F, wrapper)

    # Support both @traced_step and @traced_step(heartbeat_interval=10.0)
    if func is not None:
        return decorator(func)
    return decorator


class TracedFlow:
    """Base class for Metaflow flows with automatic OTel tracing.

    Provides:
        - correlation_id: UUID for linking to NiFi FlowFiles
        - emit_event(): Helper for adding semantic events to current span
        - set_span_attribute(): Helper for adding custom attributes

    Usage:
        from metaflow import FlowSpec, step
        from gaius.agents.metaagent.telemetry import TracedFlow, traced_step

        class MyFlow(TracedFlow, FlowSpec):
            @traced_step
            @step
            def start(self):
                self.emit_event("pdf.extraction.started", {"arxiv_id": "2312.12345"})
                self.next(self.end)

            @traced_step
            @step
            def end(self):
                pass

    Note:
        TracedFlow should be listed BEFORE FlowSpec in the inheritance order
        to ensure proper MRO (Method Resolution Order).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with correlation ID for NiFi linking."""
        super().__init__(*args, **kwargs)
        # Generate correlation ID for this flow run
        # This links Metaflow execution to NiFi FlowFiles
        self.correlation_id = str(uuid.uuid4())

    def emit_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Emit a semantic event on the current span.

        Events are distinct from spans - they mark points in time within
        a span's duration. Use for significant milestones like:
        - pdf.extraction.started
        - topics.extracted
        - nifi.flow.created

        NiFi RouteOnAttribute can filter by event.name for step-specific
        visibility.

        Args:
            name: Event name (use EventNames constants)
            attributes: Optional event attributes
        """
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and hasattr(span, "add_event"):
            span.add_event(name, attributes or {})

    def set_span_attribute(self, key: str, value: Any) -> None:
        """Set a custom attribute on the current span.

        Args:
            key: Attribute name (use MetaflowAttrs/NiFiAttrs constants)
            value: Attribute value (str, int, float, or bool)
        """
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and hasattr(span, "set_attribute"):
            if isinstance(value, (str, int, float, bool)):
                span.set_attribute(key, value)

    def get_correlation_id(self) -> str:
        """Get the correlation ID for NiFi linking.

        This ID should be passed to NiFi as a FlowFile attribute
        for end-to-end traceability.

        Note: Uses lazy initialization because Metaflow doesn't call __init__
        the normal Python way - it serializes/deserializes between steps.
        """
        if not hasattr(self, "correlation_id") or self.correlation_id is None:
            self.correlation_id = str(uuid.uuid4())
        return self.correlation_id


# Convenience re-export of EventNames for emit_event usage
__all__ = ["TracedFlow", "traced_step", "EventNames"]
