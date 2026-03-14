# OpenTelemetry

Gaius uses the OpenTelemetry SDK for distributed tracing and metric instrumentation. The engine centralizes all OTel export through `EngineMetrics`, ensuring a single source of truth for operational telemetry.

## Instrumentation

The `EngineMetrics` singleton (initialized at engine startup) creates OTel instruments:

```python
from gaius.engine.metrics import EngineMetrics

metrics = EngineMetrics.get_instance()
metrics.record_inference(model="reasoning", latency_ms=150, tokens=500)
metrics.record_gpu_memory(gpu_id=0, used_mb=12000, total_mb=24000)
metrics.record_healing_attempt(endpoint="reasoning", tier=0, success=True)
```

### Metric Categories

| Category | Instruments | Type |
|----------|-------------|------|
| Inference | `inference_count`, `inference_latency`, `inference_tokens` | Counter, Histogram |
| GPU | `gpu_memory_used`, `gpu_utilization`, `gpu_flops_utilization` | Gauge (observable callbacks) |
| Endpoints | `endpoint_healthy`, `endpoint_requests` | Gauge, Counter |
| Healing | `healing_attempts`, `healing_escalations`, `incidents_active` | Counter, Gauge |
| Pipeline | `pipeline_cards_published`, `pipeline_pending_cards` | Counter, Gauge |
| Errors | `error_total`, `exception_caught_total` | Counter |

## Metric Naming

Metrics follow a double-prefix convention due to OTel Collector namespace configuration:

```
gaius_gaius_<metric_name>_<unit>
```

The first `gaius_` comes from the OTel Collector namespace config; the second from SDK metric naming (`gaius.` becomes `gaius_` after export). PromQL queries in the `OBSERVE_METRICS` registry use this full prefix.

## Export Pipeline

```
EngineMetrics --> OTel SDK --> OTLP Exporter --> OTel Collector --> Prometheus
```

The OTel Collector runs as a sidecar, receiving OTLP and remoting to Prometheus via the Prometheus remote-write or scrape endpoint. GPU metrics use observable callbacks that are invoked on each collection cycle.

## Makespan Tracing

For long-running operations (evolution cycles, research flows), Gaius uses makespan tracing: a parent span covers the entire operation, with child spans for each phase. This enables latency attribution across multi-step workflows without excessive span cardinality.

## Source

Engine metrics: `src/gaius/engine/metrics.py`. Observability sources: `src/gaius/observability/sources/`.
