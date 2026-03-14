# Prometheus

Prometheus provides time-series metric storage and PromQL queries for the Gaius observability stack. It scrapes metrics exported by the OTel Collector and serves as the backend for the TUI's ObservePanel.

## PrometheusSource

The `PrometheusSource` client (`src/gaius/observability/sources/prometheus.py`) queries the Prometheus HTTP API:

```python
from gaius.observability import PrometheusSource

source = PrometheusSource(base_url="http://localhost:9090")

# Instant query (current value)
value = await source.query_instant(
    'histogram_quantile(0.95, sum by (le) (rate(gaius_gaius_inference_latency_milliseconds_bucket[10m])))'
)

# Range query (sparkline data)
series = await source.query_range(
    'sum(rate(gaius_gaius_inference_count_total[10m])) * 3600',
    duration_seconds=300,  # 5 minutes of history
    step_seconds=15,       # 15-second resolution
)
```

## Custom Metrics

### Inference
- `gaius_gaius_inference_latency_milliseconds` -- histogram with p95 via `histogram_quantile`
- `gaius_gaius_inference_count_total` -- counter, displayed as inferences/hour
- `gaius_gaius_inference_tokens_total` -- counter, displayed as tokens/hour
- `gaius_gaius_error_total` / `gaius_gaius_request_total` -- error rate percentage

### GPU
- `gaius_gaius_gpu_flops_utilization_percent` -- FLOPS-weighted utilization across 6x RTX 4090s using Welford streaming mean

### Health and Self-Healing
- `gaius_gaius_incidents_active` -- gauge of active incidents
- `gaius_gaius_healing_escalations_total` -- counter of ACP escalations per hour
- `gaius_gaius_fmea_rpn_score` -- FMEA Risk Priority Numbers (high RPN > 200)

### Pipeline Operations
- `gaius_gaius_pipeline_cards_published_total` -- cards published (daily)
- `gaius_gaius_pipeline_pending_cards` -- backlog gauge
- `gaius_gaius_pipeline_task_failure_total` -- failures by task type (zero tolerance)
- `gaius_gaius_exception_caught_total` -- operational errors (non-LLM)

## Windowed Rates

All rate calculations use **10-minute windows** to survive bursty workloads. This keeps metrics hydrated during quiet periods rather than dropping to zero between bursts.

## Engine Source

For metrics not available in Prometheus (GPU memory per device, scheduler queue depth, evolution cycles), the `EngineSource` queries the gRPC engine directly. These return single-point values since the engine does not retain history.

## Source

`src/gaius/observability/sources/prometheus.py`, `src/gaius/observability/sources/engine.py`, `src/gaius/observability/metrics.py`.
