# Monitoring

Operational monitoring combines CLI health checks, GPU status tracking, and Metabase dashboards.

## Quick Status

```bash
# Overall health
uv run gaius-cli --cmd "/health" --format json

# GPU status
uv run gaius-cli --cmd "/gpu status" --format json

# Health Observer incidents
uv run gaius-cli --cmd "/health incidents" --format json
```

## Monitoring Stack

| Tool | Purpose | Access |
|------|---------|--------|
| `/health` CLI | Infrastructure health checks | CLI/MCP |
| `/gpu status` CLI | GPU and endpoint monitoring | CLI/MCP |
| Health Observer | Continuous background monitoring | Engine daemon |
| Metabase | Analytics dashboards | Web UI |
| Prometheus | Time-series metrics | Query API |

## See Also

- [Health Checks](./health-checks.md) — Running diagnostics
- [GPU Management](./gpu.md) — GPU operations
