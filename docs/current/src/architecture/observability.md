# Observability

Gaius uses a three-layer observability stack: OpenTelemetry for instrumentation, Prometheus for time-series storage, and Metabase for self-service analytics dashboards.

## Architecture

The observability pipeline separates **emission** (application code → OTel SDK → Collector → Prometheus) from **consumption** (Prometheus → `PrometheusSource` → TUI/CLI):

```
Application Code → OTel SDK → OTLP Exporter → OTel Collector → Prometheus
                                                                    |
                                            PrometheusSource ← PromQL queries
                                                    |
                                        ObservePanel (TUI) / CLI /observe
```

The engine is the single source of truth for metric export. All clients (CLI, TUI, MCP) route metrics through gRPC, which exports via OpenTelemetry to the Collector. Entry point identification tags traces with the originating service (`gaius-tui`, `gaius-cli`, `gaius-mcp`, `gaius-engine`, `gaius-worker`).

## Components

| Layer | Technology | Purpose |
|-------|-----------|---------|
| [OpenTelemetry](./otel.md) | OTel SDK + Collector | Distributed tracing, metric instrumentation |
| [Prometheus](./prometheus.md) | PromQL, time-series DB | Metric storage, alerting, range queries |
| [Metabase](./metabase.md) | SQL analytics platform | Dashboards connected to PostgreSQL |

## MetricSource Protocol

All metric backends implement the `MetricSource` protocol with two operations: `query()` for point-in-time values and `query_range()` for time series. The `PrometheusSource` implementation translates to PromQL queries over HTTP.

## Metric Definitions

The `OBSERVE_METRICS` registry defines declarative metric configurations:

| Category | Metrics | Source |
|----------|---------|--------|
| GPU | Memory used (GB), utilization (%), temperature | DCGM/pynvml via Prometheus |
| Inference | Latency p95 (ms), throughput (req/s), error rate | Engine OTel SDK |
| Health | Active incidents, escalations, FMEA scores | Health Observer |
| Pipeline | Cards/day, backlog depth, evolution cycles | Engine services |

Each `MetricDefinition` specifies a PromQL query, display format (sparkline, gauge, counter, percentage), unit conversion, and warning/critical thresholds with directional logic (above or below).

## ObservePanel

The TUI's `ObservePanel` displays real-time metrics with 15-second refresh intervals. Sparklines show 5 minutes of history at 15-second resolution. Thresholds trigger color changes (green → yellow → red).

## Design Decisions

- **10-minute windowed rates** (Flink-inspired) survive bursty workloads like ambient reasoning cycles that generate inference spikes
- **Fail Open** for status display: unknown metric states are surfaced for investigation, not filtered away
- **Emission/consumption separation**: `core/telemetry.py` handles OTel SDK instrumentation; this module handles querying and display. They share no code.

See each sub-chapter for implementation details.
