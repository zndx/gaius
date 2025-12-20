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
"""

import functools
import time
import uuid
from typing import Any, Callable, TypeVar

from gaius.core.telemetry import get_tracer

from .attributes import EventNames, GaiusAttrs, MetaflowAttrs, NiFiAttrs

# Type variable for preserving function signatures
F = TypeVar("F", bound=Callable[..., Any])


def traced_step(func: F) -> F:
    """Decorator for tracing Metaflow step execution.

    Creates an OTel span with standard Metaflow attributes.
    Should be applied BEFORE the @step decorator.

    Example:
        @traced_step
        @step
        def my_step(self):
            pass

    The span will have attributes:
        - metaflow.flow_name: Flow class name
        - metaflow.step_name: Step function name
        - metaflow.run_id: Current run ID (if available)
        - nifi.correlation_id: Correlation ID for NiFi linking
    """

    @functools.wraps(func)
    def wrapper(self: "TracedFlow", *args: Any, **kwargs: Any) -> Any:
        tracer = get_tracer()
        step_name = func.__name__
        flow_name = self.__class__.__name__

        span_name = f"metaflow/{flow_name}/{step_name}"

        with tracer.start_as_current_span(span_name) as span:
            # Set standard attributes
            if hasattr(span, "set_attribute"):
                span.set_attribute(MetaflowAttrs.FLOW_NAME, flow_name)
                span.set_attribute(MetaflowAttrs.STEP_NAME, step_name)
                span.set_attribute(GaiusAttrs.COMPONENT, "metaagent")

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

            # Emit step.started event
            if hasattr(span, "add_event"):
                span.add_event(EventNames.STEP_STARTED, {"step": step_name})

            start_time = time.time()
            try:
                result = func(self, *args, **kwargs)

                # Emit step.completed event
                elapsed_ms = (time.time() - start_time) * 1000
                if hasattr(span, "add_event"):
                    span.add_event(
                        EventNames.STEP_COMPLETED,
                        {"step": step_name, "duration_ms": elapsed_ms},
                    )

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

    return wrapper  # type: ignore


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
        """
        return self.correlation_id


# Convenience re-export of EventNames for emit_event usage
__all__ = ["TracedFlow", "traced_step", "EventNames"]
