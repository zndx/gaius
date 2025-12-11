"""Base abstractions for metric sources.

This module defines the core interfaces for metric data:
- MetricValue: A single data point with timestamp and labels
- MetricSeries: A time series of values for sparkline rendering
- MetricSource: Abstract base class for metric backends
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence


@dataclass
class MetricValue:
    """Single metric data point."""

    value: float
    timestamp: datetime
    labels: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"MetricValue({self.value:.2f} @ {self.timestamp.isoformat()})"


@dataclass
class MetricSeries:
    """Time series of metric values.

    Provides convenient accessors for rendering:
    - current: Most recent value
    - sparkline_data: List of floats for sparkline rendering
    """

    name: str
    values: list[MetricValue]
    unit: str = ""
    description: str = ""

    @property
    def current(self) -> Optional[float]:
        """Most recent value, or None if empty."""
        return self.values[-1].value if self.values else None

    @property
    def sparkline_data(self) -> list[float]:
        """Extract values suitable for sparkline rendering."""
        return [v.value for v in self.values]

    @property
    def min_value(self) -> Optional[float]:
        """Minimum value in series."""
        return min(v.value for v in self.values) if self.values else None

    @property
    def max_value(self) -> Optional[float]:
        """Maximum value in series."""
        return max(v.value for v in self.values) if self.values else None

    @property
    def avg_value(self) -> Optional[float]:
        """Average value in series."""
        if not self.values:
            return None
        return sum(v.value for v in self.values) / len(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __repr__(self) -> str:
        current = f"{self.current:.2f}" if self.current is not None else "N/A"
        return f"MetricSeries({self.name}, {len(self)} points, current={current})"


class MetricSource(ABC):
    """Abstract base class for metric data sources.

    Implementations provide access to different metric backends:
    - PrometheusSource: PromQL queries against Prometheus HTTP API
    - EngineSource: GPU/scheduler metrics via gRPC proxies

    All methods are async to support non-blocking I/O.
    """

    @abstractmethod
    async def query_instant(self, query: str) -> Optional[MetricValue]:
        """Query the current value of a metric.

        Args:
            query: Backend-specific query (e.g., PromQL for Prometheus)

        Returns:
            Current value, or None if unavailable
        """
        pass

    @abstractmethod
    async def query_range(
        self,
        query: str,
        duration_seconds: int = 300,
        step_seconds: int = 15,
    ) -> MetricSeries:
        """Query metric values over a time range.

        Args:
            query: Backend-specific query
            duration_seconds: How far back to query (default 5 minutes)
            step_seconds: Resolution between data points (default 15s)

        Returns:
            MetricSeries with historical values for sparklines
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the metric source is available.

        Returns:
            True if source is reachable and healthy
        """
        pass

    async def close(self) -> None:
        """Clean up resources (optional override)."""
        pass
