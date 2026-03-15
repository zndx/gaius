# Health Workflow

The health workflow covers diagnosing system issues, applying self-healing fixes, and monitoring recovery. Gaius implements a fail-fast policy with actionable error messages, so every failure tells you what to do next.

## Step 1: Diagnose

Run the health check to see the current state of all services:

```bash
uv run gaius-cli --cmd "/health" --format json
```

This returns a structured report with checks organized by category. Each check has a status (`ok`, `warn`, `fail`) and a message explaining the current state.

To check a specific category:

```bash
uv run gaius-cli --cmd "/health engine" --format json
uv run gaius-cli --cmd "/health endpoints" --format json
```

## Step 2: Interpret Failures

Failed checks include **Guru Meditation Codes** -- unique identifiers for each failure mode. For example:

- `#DS.00000001.SVCNOTINIT` -- DatasetService not initialized
- `#NF.00000001.UNREACHABLE` -- NiFi not reachable
- `#EP.00000001.GPUOOM` -- GPU out of memory

Each code maps to a documented heuristic with symptom, cause, observation method, and solution. The error message itself contains remediation hints.

## Step 3: Self-Heal

**Always try `/health fix` before manual intervention.** This is a design principle, not a suggestion:

```bash
uv run gaius-cli --cmd "/health fix engine" --format json
uv run gaius-cli --cmd "/health fix endpoints" --format json
uv run gaius-cli --cmd "/health fix nifi" --format json
```

Available fix targets: `engine`, `dataset`, `nifi`, `postgres`, `qdrant`, `minio`, `endpoints`, `evolution`.

Each fix strategy is a multi-step remediation sequence with verification at each step. The system attempts increasingly aggressive fixes until the service recovers.

## Step 4: Monitor Recovery

After applying a fix, monitor the health observer for recovery:

```bash
# Check observer status
uv run gaius-cli --cmd "/health observer status" --format json

# List active incidents
uv run gaius-cli --cmd "/health observer incidents" --format json

# Poll for recovery
for i in $(seq 1 10); do
    sleep 15
    uv run gaius-cli --cmd "/health" --format json | \
        jq '.data.checks[] | select(.status != "ok") | {name, status, message}'
done
```

## Step 5: Escalation

If `/health fix` does not resolve the issue, the Health Observer can escalate via ACP (Agent Client Protocol) to Mistral Vibe for deeper analysis. This happens automatically when:

1. An incident exceeds the configured FMEA RPN threshold
2. Local remediation has failed
3. The incident is not in cooldown

Manual escalation path -- use `just restart-clean` as the last resort:

```bash
just restart-clean
```

This performs a full clean restart of all services: stops everything, cleans up state, and restarts from scratch.

## FMEA Framework

The health system uses Failure Mode and Effects Analysis (FMEA) to prioritize issues. Each failure mode has a Risk Priority Number (RPN) computed from severity, occurrence frequency, and detection difficulty. Higher RPNs get attention first.

```bash
# View the FMEA catalog
uv run gaius-cli --cmd "/fmea catalog" --format json

# Calculate RPN for a specific failure mode
uv run gaius-cli --cmd "/fmea rpn <mode>" --format json
```

## Health Observer Daemon

The Health Observer runs as a background daemon, continuously monitoring service health and automatically triggering remediation when issues are detected:

```bash
# Start the observer
uv run gaius-cli --cmd "/health observer start" --format json

# Stop the observer
uv run gaius-cli --cmd "/health observer stop" --format json
```

When running, it checks services periodically and logs incidents. Resolved incidents are filtered out of the active list, but unknown or unexpected states remain visible (fail-open for observability).
