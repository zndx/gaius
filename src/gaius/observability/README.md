# Gaius Observability

Metrics collection and visualization for operational monitoring. Provides a unified abstraction over multiple data backends including Prometheus and the gRPC engine.

## Architecture

```mermaid
graph TB
    subgraph "Data Sources"
        PROM[Prometheus]
        ENGINE[gaius-engine gRPC]
        NVML[pynvml]
    end

    subgraph "Observability Layer"
        SRC[MetricSource Protocol]
        PS[PrometheusSource]
        ES[EngineSource]
    end

    subgraph "Display"
        TUI[ObservePanel Widget]
        CLI[/observe Command]
    end

    PROM --> PS
    ENGINE --> ES
    NVML --> ES
    PS --> SRC
    ES --> SRC
    SRC --> TUI
    SRC --> CLI
```

## Module Structure

```
observability/
├── __init__.py           # Module exports
├── metrics.py            # MetricDefinition, OBSERVE_METRICS registry
└── sources/
    ├── base.py           # MetricSource protocol, MetricValue
    └── prometheus.py     # PrometheusSource implementation
```

## Metric Source Protocol

All metric backends implement the `MetricSource` protocol:

```python
class MetricSource(Protocol):
    """Abstract metric data source."""

    async def query(
        self,
        metric_name: str,
        labels: dict[str, str] | None = None,
    ) -> MetricValue:
        """Query a single metric value."""
        ...

    async def query_range(
        self,
        metric_name: str,
        start: datetime,
        end: datetime,
        step: timedelta,
        labels: dict[str, str] | None = None,
    ) -> MetricSeries:
        """Query metric values over time range."""
        ...
```

## Data Types

### MetricValue

```python
@dataclass
class MetricValue:
    timestamp: datetime
    value: float
    labels: dict[str, str] = field(default_factory=dict)
```

### MetricSeries

```python
@dataclass
class MetricSeries:
    metric_name: str
    values: list[MetricValue]
    labels: dict[str, str] = field(default_factory=dict)
```

## Prometheus Source

Query metrics from Prometheus:

```python
from gaius.observability import PrometheusSource

source = PrometheusSource(url="http://localhost:9090")

# Single value
gpu_memory = await source.query(
    "nvidia_gpu_memory_used_bytes",
    labels={"gpu": "0"},
)
print(f"GPU 0 memory: {gpu_memory.value / 1e9:.1f} GB")

# Time series
series = await source.query_range(
    "nvidia_gpu_utilization_ratio",
    start=datetime.now() - timedelta(hours=1),
    end=datetime.now(),
    step=timedelta(minutes=1),
)

for point in series.values:
    print(f"{point.timestamp}: {point.value:.1%}")
```

## Metric Definitions

Declarative metric configuration:

```python
from gaius.observability import MetricDefinition, MetricDisplay

OBSERVE_METRICS = [
    MetricDefinition(
        name="gpu_memory",
        query="nvidia_gpu_memory_used_bytes",
        display=MetricDisplay(
            label="GPU Memory",
            unit="GB",
            format=".1f",
            transform=lambda v: v / 1e9,
        ),
    ),
    MetricDefinition(
        name="gpu_utilization",
        query="nvidia_gpu_utilization_ratio",
        display=MetricDisplay(
            label="GPU Util",
            unit="%",
            format=".0%",
        ),
    ),
    MetricDefinition(
        name="inference_latency",
        query="gaius_inference_duration_seconds",
        display=MetricDisplay(
            label="Latency",
            unit="ms",
            format=".0f",
            transform=lambda v: v * 1000,
        ),
    ),
]
```

### MetricDefinition

```python
@dataclass
class MetricDefinition:
    name: str              # Internal identifier
    query: str             # PromQL or metric name
    display: MetricDisplay # Display configuration
    labels: dict[str, str] = field(default_factory=dict)
    source: str = "prometheus"  # "prometheus" or "engine"
```

### MetricDisplay

```python
@dataclass
class MetricDisplay:
    label: str             # Human-readable name
    unit: str              # Unit suffix
    format: str = ".2f"    # Python format spec
    transform: Callable[[float], float] | None = None
    thresholds: list[tuple[float, str]] | None = None  # (value, color)
```

## Usage in TUI

The ObservePanel widget uses metric definitions:

```python
from gaius.observability import OBSERVE_METRICS, PrometheusSource

source = PrometheusSource()

for metric_def in OBSERVE_METRICS:
    value = await source.query(metric_def.query, metric_def.labels)

    # Apply transform
    display_value = value.value
    if metric_def.display.transform:
        display_value = metric_def.display.transform(display_value)

    # Format
    formatted = f"{display_value:{metric_def.display.format}} {metric_def.display.unit}"
    print(f"{metric_def.display.label}: {formatted}")
```

## Configuration

```python
@dataclass
class ObservabilityConfig:
    prometheus_url: str = "http://localhost:9090"
    scrape_interval: timedelta = timedelta(seconds=15)
    retention_hours: int = 24
```

Environment variables:
- `PROMETHEUS_URL`: Prometheus server URL

## Standard Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| `nvidia_gpu_memory_used_bytes` | DCGM/pynvml | GPU VRAM usage |
| `nvidia_gpu_utilization_ratio` | DCGM/pynvml | GPU compute utilization |
| `nvidia_gpu_temperature` | DCGM/pynvml | GPU temperature |
| `gaius_inference_duration_seconds` | Engine | Inference latency |
| `gaius_scheduler_queue_depth` | Engine | Job queue size |
| `gaius_evolution_cycle_count` | Engine | Evolution cycles completed |

## See Also

- [Parent README](../README.md) — Module overview
- [Health README](../health/README.md) — Health monitoring
- [Engine README](../engine/README.md) — Metric emission
