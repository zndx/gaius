# Health Observer

The HealthObserver daemon provides continuous health monitoring with FMEA-based incident management, tiered self-healing, and ACP escalation for issues beyond local remediation capability.

## Operation

The observer runs as a background service within the engine, polling system health at a configurable interval (default 60 seconds). Each poll executes health checks across all registered services, computes FMEA risk scores, and dispatches to the appropriate remediation tier.

## Incident Lifecycle

```
Detection → Active → Healing → Recovered → Resolved
                  ↘ Escalated (ACP) → Resolved
```

1. **Detection**: Health check identifies a failure. The observer creates an `Incident` with a unique fingerprint (hash of service + failure mode + endpoint).
2. **Active**: FMEA engine computes RPN = S × O × D. The incident enters the tiered remediation pipeline based on its score.
3. **Healing**: Self-healing attempts in progress. Tier 0 (procedural restart, RPN < 100) runs automatically. Tier 1 (agent-assisted, RPN 100-200) uses a healthy endpoint to diagnose. Tier 2 (RPN > 200) queues for approval.
4. **Recovered/Escalated**: Either resolved locally or escalated via ACP when local remediation fails after 3 attempts.
5. **Resolved**: Terminal state. Healing events are recorded for adaptive learning.

### Healing Event Audit Trail

Every remediation action is recorded as a `HealingEvent` with timestamp, tier, action taken, and outcome. This trail feeds the adaptive learning system — successful remediations reduce the Occurrence (O) score for that failure mode via EMA (alpha=0.2), while failures increase it. Over time, the FMEA scores converge toward the actual reliability characteristics of each component.

### Fail Open

When filtering incidents for display, the observer uses **fail open** semantics: it filters OUT known terminal states (`resolved`) rather than filtering IN known active states. Unknown or unexpected states are always surfaced for investigation rather than hidden.

## Makespan Integration

The observer integrates with the `AgendaTracker` to avoid false-positive incidents during scheduled operations. When an endpoint is part of a planned makespan transition (e.g., GPU eviction for rendering), the observer checks:

```python
if tracker.is_endpoint_in_scheduled_transition("reasoning"):
    expected = tracker.get_scheduled_endpoint_state("reasoning")
    log.info(f"Skipping: endpoint in scheduled transition to {expected}")
    return  # Not an incident — this is intentional
```

Without this integration, every render pipeline operation would generate spurious health incidents as endpoints cycle through STOPPING → STOPPED → STARTING states.

## ACP Escalation

When an incident exceeds the RPN threshold or local remediation fails after 3 attempts, the observer escalates via ACP (Agent Client Protocol) to Mistral Vibe:

- The ACP agent analyzes the issue using MCP tools
- Identifies gaps in the `/health fix` framework
- Implements new fix strategies and heuristics
- Commits to `acp/health-fix` branch for human review

The ACP agent is a *meta-level maintainer* — it doesn't just fix the immediate issue, it teaches the system to fix similar issues autonomously in the future.

### Cadence Limits

To prevent runaway automation:
- Max 3 GitHub issues per 24 hours
- Min 5 minutes between restart attempts
- Max 3 restarts per endpoint per hour
- Cooldown per incident fingerprint (prevents repeated escalation of the same issue)

## Scheduled Transition Awareness

The observer distinguishes three `ControlMode` values from the AgendaTracker:

| Mode | Meaning | Observer Behavior |
|------|---------|-------------------|
| `POSITIVE` | Planned operation (start/stop) | Skip incident creation |
| `FAILURE` | Responding to failure | Create incident, track remediation |
| `RESTART_RECOVERY` | Restarting after failure | Allow extended grace period |

## CLI Commands

```bash
# Observer status
uv run gaius-cli --cmd "/health observer" --format json

# Active incidents
uv run gaius-cli --cmd "/health incidents" --format json

# Incident detail
uv run gaius-cli --cmd "/health incident <id>" --format json
```
