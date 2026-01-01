"""OpenTelemetry metrics for Gaius Engine.

Centralizes all OTel metric export from the engine. This is the single source
of truth for metrics - CLI, TUI, and MCP route metrics through the engine.

The engine exports:
- Inference metrics (latency, throughput, errors)
- GPU metrics (memory, utilization)
- Endpoint health metrics
- Evolution/scheduler metrics
- Self-healing metrics (attempts, success, escalations)

Architecture:
  CLI/TUI/MCP --> gRPC --> Engine --> OTel Collector --> Prometheus
                          ^^^^^^^
                     metrics exported here

Usage:
    from gaius.engine.metrics import EngineMetrics

    # Initialize once at engine startup
    metrics = EngineMetrics.get_instance()

    # Record metrics
    metrics.record_inference(model="reasoning", latency_ms=150, tokens=500)
    metrics.record_gpu_memory(gpu_id=0, used_mb=12000, total_mb=24000)
    metrics.record_healing_attempt(endpoint="reasoning", tier=0, success=True)
"""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Global singleton instance
_metrics_instance: Optional["EngineMetrics"] = None


class EngineMetrics:
    """Centralized OTel metrics for the engine.

    Uses OpenTelemetry SDK to create and record metrics that are exported
    to the OTel collector (and then to Prometheus).
    """

    def __init__(self):
        """Initialize metrics instruments."""
        self._initialized = False
        self._meter: Any = None

        # Inference metrics
        self._inference_count: Any = None
        self._inference_latency: Any = None
        self._inference_errors: Any = None
        self._inference_tokens: Any = None

        # GPU metrics (gauges via observable callbacks)
        self._gpu_memory_used: Any = None
        self._gpu_memory_total: Any = None
        self._gpu_utilization: Any = None
        self._gpu_flops_utilization: Any = None  # FLOPS-weighted aggregate

        # Endpoint metrics
        self._endpoint_healthy: Any = None
        self._endpoint_requests: Any = None

        # Scheduler metrics
        self._scheduler_queue_depth: Any = None
        self._scheduler_active_jobs: Any = None

        # Evolution metrics
        self._evolution_cycles: Any = None
        self._evolution_improvements: Any = None

        # Search metrics
        self._search_count: Any = None
        self._search_latency: Any = None

        # Healing metrics (matching healing_metrics.py naming)
        self._healing_attempts: Any = None
        self._healing_success: Any = None
        self._healing_failure: Any = None
        self._healing_escalations: Any = None
        self._healing_duration: Any = None
        self._healing_in_progress: Any = None
        self._healing_cooldown: Any = None

        # Error/request metrics for rate calculations
        self._request_total: Any = None
        self._error_total: Any = None

        self._init_instruments()

    def _init_instruments(self) -> None:
        """Create OTel metric instruments.

        Uses the global meter from core.telemetry module which is initialized
        by the engine server. This ensures we use the same MeterProvider.
        """
        if self._initialized:
            return

        # Check if OTel is disabled
        if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
            logger.debug("OTel disabled, engine metrics will be no-ops")
            self._initialized = True
            return

        try:
            # Use the global meter from core.telemetry
            from ..core.telemetry import get_meter

            self._meter = get_meter()

            # Check if we got a real meter (not NoOpMeter)
            if hasattr(self._meter, "__class__") and "NoOp" in self._meter.__class__.__name__:
                logger.debug("OTel not initialized yet, engine metrics deferred")
                # Don't mark as initialized - we'll retry later
                return

            # Create instruments
            self._create_inference_instruments()
            self._create_gpu_instruments()
            self._create_endpoint_instruments()
            self._create_scheduler_instruments()
            self._create_evolution_instruments()
            self._create_search_instruments()
            self._create_healing_instruments()
            self._create_general_instruments()

            self._initialized = True
            logger.info("Engine OTel metrics instruments created")

        except ImportError as e:
            logger.warning(f"OpenTelemetry packages not installed: {e}")
            self._initialized = True
        except Exception as e:
            logger.warning(f"Failed to initialize OTel metrics: {e}")
            self._initialized = True

    def _create_inference_instruments(self) -> None:
        """Create inference-related instruments."""
        if not self._meter:
            return

        self._inference_count = self._meter.create_counter(
            "gaius.inference.count",
            description="Total inference requests",
            unit="1",
        )
        self._inference_latency = self._meter.create_histogram(
            "gaius.inference.latency",
            description="Inference latency in milliseconds",
            unit="ms",
        )
        self._inference_errors = self._meter.create_counter(
            "gaius.inference.errors",
            description="Inference errors",
            unit="1",
        )
        self._inference_tokens = self._meter.create_counter(
            "gaius.inference.tokens",
            description="Total tokens processed",
            unit="1",
        )

    def _create_gpu_instruments(self) -> None:
        """Create GPU-related instruments."""
        if not self._meter:
            return

        self._gpu_memory_used = self._meter.create_histogram(
            "gaius.gpu.memory_used",
            description="GPU memory used in MB",
            unit="MB",
        )
        self._gpu_utilization = self._meter.create_histogram(
            "gaius.gpu.utilization",
            description="GPU utilization percentage",
            unit="%",
        )
        # FLOPS-weighted aggregate utilization for Observe panel sparkline
        self._gpu_flops_utilization = self._meter.create_gauge(
            "gaius.gpu.flops_utilization",
            description="FLOPS-weighted GPU utilization across all GPUs",
            unit="%",
        )

    def _create_endpoint_instruments(self) -> None:
        """Create endpoint-related instruments."""
        if not self._meter:
            return

        self._endpoint_healthy = self._meter.create_up_down_counter(
            "gaius.endpoint.healthy",
            description="Number of healthy endpoints",
            unit="1",
        )
        self._endpoint_requests = self._meter.create_counter(
            "gaius.endpoint.requests",
            description="Requests per endpoint",
            unit="1",
        )

    def _create_scheduler_instruments(self) -> None:
        """Create scheduler-related instruments."""
        if not self._meter:
            return

        self._scheduler_queue_depth = self._meter.create_up_down_counter(
            "gaius.scheduler.queue_depth",
            description="Jobs in scheduler queue",
            unit="1",
        )
        self._scheduler_active_jobs = self._meter.create_up_down_counter(
            "gaius.scheduler.active_jobs",
            description="Currently executing jobs",
            unit="1",
        )

    def _create_evolution_instruments(self) -> None:
        """Create evolution-related instruments."""
        if not self._meter:
            return

        self._evolution_cycles = self._meter.create_counter(
            "gaius.evolution.cycles",
            description="Completed evolution cycles",
            unit="1",
        )
        self._evolution_improvements = self._meter.create_counter(
            "gaius.evolution.improvements",
            description="Successful improvements",
            unit="1",
        )

    def _create_search_instruments(self) -> None:
        """Create search-related instruments."""
        if not self._meter:
            return

        self._search_count = self._meter.create_counter(
            "gaius.search.count",
            description="Total search operations",
            unit="1",
        )
        self._search_latency = self._meter.create_histogram(
            "gaius.search.latency",
            description="Search latency in milliseconds",
            unit="ms",
        )

    def _create_healing_instruments(self) -> None:
        """Create healing-related instruments.

        Names match the ObservePanel expectations:
        - gaius_gaius_healing_attempts_total
        - gaius_gaius_healing_success_total
        - gaius_gaius_healing_escalations_total
        """
        if not self._meter:
            return

        self._healing_attempts = self._meter.create_counter(
            "gaius.healing.attempts",
            description="Total healing attempts",
            unit="1",
        )
        self._healing_success = self._meter.create_counter(
            "gaius.healing.success",
            description="Successful healing attempts",
            unit="1",
        )
        self._healing_failure = self._meter.create_counter(
            "gaius.healing.failure",
            description="Failed healing attempts",
            unit="1",
        )
        self._healing_escalations = self._meter.create_counter(
            "gaius.healing.escalations",
            description="Tier escalations",
            unit="1",
        )
        self._healing_duration = self._meter.create_histogram(
            "gaius.healing.duration_ms",
            description="Healing attempt duration in milliseconds",
            unit="ms",
        )
        self._healing_in_progress = self._meter.create_up_down_counter(
            "gaius.healing.in_progress",
            description="Healing attempts in progress",
            unit="1",
        )
        self._healing_cooldown = self._meter.create_up_down_counter(
            "gaius.healing.cooldown_active",
            description="Endpoints in cooldown",
            unit="1",
        )

    def _create_general_instruments(self) -> None:
        """Create general request/error instruments for rate calculations."""
        if not self._meter:
            return

        self._request_total = self._meter.create_counter(
            "gaius.request",
            description="Total requests",
            unit="1",
        )
        self._error_total = self._meter.create_counter(
            "gaius.error",
            description="Total errors",
            unit="1",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Recording Methods
    # ─────────────────────────────────────────────────────────────────────────

    def record_inference(
        self,
        model: str,
        latency_ms: float,
        tokens: int = 0,
        success: bool = True,
        technique: str = "",
    ) -> None:
        """Record an inference request.

        Args:
            model: Model/endpoint name
            latency_ms: Request latency in ms
            tokens: Tokens processed (input + output)
            success: Whether request succeeded
            technique: optillm technique if used
        """
        if not self._inference_count:
            logger.warning(
                f"record_inference called but _inference_count is None "
                f"(initialized={self._initialized}, model={model})"
            )
            return

        attrs = {"model": model}
        if technique:
            attrs["technique"] = technique

        logger.info(f"Recording inference metric: model={model}, latency={latency_ms}ms, tokens={tokens}")
        self._inference_count.add(1, attrs)
        self._inference_latency.record(latency_ms, attrs)
        if tokens > 0:
            self._inference_tokens.add(tokens, attrs)

        self._request_total.add(1, {"type": "inference"})

        if not success:
            self._inference_errors.add(1, attrs)
            self._error_total.add(1, {"type": "inference"})

    def record_search(
        self,
        source: str,
        results_count: int,
        latency_ms: float = 0,
    ) -> None:
        """Record a search operation.

        Args:
            source: Search source (kb, web, hybrid)
            results_count: Number of results
            latency_ms: Search latency
        """
        if not self._search_count:
            return

        attrs = {"source": source, "results_count": str(results_count)}
        self._search_count.add(1, attrs)
        if latency_ms > 0:
            self._search_latency.record(latency_ms, attrs)

        self._request_total.add(1, {"type": "search"})

    def record_gpu_metrics(
        self,
        gpu_id: int,
        memory_used_mb: float,
        memory_total_mb: float,
        utilization_percent: float,
    ) -> None:
        """Record GPU metrics snapshot.

        Args:
            gpu_id: GPU index
            memory_used_mb: Used memory in MB
            memory_total_mb: Total memory in MB
            utilization_percent: GPU utilization percentage
        """
        if not self._gpu_memory_used:
            return

        attrs = {"gpu_id": str(gpu_id)}
        self._gpu_memory_used.record(memory_used_mb, attrs)
        self._gpu_utilization.record(utilization_percent, attrs)

    def record_gpu_flops_utilization(self, utilization_pct: float) -> None:
        """Record FLOPS-weighted GPU utilization aggregate.

        This is the streaming Welford mean across all GPUs, weighted by
        each GPU's theoretical TFLOPS capacity. Used for the Observe panel
        Compute sparkline.

        Args:
            utilization_pct: Current FLOPS-weighted utilization (0-100)
        """
        if not self._gpu_flops_utilization:
            return
        self._gpu_flops_utilization.set(utilization_pct)

    def record_endpoint_health(
        self,
        endpoint: str,
        healthy: bool,
    ) -> None:
        """Record endpoint health change.

        Args:
            endpoint: Endpoint name
            healthy: Whether endpoint is healthy
        """
        if not self._endpoint_healthy:
            return

        delta = 1 if healthy else -1
        self._endpoint_healthy.add(delta, {"endpoint": endpoint})

    def record_endpoint_request(self, endpoint: str) -> None:
        """Record a request to an endpoint.

        Args:
            endpoint: Endpoint name
        """
        if not self._endpoint_requests:
            return
        self._endpoint_requests.add(1, {"endpoint": endpoint})

    def record_scheduler_queue_change(self, delta: int) -> None:
        """Record scheduler queue depth change.

        Args:
            delta: Change in queue depth (+1 for enqueue, -1 for dequeue)
        """
        if not self._scheduler_queue_depth:
            return
        self._scheduler_queue_depth.add(delta)

    def record_scheduler_job_start(self) -> None:
        """Record a job starting execution."""
        if not self._scheduler_active_jobs:
            return
        self._scheduler_active_jobs.add(1)

    def record_scheduler_job_end(self) -> None:
        """Record a job completing execution."""
        if not self._scheduler_active_jobs:
            return
        self._scheduler_active_jobs.add(-1)

    def record_evolution_cycle(self, improved: bool = False) -> None:
        """Record an evolution cycle completion.

        Args:
            improved: Whether the cycle produced an improvement
        """
        if not self._evolution_cycles:
            return
        self._evolution_cycles.add(1)
        if improved:
            self._evolution_improvements.add(1)

    def record_healing_attempt(
        self,
        endpoint: str,
        tier: int,
        action: str,
        success: bool,
        duration_ms: float = 0,
    ) -> None:
        """Record a healing attempt.

        Args:
            endpoint: Affected endpoint
            tier: Healing tier (0, 1, 2)
            action: Action taken
            success: Whether attempt succeeded
            duration_ms: Duration of attempt
        """
        if not self._healing_attempts:
            return

        attrs = {
            "endpoint": endpoint,
            "tier": str(tier),
            "action": action,
        }

        self._healing_attempts.add(1, attrs)

        if success:
            self._healing_success.add(1, attrs)
        else:
            self._healing_failure.add(1, attrs)

        if duration_ms > 0:
            self._healing_duration.record(duration_ms, attrs)

    def record_healing_escalation(
        self,
        endpoint: str,
        from_tier: int,
        to_tier: int,
    ) -> None:
        """Record a healing tier escalation.

        Args:
            endpoint: Affected endpoint
            from_tier: Source tier
            to_tier: Target tier
        """
        if not self._healing_escalations:
            return

        self._healing_escalations.add(1, {
            "endpoint": endpoint,
            "from_tier": str(from_tier),
            "to_tier": str(to_tier),
        })

    def record_healing_start(self, endpoint: str) -> None:
        """Record that healing has started for an endpoint."""
        if not self._healing_in_progress:
            return
        self._healing_in_progress.add(1, {"endpoint": endpoint})

    def record_healing_end(self, endpoint: str) -> None:
        """Record that healing has ended for an endpoint."""
        if not self._healing_in_progress:
            return
        self._healing_in_progress.add(-1, {"endpoint": endpoint})

    def record_cooldown_change(self, endpoint: str, active: bool) -> None:
        """Record cooldown status change.

        Args:
            endpoint: Affected endpoint
            active: Whether cooldown is now active
        """
        if not self._healing_cooldown:
            return
        delta = 1 if active else -1
        self._healing_cooldown.add(delta, {"endpoint": endpoint})

    def record_error(self, error_type: str = "general") -> None:
        """Record a general error.

        Args:
            error_type: Type of error
        """
        if not self._error_total:
            return
        self._error_total.add(1, {"type": error_type})

    @classmethod
    def get_instance(cls) -> "EngineMetrics":
        """Get the singleton metrics instance."""
        global _metrics_instance
        if _metrics_instance is None:
            _metrics_instance = cls()
        return _metrics_instance


# Convenience functions for direct access
def record_inference(
    model: str,
    latency_ms: float,
    tokens: int = 0,
    success: bool = True,
    technique: str = "",
) -> None:
    """Record an inference request."""
    EngineMetrics.get_instance().record_inference(
        model, latency_ms, tokens, success, technique
    )


def record_search(source: str, results_count: int, latency_ms: float = 0) -> None:
    """Record a search operation."""
    EngineMetrics.get_instance().record_search(source, results_count, latency_ms)


def record_healing_attempt(
    endpoint: str,
    tier: int,
    action: str,
    success: bool,
    duration_ms: float = 0,
) -> None:
    """Record a healing attempt."""
    EngineMetrics.get_instance().record_healing_attempt(
        endpoint, tier, action, success, duration_ms
    )


def record_healing_escalation(endpoint: str, from_tier: int, to_tier: int) -> None:
    """Record a healing tier escalation."""
    EngineMetrics.get_instance().record_healing_escalation(endpoint, from_tier, to_tier)
