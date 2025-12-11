# OTel Collector + Prometheus in devenv

Added OpenTelemetry Collector and Prometheus services to the `devenv up` stack for real-time observability.

## What Was Added

### devenv.nix Services

```nix
# OTel Collector - receives telemetry from all Gaius components
services.opentelemetry-collector = {
  enable = true;
  package = pkgs.opentelemetry-collector-contrib;
  settings = {
    receivers.otlp.protocols = {
      grpc.endpoint = "0.0.0.0:4317";
      http.endpoint = "0.0.0.0:4318";
    };
    processors.batch = { timeout = "5s"; send_batch_size = 1000; };
    exporters = {
      prometheus = { endpoint = "0.0.0.0:8889"; namespace = "gaius"; };
      debug.verbosity = "basic";
    };
    service.pipelines = {
      traces = { receivers = ["otlp"]; processors = ["batch"]; exporters = ["debug"]; };
      metrics = { receivers = ["otlp"]; processors = ["batch"]; exporters = ["prometheus"]; };
    };
  };
};

# Prometheus - scrapes metrics from OTel Collector
services.prometheus = {
  enable = true;
  port = 9090;
  extraArgs = "--web.listen-address=127.0.0.1:9090";
  storage.retentionTime = "15d";
  scrapeConfigs = [{
    job_name = "otel-collector";
    static_configs = [{ targets = ["localhost:8889"]; }];
  }];
};
```

### .env Update

Changed from disabled-by-default to enabled:
```bash
# OpenTelemetry - enabled by default (collector runs via devenv up)
# Set OTEL_SDK_DISABLED=true to disable telemetry when not using devenv
# OTEL_SDK_DISABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

## Port Assignments

| Service | Port | Purpose |
|---------|------|---------|
| OTel Collector gRPC | 4317 | OTLP receiver for traces/metrics |
| OTel Collector HTTP | 4318 | OTLP HTTP receiver |
| OTel Collector metrics | 8889 | Prometheus scrape endpoint |
| Prometheus | 9090 | Web UI and query API |

## Testing

```bash
# Start the stack
devenv up

# Verify collector is receiving metrics
curl http://localhost:8889/metrics | grep gaius

# Query Prometheus
curl 'http://localhost:9090/api/v1/query?query=up'

# View Prometheus UI
open http://localhost:9090
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Gaius Components                                   │
│  gaius-cli, gaius-tui, gaius-mcp, engine, worker                    │
│                           │                                           │
│                    OTLP gRPC :4317                                    │
│                           ▼                                           │
│            ┌─────────────────────────────┐                           │
│            │    OTel Collector           │                           │
│            │  • batch processor          │                           │
│            │  • prometheus exporter :8889│                           │
│            │  • debug exporter (traces)  │                           │
│            └──────────────┬──────────────┘                           │
│                           │ scrape                                   │
│                           ▼                                           │
│            ┌─────────────────────────────┐                           │
│            │    Prometheus :9090         │                           │
│            │  • 15d retention            │                           │
│            │  • Web UI + API             │                           │
│            └─────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Complementary to SDK Filtering

This setup works alongside the SDK-level SpanProcessor filtering researched earlier:

- **SDK filtering**: In-process, zero network overhead, for `/health watch`
- **Collector**: Always-on pipeline processing, export to Prometheus
- **Prometheus**: Time-series storage, queries, future alerting

Both layers can operate simultaneously without redundancy.
