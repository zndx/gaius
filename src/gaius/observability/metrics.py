"""Metric definitions registry.

Declarative configuration for ObservePanel metrics:
- MetricDisplay: How to render the metric (sparkline, gauge, counter)
- MetricDefinition: Complete metric specification
- OBSERVE_METRICS: Default metrics for the ObservePanel
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MetricDisplay(Enum):
    """How to render a metric in the ObservePanel."""

    SPARKLINE = "sparkline"  # Time series as Unicode blocks
    GAUGE = "gauge"  # Horizontal bar with fill percentage
    COUNTER = "counter"  # Simple numeric value
    PERCENTAGE = "percentage"  # Value with % suffix


@dataclass
class MetricDefinition:
    """Declarative metric specification.

    Defines how a metric is fetched, displayed, and colored.

    Attributes:
        id: Unique identifier for caching
        name: Display name (left-aligned label)
        source: Data source type ("prometheus" or "engine")
        query: Backend-specific query string
        display: How to render (SPARKLINE, GAUGE, COUNTER)
        unit: Units to display after value (ms, %, req/s, etc.)
        warning_threshold: Value at which to show yellow
        critical_threshold: Value at which to show red
        threshold_direction: "above" (default) or "below"
        width: Width for sparkline/gauge rendering
        precision: Decimal places for value display
        max_value: Maximum value for GAUGE display (default 100)
    """

    id: str
    name: str
    source: str  # "prometheus" or "engine"
    query: str
    display: MetricDisplay
    unit: str = ""
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    threshold_direction: str = "above"  # "above" or "below"
    width: int = 20
    precision: int = 1
    max_value: float = 100.0  # For GAUGE display

    def get_color(self, value: Optional[float]) -> str:
        """Determine color based on value and thresholds.

        Args:
            value: Current metric value

        Returns:
            Color name: "green", "yellow", or "red"
        """
        if value is None:
            return "dim"

        if self.threshold_direction == "above":
            if self.critical_threshold is not None and value >= self.critical_threshold:
                return "red"
            if self.warning_threshold is not None and value >= self.warning_threshold:
                return "yellow"
        else:  # "below"
            if self.critical_threshold is not None and value <= self.critical_threshold:
                return "red"
            if self.warning_threshold is not None and value <= self.warning_threshold:
                return "yellow"

        return "green"


# Default metrics for ObservePanel
# Note: Prometheus metrics have "gaius_gaius_" prefix:
#   - "gaius_" from OTel Collector namespace config
#   - "gaius." from SDK metric naming (becomes "gaius_" after export)
#
# Windowed Stats Philosophy (Flink-inspired):
# - Use 10-minute windows for rate calculations to survive bursty workloads
# - Sparklines show 5-minute history at 15-second resolution
# - Current value shows meaningful aggregate rather than instantaneous zero
OBSERVE_METRICS: list[MetricDefinition] = [
    # --- Prometheus metrics (time series with sparklines) ---
    # Note: Metric names follow the pattern gaius_gaius_<name>_<unit> from OTel export
    MetricDefinition(
        id="inference_latency_p95",
        name="Latency p95",
        source="prometheus",
        # Sum across all models, keeping only the 'le' bucket label for histogram_quantile
        # 10-minute window for bursty workloads like ambient reasoning
        query='histogram_quantile(0.95, sum by (le) (rate(gaius_gaius_inference_latency_milliseconds_bucket[10m])))',
        display=MetricDisplay.GAUGE,
        unit="ms",
        warning_threshold=500,
        critical_threshold=1000,
        max_value=2000.0,  # 2s max for gauge scale
        width=12,
        precision=0,
    ),
    MetricDefinition(
        id="inference_rate",
        name="Infer/hr",
        source="prometheus",
        # 10-minute windowed rate extrapolated to hourly
        # This keeps the metric hydrated even during quiet periods
        query='sum(rate(gaius_gaius_inference_count_total[10m])) * 3600',
        display=MetricDisplay.SPARKLINE,
        unit="",
        width=15,
    ),
    MetricDefinition(
        id="tokens_rate",
        name="Tokens/hr",
        source="prometheus",
        # 10-minute windowed rate extrapolated to hourly
        query='sum(rate(gaius_gaius_inference_tokens_total[10m])) * 3600',
        display=MetricDisplay.SPARKLINE,
        unit="",
        width=15,
    ),
    MetricDefinition(
        id="tokens_in_rate",
        name="Tok in/hr",
        source="prometheus",
        query='sum(rate(gaius_gaius_inference_tokens_in_total[10m])) * 3600',
        display=MetricDisplay.SPARKLINE,
        unit="",
        width=15,
    ),
    MetricDefinition(
        id="tokens_out_rate",
        name="Tok out/hr",
        source="prometheus",
        query='sum(rate(gaius_gaius_inference_tokens_out_total[10m])) * 3600',
        display=MetricDisplay.SPARKLINE,
        unit="",
        width=15,
    ),
    MetricDefinition(
        id="gpu_watts",
        name="GPU W",
        source="engine",
        query="signals_total_w",
        display=MetricDisplay.GAUGE,
        unit="W",
        width=12,
        precision=0,
        max_value=2700.0,
    ),
    MetricDefinition(
        id="gpu_inferring_watts",
        name="Infer W",
        source="engine",
        query="signals_inferring_w",
        display=MetricDisplay.GAUGE,
        unit="W",
        width=12,
        precision=0,
        max_value=1800.0,
    ),
    # Note: Search/min metric available but not displayed in panel
    # query='rate(gaius_gaius_search_count_total[10m]) * 60'
    MetricDefinition(
        id="error_rate",
        name="LLM Errors",
        source="prometheus",
        # 10-minute windowed error rate for stability
        query='rate(gaius_gaius_error_total[10m]) / (rate(gaius_gaius_request_total[10m]) + 0.0001) * 100',
        display=MetricDisplay.PERCENTAGE,
        unit="%",
        warning_threshold=1,
        critical_threshold=5,
        precision=2,
    ),
    # --- Operational Errors (fail-fast visibility) ---
    # Tracks caught operational exceptions that should be surfaced for observability.
    # Separate from "Errors" which tracks LLM inference error rate.
    # Shows count of operational failures (GitHub issues, ACP escalation, RCA, etc.)
    MetricDefinition(
        id="ops_errors",
        name="Ops Errors",
        source="prometheus",
        query='sum(increase(gaius_gaius_exception_caught_total[10m])) or vector(0)',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=1,
        critical_threshold=5,
        precision=0,
    ),
    # --- GPU FLOPS Utilization (Prometheus via OTel) ---
    # FLOPS-weighted GPU utilization across all GPUs using Welford streaming mean.
    # Shows actual compute load relative to theoretical peak FLOPS for 6x RTX 4090s.
    # - Near 0% when idle or during changeover
    # - High % when inference is active
    # - 100% when all GPUs under full load (e.g., TP=2, PP=3 with active inference)
    MetricDefinition(
        id="gpu_flops_utilization",
        name="Compute",
        source="prometheus",
        query="gaius_gaius_gpu_flops_utilization_percent",  # From OTel export
        display=MetricDisplay.SPARKLINE,  # Now with history!
        unit="%",
        warning_threshold=95,
        critical_threshold=99,
        threshold_direction="above",
        width=15,
        precision=0,
    ),
    MetricDefinition(
        id="evolution",
        name="Evolution",
        source="engine",
        query="evolution_cycles",
        display=MetricDisplay.COUNTER,
        unit=" cycles",
        precision=0,
    ),
    # --- Healing metrics (self-healing observability) ---
    # These use gaius_gaius_healing_* metrics from healing_metrics.py or engine/metrics.py
    # Active incidents count - includes incidents with open GitHub issues
    MetricDefinition(
        id="active_incidents",
        name="Incidents",
        source="prometheus",
        query='sum(gaius_gaius_incidents_active) or vector(0)',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=1,
        critical_threshold=3,
        precision=0,
    ),
    MetricDefinition(
        id="healing_escalations",
        name="Escalations",
        source="prometheus",
        query='sum(increase(gaius_gaius_healing_escalations_total[1h]))',
        display=MetricDisplay.COUNTER,
        warning_threshold=3,
        critical_threshold=5,
        precision=0,
    ),
    # FMEA metrics - these need to be exported from the engine when RPN is calculated
    # For now, show 0 if no data
    MetricDefinition(
        id="fmea_high_rpn",
        name="High RPN",
        source="prometheus",
        query='count(gaius_gaius_fmea_rpn_score > 200) or vector(0)',
        display=MetricDisplay.COUNTER,
        warning_threshold=1,
        critical_threshold=3,
        precision=0,
    ),
    # --- Landing Page Pipeline Metrics ---
    # Cards published per day (expected: ~6/day at current 4x schedule)
    MetricDefinition(
        id="cards_per_day",
        name="Cards/day",
        source="prometheus",
        query='increase(gaius_gaius_pipeline_cards_published_total[24h])',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=3,  # Below expected throughput
        threshold_direction="below",
        precision=0,
    ),
    # Curations per week (expected: ~4-5/week at 36h cadence)
    MetricDefinition(
        id="curations_per_week",
        name="Curate/wk",
        source="prometheus",
        query='increase(gaius_gaius_pipeline_articles_curated_total[7d])',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=2,  # Below expected throughput
        threshold_direction="below",
        precision=0,
    ),
    # Minimum daily cards in backlog (tune if approaching 0)
    MetricDefinition(
        id="min_daily_backlog",
        name="Min backlog",
        source="prometheus",
        query='min_over_time(gaius_gaius_pipeline_pending_cards[24h])',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=5,  # Warn if backlog gets low
        critical_threshold=0,  # Critical if empty
        threshold_direction="below",
        precision=0,
    ),
    # Current pending cards gauge
    MetricDefinition(
        id="pending_cards",
        name="Backlog",
        source="prometheus",
        query='gaius_gaius_pipeline_pending_cards',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=5,
        critical_threshold=0,
        threshold_direction="below",
        precision=0,
    ),
    # Pipeline task failures (zero tolerance)
    MetricDefinition(
        id="pipeline_failures",
        name="Pipe Fail",
        source="prometheus",
        query='sum(increase(gaius_gaius_pipeline_task_failure_total[24h])) or vector(0)',
        display=MetricDisplay.COUNTER,
        unit="",
        warning_threshold=1,  # ANY failure = warning
        critical_threshold=3,
        precision=0,
    ),
    # Error attribution - % of pipeline failures from article_curate
    MetricDefinition(
        id="curate_error_pct",
        name="Curate Err%",
        source="prometheus",
        query='(sum(gaius_gaius_pipeline_task_failure_total{task_type="article_curate"}) or vector(0)) / (sum(gaius_gaius_pipeline_task_failure_total) + 0.0001) * 100',
        display=MetricDisplay.PERCENTAGE,
        unit="%",
        precision=0,
    ),
    # Error attribution - % of pipeline failures from publish_cards
    MetricDefinition(
        id="publish_error_pct",
        name="Publish Err%",
        source="prometheus",
        query='(sum(gaius_gaius_pipeline_task_failure_total{task_type="publish_cards"}) or vector(0)) / (sum(gaius_gaius_pipeline_task_failure_total) + 0.0001) * 100',
        display=MetricDisplay.PERCENTAGE,
        unit="%",
        precision=0,
    ),
]


def get_metrics_by_source(source: str) -> list[MetricDefinition]:
    """Get metrics filtered by source type.

    Args:
        source: "prometheus" or "engine"

    Returns:
        List of MetricDefinition for that source
    """
    return [m for m in OBSERVE_METRICS if m.source == source]


def get_metric_by_id(metric_id: str) -> Optional[MetricDefinition]:
    """Get a specific metric by ID.

    Args:
        metric_id: Unique metric identifier

    Returns:
        MetricDefinition or None if not found
    """
    for m in OBSERVE_METRICS:
        if m.id == metric_id:
            return m
    return None
