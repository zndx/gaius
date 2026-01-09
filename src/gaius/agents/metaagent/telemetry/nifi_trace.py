"""NiFi API operation tracing for MetaAgent.

Provides @trace_nifi_operation decorator for instrumenting NiFi REST API calls.

Usage:
    from gaius.agents.metaagent.telemetry import trace_nifi_operation

    @trace_nifi_operation("create_processor")
    async def create_processor(self, process_group_id, ...):
        # Span created with nifi.operation_type="create_processor"
        pass

Metrics:
    gaius.nifi.api.calls: Counter of NiFi API calls
    gaius.nifi.api.latency: Histogram of API call latencies
"""

import functools
import inspect
import time
from typing import Any, Callable, TypeVar, cast

from gaius.core.telemetry import get_meter, get_tracer

from .attributes import GaiusAttrs, NiFiAttrs

# Type variable for preserving function signatures
F = TypeVar("F", bound=Callable[..., Any])

# Lazy-initialized metrics
_nifi_calls_counter = None
_nifi_latency_histogram = None


def _get_nifi_metrics() -> tuple:
    """Get or create NiFi metrics instruments."""
    global _nifi_calls_counter, _nifi_latency_histogram

    if _nifi_calls_counter is None:
        meter = get_meter()
        _nifi_calls_counter = meter.create_counter(
            "gaius.nifi.api.calls",
            description="Number of NiFi API calls",
            unit="1",
        )
        _nifi_latency_histogram = meter.create_histogram(
            "gaius.nifi.api.latency",
            description="NiFi API call latency",
            unit="ms",
        )

    return _nifi_calls_counter, _nifi_latency_histogram


def trace_nifi_operation(operation_type: str) -> Callable[[F], F]:
    """Decorator for tracing NiFi API operations.

    Creates an OTel span with NiFi-specific attributes and records
    metrics for API call counts and latencies.

    Args:
        operation_type: The type of NiFi operation (e.g., "create_processor",
            "get_process_group_contents", "delete_connection")

    Example:
        @trace_nifi_operation("create_processor")
        async def create_processor(self, process_group_id, ...):
            pass

    The span will have attributes:
        - nifi.operation_type: The operation being performed
        - nifi.response_time_ms: API response time
        - nifi.process_group_id: Target process group (if provided)
        - nifi.processor_id: Target processor (if provided)
        - gaius.component: "metaagent"

    Metrics recorded:
        - gaius.nifi.api.calls{operation_type}: Count of calls
        - gaius.nifi.api.latency{operation_type}: Latency histogram
    """

    def decorator(func: F) -> F:
        # Check if function is async
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _trace_operation(func, operation_type, args, kwargs, True)

            # Cast is safe: async_wrapper preserves func's signature via @wraps;
            # type checker can't verify decorators preserve signatures
            return cast(F, async_wrapper)
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                import asyncio

                # This shouldn't happen for NiFi client (all async), but handle it
                return asyncio.get_event_loop().run_until_complete(
                    _trace_operation(func, operation_type, args, kwargs, False)
                )

            # Cast is safe: sync_wrapper preserves func's signature via @wraps;
            # type checker can't verify decorators preserve signatures
            return cast(F, sync_wrapper)

    return decorator


async def _trace_operation(
    func: Callable,
    operation_type: str,
    args: tuple,
    kwargs: dict,
    is_async: bool,
) -> Any:
    """Execute function with tracing and metrics."""
    tracer = get_tracer()
    calls_counter, latency_histogram = _get_nifi_metrics()

    span_name = f"nifi/{operation_type}"

    with tracer.start_as_current_span(span_name) as span:
        # Set standard attributes
        if hasattr(span, "set_attribute"):
            span.set_attribute(NiFiAttrs.OPERATION_TYPE, operation_type)
            span.set_attribute(GaiusAttrs.COMPONENT, "metaagent")

            # Extract common IDs from kwargs or positional args
            _set_id_attributes(span, args, kwargs)

        start_time = time.time()
        try:
            # Call the actual function
            if is_async:
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Record latency
            latency_ms = (time.time() - start_time) * 1000
            if hasattr(span, "set_attribute"):
                span.set_attribute(NiFiAttrs.RESPONSE_TIME_MS, latency_ms)

            # Record metrics
            metric_attrs = {"operation_type": operation_type, "status": "success"}
            calls_counter.add(1, metric_attrs)
            latency_histogram.record(latency_ms, metric_attrs)

            return result

        except Exception as e:
            # Record latency even on failure
            latency_ms = (time.time() - start_time) * 1000
            if hasattr(span, "set_attribute"):
                span.set_attribute(NiFiAttrs.RESPONSE_TIME_MS, latency_ms)

            # Record error metrics
            metric_attrs = {"operation_type": operation_type, "status": "error"}
            calls_counter.add(1, metric_attrs)
            latency_histogram.record(latency_ms, metric_attrs)

            # Record exception on span
            if hasattr(span, "record_exception"):
                span.record_exception(e)

            raise


def _set_id_attributes(span: Any, args: tuple, kwargs: dict) -> None:
    """Extract and set common ID attributes from function arguments."""
    # Check kwargs first, then positional args
    # Common parameter names in NiFi client methods

    # Process group ID
    if "process_group_id" in kwargs:
        span.set_attribute(NiFiAttrs.PROCESS_GROUP_ID, kwargs["process_group_id"])
    elif "group_id" in kwargs:
        span.set_attribute(NiFiAttrs.PROCESS_GROUP_ID, kwargs["group_id"])
    elif "parent_id" in kwargs:
        span.set_attribute(NiFiAttrs.PROCESS_GROUP_ID, kwargs["parent_id"])

    # Processor ID
    if "processor_id" in kwargs:
        span.set_attribute(NiFiAttrs.PROCESSOR_ID, kwargs["processor_id"])

    # Connection ID
    if "connection_id" in kwargs:
        span.set_attribute(NiFiAttrs.CONNECTION_ID, kwargs["connection_id"])

    # Processor name (if creating)
    if "name" in kwargs:
        span.set_attribute(NiFiAttrs.PROCESSOR_NAME, kwargs["name"])

    # Processor type (if creating)
    if "processor_type" in kwargs:
        span.set_attribute(NiFiAttrs.PROCESSOR_TYPE, kwargs["processor_type"])


__all__ = ["trace_nifi_operation"]
