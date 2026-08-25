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


def _z_score_bucket(z: float) -> str:
    """Convert Z-score to bucket label for metrics aggregation."""
    if z < 2.0:
        return "normal"
    elif z < 3.0:
        return "elevated"
    elif z < 4.0:
        return "high"
    else:
        return "extreme"


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
        self._inference_tokens_in: Any = None  # Input tokens (prompt)
        self._inference_tokens_out: Any = None  # Output tokens (completion)

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

        # Incident tracking (for Observe panel visibility)
        self._incidents_active: Any = None

        # Error/request metrics for rate calculations
        self._request_total: Any = None
        self._error_total: Any = None

        # Operational exception tracking (for fail-fast visibility)
        self._exception_caught: Any = None

        # Operation/heartbeat metrics (for timeout replacement)
        self._operation_duration: Any = None
        self._operation_heartbeat: Any = None
        self._operation_anomaly: Any = None

        # Landing page pipeline metrics
        self._pipeline_task_duration: Any = None  # Histogram
        self._pipeline_task_success: Any = None  # Counter (by task_type label)
        self._pipeline_task_failure: Any = None  # Counter (by task_type label)
        self._pipeline_cards_published: Any = None  # Counter
        self._pipeline_articles_curated: Any = None  # Counter
        self._pipeline_pending_cards: Any = None  # Gauge
        self._cognition_tremor: Any = None  # Gauge — Discover 1h Kumo SoR

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
                logger.debug("OTel not initialized, engine metrics will be no-ops")
                self._initialized = True
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
            self._create_exception_instruments()
            self._create_operation_instruments()
            self._create_pipeline_instruments()
            self._create_cognition_instruments()

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
        self._inference_tokens_in = self._meter.create_counter(
            "gaius.inference.tokens_in",
            description="Input tokens (prompts)",
            unit="1",
        )
        self._inference_tokens_out = self._meter.create_counter(
            "gaius.inference.tokens_out",
            description="Output tokens (completions)",
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

        # Incident tracking gauge for Observe panel
        # This tracks currently active incidents (including those with open GitHub issues)
        self._incidents_active = self._meter.create_up_down_counter(
            "gaius.incidents.active",
            description="Currently active health incidents",
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

    def _create_exception_instruments(self) -> None:
        """Create instruments for tracking caught operational exceptions.

        This provides visibility into operational errors that are caught and
        handled but should still be surfaced for observability (fail-fast principle).

        The counter is labeled with:
        - component: Which component caught the exception (health, acp, engine)
        - operation: What operation was being attempted
        - exception_type: The exception class name
        - failure_mode_id: FMEA failure mode if applicable
        - guru_code: Guru Meditation code if applicable
        """
        if not self._meter:
            return

        self._exception_caught = self._meter.create_counter(
            "gaius.exception.caught",
            description="Operational exceptions caught and handled",
            unit="1",
        )

    def _create_operation_instruments(self) -> None:
        """Create operation monitoring instruments.

        These metrics enable monitoring of long-running operations and
        replace hard timeouts with statistical anomaly detection.

        Metric meanings:
        - operation_duration: Histogram of operation durations by type
        - operation_heartbeat: Counter of heartbeats emitted (liveness signals)
        - operation_anomaly: Counter of anomalies detected (Z > threshold)
        """
        if not self._meter:
            return

        self._operation_duration = self._meter.create_histogram(
            "gaius.operation.duration",
            description="Operation duration in seconds by type",
            unit="s",
        )
        self._operation_heartbeat = self._meter.create_counter(
            "gaius.operation.heartbeat",
            description="Heartbeats emitted during long operations",
            unit="1",
        )
        self._operation_anomaly = self._meter.create_counter(
            "gaius.operation.anomaly",
            description="Anomalous operation durations detected (Z > threshold)",
            unit="1",
        )

    def _create_pipeline_instruments(self) -> None:
        """Create landing page pipeline instruments.

        Tracks article curation and card publishing pipeline metrics:
        - Task duration histogram (by task_type)
        - Task success/failure counters (by task_type)
        - Cards published counter
        - Articles curated counter
        - Pending cards gauge (backlog)
        """
        if not self._meter:
            return

        self._pipeline_task_duration = self._meter.create_histogram(
            "gaius.pipeline.task_duration",
            description="Pipeline task execution duration in milliseconds",
            unit="ms",
        )
        self._pipeline_task_success = self._meter.create_counter(
            "gaius.pipeline.task_success",
            description="Successful pipeline task completions",
            unit="1",
        )
        self._pipeline_task_failure = self._meter.create_counter(
            "gaius.pipeline.task_failure",
            description="Failed pipeline task completions",
            unit="1",
        )
        self._pipeline_cards_published = self._meter.create_counter(
            "gaius.pipeline.cards_published",
            description="Total cards published to landing page",
            unit="1",
        )
        self._pipeline_articles_curated = self._meter.create_counter(
            "gaius.pipeline.articles_curated",
            description="Total article curations completed",
            unit="1",
        )
        self._pipeline_pending_cards = self._meter.create_gauge(
            "gaius.pipeline.pending_cards",
            description="Current pending cards in backlog",
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
        tokens_in: int = 0,
        tokens_out: int = 0,
        success: bool = True,
        technique: str = "",
        provider: str = "",
    ) -> None:
        """Record an inference request.

        Args:
            model: Model/endpoint name
            latency_ms: Request latency in ms
            tokens: Tokens processed (input + output) - legacy, use tokens_in/out
            tokens_in: Input tokens (prompt)
            tokens_out: Output tokens (completion)
            success: Whether request succeeded
            technique: optillm technique if used
            provider: Provider name (cerebras, xai, local) for filtering
        """
        if not self._inference_count:
            if not self._initialized:
                logger.warning(
                    f"record_inference called but _inference_count is None "
                    f"(initialized={self._initialized}, model={model})"
                )
            return

        attrs = {"model": model}
        if technique:
            attrs["technique"] = technique
        if provider:
            attrs["provider"] = provider

        # Calculate total if only separate counts provided
        total_tokens = tokens if tokens > 0 else (tokens_in + tokens_out)

        logger.info(
            f"Recording inference metric: provider={provider}, model={model}, "
            f"latency={latency_ms}ms, tokens_in={tokens_in}, tokens_out={tokens_out}"
        )
        self._inference_count.add(1, attrs)
        self._inference_latency.record(latency_ms, attrs)

        # Record both total and separate token counts
        if total_tokens > 0:
            self._inference_tokens.add(total_tokens, attrs)
        if tokens_in > 0 and self._inference_tokens_in:
            self._inference_tokens_in.add(tokens_in, attrs)
        if tokens_out > 0 and self._inference_tokens_out:
            self._inference_tokens_out.add(tokens_out, attrs)

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

    def record_incident_change(self, delta: int, status: str = "active") -> None:
        """Record incident count change for Observe panel.

        Used to track currently active incidents. An incident remains "active"
        even if it transitions to manual_required (GitHub issue opened) until
        the issue is closed.

        Args:
            delta: Change in incident count (+1 for new, -1 for resolved)
            status: Current incident status (active, recovering, manual_required)
        """
        if not self._incidents_active:
            return
        self._incidents_active.add(delta, {"status": status})

    def record_error(self, error_type: str = "general") -> None:
        """Record a general error.

        Args:
            error_type: Type of error
        """
        if not self._error_total:
            return
        self._error_total.add(1, {"type": error_type})

    def record_exception_caught(
        self,
        component: str,
        operation: str,
        exception_type: str,
        failure_mode_id: str | None = None,
        guru_code: str | None = None,
    ) -> None:
        """Record an exception that was caught and handled.

        This is for operational visibility following fail-fast principles.
        Even when exceptions are handled gracefully, they should be recorded
        for observability so silent failures don't accumulate.

        Args:
            component: Component catching the exception (health, acp, engine)
            operation: Operation being attempted (remediation, escalation, etc.)
            exception_type: Exception class name (e.g., "RepositoryNotAllowedError")
            failure_mode_id: FMEA failure mode ID if applicable (e.g., "GPU_001")
            guru_code: Guru Meditation code (e.g., "#ACP.SEC.00000002.NOTALLOWED")
        """
        if not self._exception_caught:
            return

        attrs = {
            "component": component,
            "operation": operation,
            "exception_type": exception_type,
        }
        if failure_mode_id:
            attrs["failure_mode_id"] = failure_mode_id
        if guru_code:
            attrs["guru_code"] = guru_code

        self._exception_caught.add(1, attrs)
        logger.debug(
            f"Recorded exception: component={component} operation={operation} "
            f"type={exception_type} guru={guru_code}"
        )

    def record_operation_duration(
        self,
        operation: str,
        duration_s: float,
        endpoint: str = "",
    ) -> None:
        """Record an operation's duration.

        Args:
            operation: Operation type (e.g., "gpu_allocation", "llm_inference")
            duration_s: Duration in seconds
            endpoint: Optional endpoint context
        """
        if not self._operation_duration:
            return

        attrs = {"operation": operation}
        if endpoint:
            attrs["endpoint"] = endpoint

        self._operation_duration.record(duration_s, attrs)

    def record_heartbeat(
        self,
        operation: str,
        endpoint: str = "",
        elapsed_s: float = 0.0,
    ) -> None:
        """Record a heartbeat emission.

        Args:
            operation: Operation type
            endpoint: Optional endpoint context
            elapsed_s: Time elapsed since operation start
        """
        if not self._operation_heartbeat:
            return

        attrs = {"operation": operation}
        if endpoint:
            attrs["endpoint"] = endpoint

        self._operation_heartbeat.add(1, attrs)

    def record_operation_anomaly(
        self,
        operation: str,
        z_score: float,
        duration_s: float,
        endpoint: str = "",
    ) -> None:
        """Record an operation anomaly detection.

        Args:
            operation: Operation type
            z_score: Z-score (standard deviations from mean)
            duration_s: Actual duration
            endpoint: Optional endpoint context
        """
        if not self._operation_anomaly:
            return

        attrs = {
            "operation": operation,
            "z_score_bucket": _z_score_bucket(z_score),
        }
        if endpoint:
            attrs["endpoint"] = endpoint

        self._operation_anomaly.add(1, attrs)
        logger.warning(
            f"Operation anomaly: operation={operation} endpoint={endpoint} "
            f"duration={duration_s:.1f}s Z={z_score:.2f}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pipeline Recording Methods
    # ─────────────────────────────────────────────────────────────────────────

    def record_pipeline_task_completion(
        self,
        task_type: str,
        success: bool,
        duration_ms: float,
        items_processed: int = 0,
    ) -> None:
        """Record a pipeline task completion.

        Args:
            task_type: Type of task (article_curate, publish_cards)
            success: Whether the task succeeded
            duration_ms: Task execution duration in milliseconds
            items_processed: Number of items processed (cards published, etc.)
        """
        attrs = {"task_type": task_type}

        # Record duration histogram
        if self._pipeline_task_duration:
            self._pipeline_task_duration.record(duration_ms, attrs)

        # Record success/failure counter
        if success:
            if self._pipeline_task_success:
                self._pipeline_task_success.add(1, attrs)
            # Also record specific counters for curations
            if task_type == "article_curate" and self._pipeline_articles_curated:
                self._pipeline_articles_curated.add(1)
        else:
            if self._pipeline_task_failure:
                self._pipeline_task_failure.add(1, attrs)

        logger.debug(
            f"Pipeline task completed: type={task_type} success={success} "
            f"duration={duration_ms:.0f}ms items={items_processed}"
        )

    def record_cards_published(self, count: int) -> None:
        """Record cards published to landing page.

        Args:
            count: Number of cards published
        """
        if not self._pipeline_cards_published:
            return
        self._pipeline_cards_published.add(count)
        logger.debug(f"Recorded {count} cards published")

    def record_pipeline_backlog(self, pending_cards: int) -> None:
        """Record current pending cards backlog.

        Args:
            pending_cards: Current number of pending cards
        """
        if not self._pipeline_pending_cards:
            return
        self._pipeline_pending_cards.set(pending_cards)
        logger.debug(f"Pipeline backlog: {pending_cards} pending cards")

    def _create_cognition_instruments(self) -> None:
        if not self._meter:
            return
        self._cognition_tremor = self._meter.create_gauge(
            "gaius.cognition.tremor",
            description="Waterfall onset envelope (Ricci Δ, CLT, vLLM rates)",
            unit="1",
        )

    def set_cognition_tremor(self, energy: float) -> None:
        """Publish tremor 0..1 for Prometheus scrape (1s)."""
        if not self._cognition_tremor:
            return
        v = max(0.0, min(1.0, float(energy)))
        self._cognition_tremor.set(v)

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
    tokens_in: int = 0,
    tokens_out: int = 0,
    success: bool = True,
    technique: str = "",
    provider: str = "",
) -> None:
    """Record an inference request."""
    EngineMetrics.get_instance().record_inference(
        model, latency_ms, tokens, tokens_in, tokens_out, success, technique, provider
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


def record_exception_caught(
    component: str,
    operation: str,
    exception_type: str,
    failure_mode_id: str | None = None,
    guru_code: str | None = None,
) -> None:
    """Record an exception that was caught and handled.

    This provides operational visibility following fail-fast principles.
    Even when exceptions are handled gracefully, they should be recorded
    for observability so silent failures don't accumulate.

    Args:
        component: Component catching the exception (health, acp, engine)
        operation: Operation being attempted (remediation, escalation, etc.)
        exception_type: Exception class name
        failure_mode_id: FMEA failure mode ID if applicable
        guru_code: Guru Meditation code if applicable
    """
    EngineMetrics.get_instance().record_exception_caught(
        component, operation, exception_type, failure_mode_id, guru_code
    )


def record_incident_change(delta: int, status: str = "active") -> None:
    """Record incident count change for Observe panel.

    Used to track currently active incidents for observability.
    Incidents remain counted even with GitHub issues until resolved.

    Args:
        delta: Change in incident count (+1 for new, -1 for resolved)
        status: Current incident status (active, recovering, manual_required)
    """
    EngineMetrics.get_instance().record_incident_change(delta, status)


def record_pipeline_task_completion(
    task_type: str,
    success: bool,
    duration_ms: float,
    items_processed: int = 0,
) -> None:
    """Record a pipeline task completion.

    Args:
        task_type: Type of task (article_curate, publish_cards)
        success: Whether the task succeeded
        duration_ms: Task execution duration in milliseconds
        items_processed: Number of items processed (cards published, etc.)
    """
    EngineMetrics.get_instance().record_pipeline_task_completion(
        task_type, success, duration_ms, items_processed
    )


def record_cards_published(count: int) -> None:
    """Record cards published to landing page.

    Args:
        count: Number of cards published
    """
    EngineMetrics.get_instance().record_cards_published(count)


def record_pipeline_backlog(pending_cards: int) -> None:
    """Record current pending cards backlog.

    Args:
        pending_cards: Current number of pending cards
    """
    EngineMetrics.get_instance().record_pipeline_backlog(pending_cards)
