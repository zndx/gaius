# Monitoring

Operational monitoring combines CLI health checks, GPU status tracking, Prometheus metrics, and Metabase dashboards. The Health Observer daemon provides continuous background monitoring with FMEA-scored incident tracking.

## Quick Status

```bash
# Overall health (all service checks)
uv run gaius-cli --cmd "/health" --format json

# GPU and endpoint status (6x RTX 4090)
uv run gaius-cli --cmd "/gpu status" --format json

# Active incidents with RPN scores
uv run gaius-cli --cmd "/health incidents" --format json

# Prometheus metrics (inference throughput, latency)
uv run gaius-cli --cmd "/observe" --format json
```

## Monitoring Stack

| Layer | Tool | What it monitors | Access |
|-------|------|-----------------|--------|
| Health | `/health` | Service availability, gRPC connectivity | CLI/MCP |
| Endpoints | `/gpu status` | vLLM endpoints, GPU memory/temp | CLI/MCP |
| Incidents | Health Observer | Continuous FMEA-scored failure detection | Engine daemon |
| Metrics | Prometheus | Inference latency p95, throughput, error rates | PromQL (port 9090) |
| Dashboards | Metabase | Lineage, operations, KB geometry | Web UI (port 3000) |
| Telemetry | OpenTelemetry | Distributed traces, metric instrumentation | OTel Collector |

## Key Metrics

| Metric | Query Pattern | Alert Threshold |
|--------|---------------|-----------------|
| Inference latency p95 | `histogram_quantile(0.95, ...)` | > 5000ms |
| GPU utilization | FLOPS-weighted Welford mean | < 10% (underutilized) |
| Active incidents | `gaius_gaius_incidents_active` | > 0 |
| FMEA RPN scores | `gaius_gaius_fmea_rpn_score` | > 200 (escalation) |
| Pipeline backlog | `gaius_gaius_pipeline_pending_cards` | > 50 |

All rate calculations use **10-minute windows** to survive bursty workloads.

## TUI ObservePanel

The TUI's ObservePanel displays real-time metrics with 15-second refresh intervals. Sparklines show 5 minutes of history. Thresholds trigger color changes (green → yellow → red).

## See Also

- [Health Checks](./health-checks.md) — Running diagnostics
- [GPU Management](./gpu.md) — GPU operations
- [Observability](../architecture/observability.md) — Architecture details
