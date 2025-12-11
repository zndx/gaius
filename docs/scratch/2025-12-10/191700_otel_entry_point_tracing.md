# OTel Entry Point Tracing Implementation

Implemented OpenTelemetry traces/spans to distinguish per-entry-point (CLI/MCP/TUI/Engine/Worker) command handling code paths. This aligns with Cloudera Observability platform expectations and enables proper distributed tracing across Gaius components.

## Key Design Decision: Standard OTel Environment Variables

Telemetry is **enabled by default** and controlled via standard OTel environment variables:

| Variable | Purpose | Example |
|----------|---------|---------|
| `OTEL_SDK_DISABLED=true` | Disable all telemetry | `OTEL_SDK_DISABLED=true gaius-cli` |
| `OTEL_TRACES_EXPORTER` | Set exporter type | `console` or `otlp` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | `http://localhost:4317` |

This follows OTel conventions rather than custom `GAIUS_TELEMETRY_ENABLED` flags.

## What Changed

### Core Telemetry Module (`src/gaius/core/telemetry.py`)

- Added `entry_point` parameter to `_init_telemetry()` and `init_from_config()`
- Added `_is_otel_disabled()` to check `OTEL_SDK_DISABLED` env var
- Added `get_entry_point()` helper to retrieve current entry point
- Added `traced_command()` context manager for standardized command tracing
- Removed `config.enabled` check in favor of standard env var
- Enhanced resource attributes per OTel semantic conventions:
  - `service.name`: `gaius-{tui,cli,mcp,engine,worker}`
  - `service.namespace`: `gaius`
  - `service.version`: `0.2.0`
  - `service.instance.id`: `{hostname}-{pid}`
  - `deployment.environment.name`: From `GAIUS_ENV` env var (default: `dev`)

### Entry Points Updated

| Entry Point | File | Change |
|-------------|------|--------|
| TUI | `app.py` | Added `entry_point="tui"` to `init_telemetry()` call |
| CLI | `cli.py` | Added telemetry init in `main()` with `entry_point="cli"`, wrapped `execute()` in `traced_command()` |
| MCP | `mcp_server.py` | Added telemetry init in `main()` with `entry_point="mcp"` |
| Engine | `engine/server.py` | Updated `_init_telemetry()` to use core module with `entry_point="engine"` |
| Workers | `workers/cli.py` | Added telemetry init in `main()` with `entry_point="worker"` |

## Example Span Output

With `GAIUS_TELEMETRY_ENABLED=true GAIUS_TELEMETRY_EXPORTER=console`:

```json
{
    "name": "gaius.cli/command/state",
    "attributes": {
        "gaius.command": "state",
        "gaius.entry_point": "cli",
        "code.function.name": "execute"
    },
    "resource": {
        "attributes": {
            "service.name": "gaius-cli",
            "service.namespace": "gaius",
            "service.version": "0.2.0",
            "service.instance.id": "tinybox-2978467",
            "deployment.environment.name": "dev"
        }
    }
}
```

## Usage

### Testing with Console Exporter

```bash
# Use console exporter to see spans in stdout
OTEL_TRACES_EXPORTER=console uv run gaius-cli --cmd "/state"

# Disable telemetry entirely
OTEL_SDK_DISABLED=true uv run gaius-cli --cmd "/state"
```

### Using traced_command in Code

```python
from gaius.core.telemetry import traced_command

with traced_command("domain", "_cmd_domain") as span:
    # Handle command
    span.set_attribute("domain", "pension")
```

## Cloudera Observability Alignment

- Distinct `service.name` per entry point enables filtering in dashboards
- `deployment.environment.name` enables dev/staging/prod separation
- Standard OTel semantic conventions for resource attributes
- W3C traceparent propagation already in engine transport
