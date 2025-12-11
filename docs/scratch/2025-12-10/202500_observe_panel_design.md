# Observe Panel Design

## Summary

Rename/repurpose InitPanel → ObservePanel. The bidirectional InitStream becomes the real-time data mechanism for persistent operational monitoring.

## Panel Taxonomy

| Panel | Focus | Data Source |
|-------|-------|-------------|
| **Graph** | Knowledge structure | KB embeddings, TDA |
| **Think** | Cognition streams | Thought DB, reflection |
| **Evolve** | Agent optimization | Evolution daemon, agent versions |
| **Observe** | Operational health | Prometheus via OTel Collector |

## Observe Panel Content

### Sparklines (compact time-series)
- Inference latency p50/p95/p99
- Request throughput (req/s by entry point)
- GPU memory utilization per device
- Collector pipeline throughput

### Gauges (current values)
- Active endpoints (healthy/total)
- Evolution daemon status
- Error rate (last 5m)
- Queue depth

### Layout Sketch

```
┌─ Observe ──────────────────────────────────┐
│ Latency p95 ▁▂▃▂▁▂▄▅▃▂▁  142ms            │
│ Throughput  ▃▃▄▅▆▅▄▃▃▄▅  12.3 req/s       │
│ GPU 0       ████████░░░░  67% (32/48GB)   │
│ GPU 1       ██████░░░░░░  52% (25/48GB)   │
│─────────────────────────────────────────────│
│ Endpoints   ●●●○  3/4 healthy              │
│ Evolution   ● running  cycle 847           │
│ Errors      0.2% (last 5m)                 │
│ Collector   ● 1.2k spans/s                 │
└─────────────────────────────────────────────┘
```

## Data Flow

```
Gaius Components
    │ OTLP traces/metrics
    ▼
OTel Collector (:4317)
    │ prometheus exporter
    ▼
Prometheus (:9090)
    │ PromQL queries
    ▼
ObservePanel (TUI widget)
```

## Implementation Steps

1. **Add metrics instrumentation to Gaius**
   - Counters: request_count, error_count
   - Histograms: inference_latency, command_duration
   - Gauges: active_endpoints, gpu_memory_used

2. **Create ObservePanel widget**
   - Rename InitPanel → ObservePanel
   - Keep InitStream for real-time updates
   - Add PromQL query integration

3. **Sparkline rendering**
   - Use Unicode block characters (▁▂▃▄▅▆▇█)
   - Rolling window (last 5m default)
   - Color coding (green/yellow/red thresholds)

4. **Panel cycling**
   - `g` cycles: Graph → Think → Evolve → Observe
   - Each panel maintains its own state

## Prometheus Queries

```promql
# Latency p95 (last 5m, 10s buckets)
histogram_quantile(0.95,
  rate(gaius_inference_latency_bucket[5m])
)

# Request throughput
rate(gaius_request_total[1m])

# Error rate
rate(gaius_error_total[5m]) / rate(gaius_request_total[5m])

# GPU memory (from node_exporter or DCGM)
nvidia_gpu_memory_used_bytes / nvidia_gpu_memory_total_bytes
```

## Future: Alerting Integration

ObservePanel could show active alerts from Alertmanager:
- HighLatency, LowThroughput, GPUMemoryPressure
- Visual indicator when alerts firing
