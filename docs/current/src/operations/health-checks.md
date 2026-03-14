# Health Checks

The `/health` command runs diagnostics across all system components and reports status.

## Running Health Checks

```bash
# All checks
uv run gaius-cli --cmd "/health" --format json

# Specific category
uv run gaius-cli --cmd "/health gpu" --format json
uv run gaius-cli --cmd "/health endpoints" --format json
uv run gaius-cli --cmd "/health infrastructure" --format json
```

## Interpreting Results

Each check reports a status:

| Status | Meaning |
|--------|---------|
| `PASS` | Component is healthy |
| `WARN` | Component has issues but is functional |
| `FAIL` | Component is unhealthy |

## Applying Fixes

When checks fail, use `/health fix`:

```bash
# Fix a specific service
uv run gaius-cli --cmd "/health fix engine" --format json

# Available services
# engine, dataset, nifi, postgres, qdrant, minio, endpoints, evolution
```

**Always try `/health fix` before manual intervention.** This exercises the self-healing system and helps it improve over time.

## Manual Fallback

If `/health fix` fails:

```bash
# Full clean restart
just restart-clean

# GPU-specific cleanup
just gpu-cleanup
just gpu-deep-cleanup
```

## FMEA Diagnostics

For deeper analysis:

```bash
# FMEA summary with RPN scores
uv run gaius-cli --cmd "/fmea" --format json

# Failure mode details
uv run gaius-cli --cmd "/fmea detail GPU_001" --format json
```
