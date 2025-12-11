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
OBSERVE_METRICS: list[MetricDefinition] = [
    # --- Prometheus metrics (time series with sparklines) ---
    MetricDefinition(
        id="inference_latency_p95",
        name="Latency p95",
        source="prometheus",
        query='histogram_quantile(0.95, rate(gaius_gaius_inference_latency_bucket[5m]))',
        display=MetricDisplay.SPARKLINE,
        unit="ms",
        warning_threshold=500,
        critical_threshold=1000,
    ),
    MetricDefinition(
        id="inference_rate",
        name="Infer/min",
        source="prometheus",
        query='rate(gaius_gaius_inference_count_total[1m]) * 60',
        display=MetricDisplay.SPARKLINE,
        unit="",
        width=15,
    ),
    MetricDefinition(
        id="search_rate",
        name="Search/min",
        source="prometheus",
        query='rate(gaius_gaius_search_count_total[1m]) * 60',
        display=MetricDisplay.SPARKLINE,
        unit="",
        width=15,
    ),
    MetricDefinition(
        id="error_rate",
        name="Errors",
        source="prometheus",
        query='rate(gaius_gaius_error_total[5m]) / (rate(gaius_gaius_request_total[5m]) + 0.0001) * 100',
        display=MetricDisplay.PERCENTAGE,
        unit="%",
        warning_threshold=1,
        critical_threshold=5,
        precision=2,
    ),
    # --- Engine metrics (gauges for current state) ---
    MetricDefinition(
        id="gpu_memory_0",
        name="GPU 0 Mem",
        source="engine",
        query="gpu_memory:0",
        display=MetricDisplay.GAUGE,
        unit="%",
        warning_threshold=85,
        critical_threshold=95,
        width=12,
    ),
    MetricDefinition(
        id="gpu_memory_1",
        name="GPU 1 Mem",
        source="engine",
        query="gpu_memory:1",
        display=MetricDisplay.GAUGE,
        unit="%",
        warning_threshold=85,
        critical_threshold=95,
        width=12,
    ),
    MetricDefinition(
        id="endpoints",
        name="Endpoints",
        source="engine",
        query="endpoint_count",
        display=MetricDisplay.COUNTER,
        unit=" healthy",
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
