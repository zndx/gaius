# Scripting

The `gaius-cli` is designed for non-interactive use in shell scripts. It connects to the gRPC engine, executes a command, prints output, and exits. This makes it suitable for cron jobs, monitoring scripts, and automation pipelines.

## Health Monitoring Script

A script that checks system health and sends alerts on failures:

```bash
#!/usr/bin/env bash
set -euo pipefail

LOG="/var/log/gaius-health.log"

health=$(uv run gaius-cli --cmd "/health" --format json)
failed=$(echo "$health" | jq '[.data.checks[] | select(.status != "ok")] | length')

if [ "$failed" -gt 0 ]; then
    echo "$(date -Iseconds) ALERT: $failed health checks failing" >> "$LOG"
    echo "$health" | jq '.data.checks[] | select(.status != "ok")' >> "$LOG"
fi
```

## Periodic Data Collection

Capture endpoint metrics at regular intervals for trend analysis:

```bash
#!/usr/bin/env bash
set -euo pipefail

OUTDIR="$HOME/gaius-metrics/$(date +%Y-%m-%d)"
mkdir -p "$OUTDIR"

TIMESTAMP=$(date +%H%M%S)

uv run gaius-cli --cmd "/gpu status" --format json > "$OUTDIR/${TIMESTAMP}_gpu.json"
uv run gaius-cli --cmd "/health" --format json > "$OUTDIR/${TIMESTAMP}_health.json"
uv run gaius-cli --cmd "/evolve status" --format json > "$OUTDIR/${TIMESTAMP}_evolve.json"
```

Run via cron every 5 minutes:

```cron
*/5 * * * * cd /path/to/gaius && devenv shell -- bash scripts/collect-metrics.sh
```

## Endpoint Readiness Gate

Wait for all endpoints to be healthy before proceeding with a downstream operation:

```bash
#!/usr/bin/env bash
set -euo pipefail

MAX_WAIT=300  # 5 minutes
INTERVAL=10
elapsed=0

echo "Waiting for endpoints to become healthy..."
while [ $elapsed -lt $MAX_WAIT ]; do
    if uv run gaius-cli --cmd "/gpu status" --format json | \
        jq -e '.data.endpoints | all(.status == "HEALTHY")' > /dev/null 2>&1; then
        echo "All endpoints healthy after ${elapsed}s"
        exit 0
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

echo "Timed out waiting for endpoints after ${MAX_WAIT}s"
exit 1
```

## Evolution Report

Generate a summary of the current evolution state:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Gaius Evolution Report $(date -Iseconds) ==="
echo

echo "## Agent Status"
uv run gaius-cli --cmd "/evolve status" --format json | \
    jq -r '.data | "Generation: \(.generation)\nActive agents: \(.active_agents)"'

echo
echo "## Endpoint Status"
uv run gaius-cli --cmd "/gpu status" --format json | \
    jq -r '.data.endpoints[] | "  \(.name): \(.status)"'

echo
echo "## Health Summary"
uv run gaius-cli --cmd "/health" --format json | \
    jq -r '.data.checks[] | "  \(.name): \(.status)"'
```

## Tips for Robust Scripts

- Always use `set -euo pipefail` at the top of scripts
- Check that the engine is reachable before running a batch of commands
- Use `--format json` consistently so output is parseable
- Capture output to variables when you need to inspect it multiple times
- Log timestamps alongside data for correlation with system events
