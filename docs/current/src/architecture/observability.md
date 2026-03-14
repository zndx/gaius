# Observability

Gaius uses a three-layer observability stack: OpenTelemetry for instrumentation, Prometheus for time-series storage, and Metabase for self-service analytics dashboards.

## Architecture

```
CLI/TUI/MCP --> gRPC --> Engine --> OTel Collector --> Prometheus
                         ^^^^^^                          |
                    metrics exported here          Metabase (dashboards)
```

The engine is the single source of truth for metric export. All clients (CLI, TUI, MCP) route metrics through the gRPC engine, which exports via OpenTelemetry SDK to the OTel Collector. The collector forwards to Prometheus for scraping.

## Components

| Layer | Technology | Purpose |
|-------|-----------|---------|
| [OpenTelemetry](./otel.md) | OTel SDK + Collector | Distributed tracing, metric instrumentation |
| [Prometheus](./prometheus.md) | PromQL, time-series DB | Metric storage, alerting, range queries |
| [Metabase](./metabase.md) | SQL analytics platform | Dashboards connected to PostgreSQL |

## ObservePanel

The TUI's `ObservePanel` displays real-time metrics using declarative `MetricDefinition` objects. Each definition specifies:

- **Source**: `prometheus` (PromQL query) or `engine` (gRPC proxy)
- **Display**: sparkline, gauge, counter, or percentage
- **Thresholds**: warning/critical levels with directional logic (above or below)

Metric categories include inference (latency, throughput, errors), GPU compute (FLOPS utilization), health (active incidents, escalations, FMEA scores), and pipeline operations (cards/day, backlog depth).

## Design Philosophy

Metrics use **10-minute windowed rates** (Flink-inspired) to survive bursty workloads like ambient reasoning. Sparklines show 5 minutes of history at 15-second resolution. The **Fail Open** principle applies: unknown states are surfaced for investigation rather than filtered away.

See each sub-chapter for implementation details.
