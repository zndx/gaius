# Command Patterns

Common patterns for working with `gaius-cli` effectively. The CLI produces structured JSON output that integrates naturally with standard Unix tools.

## JSON Output and jq

Most commands support `--format json` for machine-readable output. Pipe through `jq` to extract specific fields:

```bash
# Get endpoint names and statuses
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[] | {name, status}'

# Extract just the health categories that are not OK
uv run gaius-cli --cmd "/health" --format json | jq '.data.checks[] | select(.status != "ok")'

# Get the current evolution generation number
uv run gaius-cli --cmd "/evolve status" --format json | jq '.data.generation'
```

## Polling for Status Changes

When waiting for an operation to complete, poll in a loop:

```bash
# Watch endpoints transition from STARTING to HEALTHY after a restart
for i in $(seq 1 15); do
    sleep 10
    uv run gaius-cli --cmd "/gpu status" --format json | \
        jq -r '.data.endpoints[] | "\(.name): \(.status)"'
    echo "---"
done
```

## Comparing Before and After

Capture state before and after an operation:

```bash
# Snapshot before
uv run gaius-cli --cmd "/health" --format json > /tmp/health-before.json

# Run an operation
uv run gaius-cli --cmd "/health fix engine" --format json

# Snapshot after
uv run gaius-cli --cmd "/health" --format json > /tmp/health-after.json

# Diff
diff <(jq -S . /tmp/health-before.json) <(jq -S . /tmp/health-after.json)
```

## Batch Operations

Run multiple commands in sequence:

```bash
# Check everything in one pass
for cmd in "/health" "/gpu status" "/evolve status"; do
    echo "=== $cmd ==="
    uv run gaius-cli --cmd "$cmd" --format json | jq '.data'
    echo
done
```

## Conditional Logic

Use `jq` exit codes to drive decisions:

```bash
# Only proceed if all endpoints are healthy
if uv run gaius-cli --cmd "/gpu status" --format json | \
    jq -e '.data.endpoints | all(.status == "HEALTHY")' > /dev/null 2>&1; then
    echo "All endpoints healthy, proceeding"
    uv run gaius-cli --cmd "/evolve trigger" --format json
else
    echo "Not all endpoints healthy, aborting"
    exit 1
fi
```

## Timestamp and Logging

Add timestamps for log correlation:

```bash
uv run gaius-cli --cmd "/health" --format json | \
    jq --arg ts "$(date -Iseconds)" '. + {queried_at: $ts}'
```

## Error Handling

The CLI returns non-zero exit codes on failure. Check both the exit code and the response:

```bash
if ! output=$(uv run gaius-cli --cmd "/gpu status" --format json 2>&1); then
    echo "CLI failed: $output"
    exit 1
fi
echo "$output" | jq '.data'
```
