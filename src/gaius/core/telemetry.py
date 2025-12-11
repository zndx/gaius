"""OpenTelemetry instrumentation for Gaius.

Provides tracing, metrics, and logging via OpenTelemetry.

Entry Point Identification:
    Each entry point (TUI, CLI, MCP, Engine, Worker) gets a distinct
    service.name for observability platform filtering:
    - gaius-tui
    - gaius-cli
    - gaius-mcp
    - gaius-engine
    - gaius-worker

Disabling Telemetry:
    Set OTEL_SDK_DISABLED=true in environment to disable telemetry.
    This is the standard OTel mechanism for disabling instrumentation.

Usage:
    from gaius.core.telemetry import get_tracer, get_meter, trace_operation

    tracer = get_tracer()
    with tracer.start_as_current_span("operation_name"):
        # do work

    # Or use the decorator
    @trace_operation("search")
    def search_kb(query: str):
        pass
"""

import functools
import os
import socket
from contextlib import contextmanager
from typing import Any, Callable, Iterator

# Lazy imports to avoid dependency issues if OTel not installed
_tracer = None
_meter = None
_initialized = False
_entry_point = "cli"  # Default entry point

# Valid entry points
ENTRY_POINTS = ("tui", "cli", "mcp", "engine", "worker")


def _is_otel_disabled() -> bool:
    """Check if OTel is disabled via standard environment variable.

    Per OTel spec, OTEL_SDK_DISABLED=true disables all instrumentation.
    """
    return os.getenv("OTEL_SDK_DISABLED", "").lower() == "true"


def _init_telemetry(config: "TelemetryConfig", entry_point: str = "cli") -> None:
    """Initialize OpenTelemetry based on config.

    Telemetry is enabled by default. Set OTEL_SDK_DISABLED=true to disable.

    Args:
        config: Telemetry configuration from HOCON
        entry_point: Entry point identifier (tui, cli, mcp, engine, worker)
    """
    global _tracer, _meter, _initialized, _entry_point

    if _initialized:
        return

    # Validate entry point
    if entry_point not in ENTRY_POINTS:
        entry_point = "cli"
    _entry_point = entry_point

    # Check standard OTel disable flag first
    if _is_otel_disabled():
        _initialized = True
        return

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource

        # Create resource with service info per OTel semantic conventions
        # service.name is distinct per entry point for dashboard filtering
        service_name = f"gaius-{entry_point}"
        resource = Resource.create({
            "service.name": service_name,
            "service.namespace": "gaius",
            "service.version": "0.2.0",
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
            "deployment.environment.name": os.getenv("GAIUS_ENV", "dev"),
        })

        # Setup tracer
        tracer_provider = TracerProvider(resource=resource)

        # Configure exporter based on config
        if config.exporter == "otlp":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(endpoint=config.endpoint)
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            # Console exporter for dev/debug
            from opentelemetry.sdk.trace.export import (
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )

            tracer_provider.add_span_processor(
                SimpleSpanProcessor(ConsoleSpanExporter())
            )

        trace.set_tracer_provider(tracer_provider)
        _tracer = trace.get_tracer("gaius")

        # Setup meter with exporter
        if config.exporter == "otlp":
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            metric_exporter = OTLPMetricExporter(endpoint=config.endpoint)
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=15000,  # Export every 15 seconds
            )
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )
        else:
            # Console exporter for dev/debug
            from opentelemetry.sdk.metrics.export import (
                ConsoleMetricExporter,
                PeriodicExportingMetricReader,
            )

            metric_reader = PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=15000,
            )
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )

        metrics.set_meter_provider(meter_provider)
        _meter = metrics.get_meter("gaius")

        _initialized = True

    except ImportError:
        # OpenTelemetry not installed - silently disable
        _initialized = True


class NoOpSpan:
    """No-op span when telemetry is disabled."""

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass


class NoOpTracer:
    """No-op tracer when telemetry is disabled."""

    @contextmanager
    def start_as_current_span(
        self, name: str, **kwargs: Any
    ) -> Iterator[NoOpSpan]:
        yield NoOpSpan()


class NoOpMeter:
    """No-op meter when telemetry is disabled."""

    def create_counter(self, name: str, **kwargs: Any) -> "NoOpCounter":
        return NoOpCounter()

    def create_histogram(self, name: str, **kwargs: Any) -> "NoOpHistogram":
        return NoOpHistogram()

    def create_up_down_counter(
        self, name: str, **kwargs: Any
    ) -> "NoOpUpDownCounter":
        return NoOpUpDownCounter()


class NoOpCounter:
    def add(self, amount: int | float, attributes: dict | None = None) -> None:
        pass


class NoOpHistogram:
    def record(
        self, amount: int | float, attributes: dict | None = None
    ) -> None:
        pass


class NoOpUpDownCounter:
    def add(self, amount: int | float, attributes: dict | None = None) -> None:
        pass


def get_tracer() -> Any:
    """Get the OpenTelemetry tracer.

    Returns a NoOpTracer if telemetry is disabled or not initialized.
    """
    if _tracer is None:
        return NoOpTracer()
    return _tracer


def get_meter() -> Any:
    """Get the OpenTelemetry meter.

    Returns a NoOpMeter if telemetry is disabled or not initialized.
    """
    if _meter is None:
        return NoOpMeter()
    return _meter


def trace_operation(
    operation_name: str,
    record_args: bool = False,
) -> Callable:
    """Decorator to trace a function call.

    Args:
        operation_name: Name for the span (e.g., "search", "inference")
        record_args: If True, record function arguments as span attributes

    Example:
        @trace_operation("kb_search")
        def search(query: str, limit: int = 10):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(operation_name) as span:
                if record_args and hasattr(span, "set_attribute"):
                    # Record kwargs as attributes
                    for key, value in kwargs.items():
                        if isinstance(value, (str, int, float, bool)):
                            span.set_attribute(f"arg.{key}", value)

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    if hasattr(span, "record_exception"):
                        span.record_exception(e)
                    raise

        return wrapper

    return decorator


def init_from_config(config: Any, entry_point: str = "cli") -> None:
    """Initialize telemetry from GaiusConfig.

    Call this during app startup:
        from gaius.core.telemetry import init_from_config
        init_from_config(config, entry_point="cli")

    Args:
        config: GaiusConfig with telemetry settings
        entry_point: Entry point identifier (tui, cli, mcp, engine, worker)
    """
    _init_telemetry(config.telemetry, entry_point=entry_point)


def get_entry_point() -> str:
    """Get the current entry point identifier.

    Returns:
        Entry point string (tui, cli, mcp, engine, worker)
    """
    return _entry_point


@contextmanager
def traced_command(command: str, function_name: str | None = None) -> Iterator[Any]:
    """Create a span for a command execution with standard attributes.

    This is the preferred way to trace command execution across all entry points.
    Creates spans following the naming convention: gaius.{entry_point}/command/{cmd}

    Args:
        command: The command being executed (e.g., "state", "domain", "search_kb")
        function_name: Optional function name for code.function.name attribute

    Yields:
        The span (may be NoOpSpan if telemetry disabled)

    Example:
        with traced_command("domain", "cmd_domain") as span:
            # handle command
            span.set_attribute("domain", "pension")
    """
    tracer = get_tracer()
    entry = get_entry_point()
    span_name = f"gaius.{entry}/command/{command}"

    with tracer.start_as_current_span(span_name) as span:
        # Set standard attributes per plan
        if hasattr(span, "set_attribute"):
            span.set_attribute("gaius.command", command)
            span.set_attribute("gaius.entry_point", entry)
            if function_name:
                span.set_attribute("code.function.name", function_name)
        yield span


# Pre-defined metrics for common operations
_search_counter = None
_inference_counter = None
_inference_latency = None
_swarm_rounds = None


def get_metrics() -> dict[str, Any]:
    """Get pre-defined metrics instruments.

    Returns dict with:
        - search_counter: Count of search operations
        - inference_counter: Count of inference calls
        - inference_latency: Histogram of inference latencies
        - swarm_rounds: Count of swarm coordination rounds
    """
    global _search_counter, _inference_counter, _inference_latency, _swarm_rounds

    meter = get_meter()

    if _search_counter is None:
        _search_counter = meter.create_counter(
            "gaius.search.count",
            description="Number of search operations",
            unit="1",
        )

    if _inference_counter is None:
        _inference_counter = meter.create_counter(
            "gaius.inference.count",
            description="Number of inference calls",
            unit="1",
        )

    if _inference_latency is None:
        _inference_latency = meter.create_histogram(
            "gaius.inference.latency",
            description="Inference call latency",
            unit="ms",
        )

    if _swarm_rounds is None:
        _swarm_rounds = meter.create_counter(
            "gaius.swarm.rounds",
            description="Number of swarm coordination rounds",
            unit="1",
        )

    return {
        "search_counter": _search_counter,
        "inference_counter": _inference_counter,
        "inference_latency": _inference_latency,
        "swarm_rounds": _swarm_rounds,
    }


def record_search(query: str, results_count: int, source: str = "hybrid") -> None:
    """Record a search operation.

    Args:
        query: The search query
        results_count: Number of results returned
        source: Search source (kb, web, hybrid)
    """
    metrics = get_metrics()
    metrics["search_counter"].add(
        1,
        {
            "source": source,
            "results_count": results_count,
        },
    )


def record_inference(
    model: str,
    tokens: int,
    latency_ms: float,
    technique: str = "",
) -> None:
    """Record an inference operation.

    Args:
        model: Model identifier
        tokens: Token count (input + output)
        latency_ms: Call latency in milliseconds
        technique: optillm technique used (if any)
    """
    metrics = get_metrics()
    attrs = {"model": model}
    if technique:
        attrs["technique"] = technique

    metrics["inference_counter"].add(1, attrs)
    metrics["inference_latency"].record(latency_ms, attrs)


def record_swarm_round(agent_count: int, domain: str) -> None:
    """Record a swarm coordination round.

    Args:
        agent_count: Number of agents participating
        domain: Current analysis domain
    """
    metrics = get_metrics()
    metrics["swarm_rounds"].add(
        1,
        {
            "agent_count": agent_count,
            "domain": domain,
        },
    )


def flush_telemetry(timeout_ms: int = 5000) -> bool:
    """Flush pending telemetry data to the collector.

    Call this before exiting short-lived processes (CLI commands) to ensure
    metrics and traces are exported. For long-running apps (TUI), the SDK
    handles periodic export automatically.

    Args:
        timeout_ms: Maximum time to wait for flush in milliseconds

    Returns:
        True if flush succeeded, False otherwise
    """
    if _is_otel_disabled() or not _initialized:
        return True

    success = True
    try:
        from opentelemetry import trace, metrics

        # Flush traces
        tracer_provider = trace.get_tracer_provider()
        if hasattr(tracer_provider, "force_flush"):
            if not tracer_provider.force_flush(timeout_millis=timeout_ms):
                success = False

        # Flush metrics
        meter_provider = metrics.get_meter_provider()
        if hasattr(meter_provider, "force_flush"):
            if not meter_provider.force_flush(timeout_millis=timeout_ms):
                success = False

    except Exception:
        success = False

    return success
