# Health Observer

The HealthObserver daemon provides continuous health monitoring with FMEA-based incident management and ACP escalation for issues beyond local remediation capability.

## Operation

The observer runs as a background service within the engine, polling system health at a configurable interval (default 60 seconds).

```python
from gaius.health.observe import HealthObserver

observer = HealthObserver()
await observer.start()  # Begins continuous monitoring
```

## Incident Lifecycle

```
Detection → Active → Healing → Recovered → Resolved
                  ↘ Escalated (ACP) → Resolved
```

1. **Detection**: Health check identifies a failure
2. **Active**: Incident created with FMEA risk scoring
3. **Healing**: Self-healing attempts in progress
4. **Recovered/Escalated**: Either resolved locally or sent to ACP
5. **Resolved**: Terminal state

### Fail Open

When filtering incidents for display, the observer uses **fail open** semantics: it filters OUT known terminal states (`resolved`) rather than filtering IN known active states. Unknown states are always surfaced for investigation.

## Makespan Integration

The observer integrates with the AgendaTracker to avoid false-positive incidents during scheduled operations. When an endpoint is part of a planned makespan transition:

```python
if tracker.is_endpoint_in_scheduled_transition("reasoning"):
    # Skip incident creation — this is intentional
    log.info(f"Skipping: endpoint in scheduled transition to {expected_state}")
```

## ACP Escalation

When an incident exceeds the RPN threshold or local remediation fails after 3 attempts, the observer escalates to Claude Code via ACP:

- Claude Code analyzes the issue using MCP tools
- Identifies gaps in the `/health fix` framework
- Implements new fix strategies and heuristics
- Commits to `acp-claude/health-fix` branch for review

### Cadence Limits

To prevent runaway automation:
- Max 3 GitHub issues per 24 hours
- Min 5 minutes between restart attempts
- Max 3 restarts per endpoint per hour

## CLI Commands

```bash
# Observer status
uv run gaius-cli --cmd "/health observer" --format json

# Active incidents
uv run gaius-cli --cmd "/health incidents" --format json

# Incident detail
uv run gaius-cli --cmd "/health incident <id>" --format json
```
