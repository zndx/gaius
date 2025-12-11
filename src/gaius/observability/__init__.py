"""Observability package for metrics collection and visualization.

This package provides:
- MetricSource abstraction for different data backends
- PrometheusSource for PromQL queries
- EngineSource for GPU/scheduler metrics via gRPC
- MetricDefinition registry for declarative metric configuration
"""

from .sources.base import MetricSource, MetricValue, MetricSeries
from .sources.prometheus import PrometheusSource
from .metrics import MetricDefinition, MetricDisplay, OBSERVE_METRICS

__all__ = [
    "MetricSource",
    "MetricValue",
    "MetricSeries",
    "PrometheusSource",
    "MetricDefinition",
    "MetricDisplay",
    "OBSERVE_METRICS",
]
