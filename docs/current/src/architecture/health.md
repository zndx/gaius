# Health & Self-Healing

Gaius implements autonomous health monitoring based on FMEA (Failure Mode and Effects Analysis). The system quantifies risk using RPN (Risk Priority Number) scores, applies tiered remediation, and learns from outcomes to improve over time.

## Architecture

The health system has four layers:

1. **Detection**: Scheduled checks, continuous watcher, and user reports identify issues
2. **Analysis**: FMEA engine calculates RPN scores from severity, occurrence, and detection ratings
3. **Remediation**: Three-tier system from automatic restarts to agent-assisted diagnosis to user approval
4. **Learning**: Adaptive learner adjusts S/O/D scores based on remediation outcomes

## How It Works

When a health check detects an issue:

1. The FMEA engine maps it to a failure mode from the 34-mode catalog
2. RPN is calculated: **RPN = S x O x D** (max 1000)
3. Based on the RPN score, remediation is routed to the appropriate tier:
   - **RPN < 100** (Tier 0): Automatic procedural restart
   - **RPN 100-200** (Tier 1): Agent-assisted remediation
   - **RPN > 200** (Tier 2): Requires user approval
   - **RPN > 300**: Escalates via ACP (grok-build; local thinking default) for meta-level intervention
4. Outcomes feed back into the adaptive learner, adjusting future risk scores

## Health Check Categories

| Category | Example Checks |
|----------|---------------|
| Infrastructure | gRPC connection, PostgreSQL, Qdrant, MinIO |
| GPU | Memory usage, temperature |
| Endpoints | vLLM health, stuck endpoints, orphan processes |
| Evolution | Evolution daemon, cognition daemon |
| Resources | Disk space, scheduler queue, XAI budget |

## CLI Commands

```bash
# Run all health checks
uv run gaius-cli --cmd "/health" --format json

# Run checks for a specific category
uv run gaius-cli --cmd "/health gpu" --format json

# Apply automated fix
uv run gaius-cli --cmd "/health fix engine" --format json

# FMEA summary
uv run gaius-cli --cmd "/fmea" --format json
```

## HealthObserver Daemon

The `HealthObserver` (`health/observe.py`) runs as a background daemon with a configurable poll interval (default 60s). On each cycle it executes all health checks, maps failures to FMEA failure modes, and manages a set of active incidents.

**Incident lifecycle**:

1. **Detection** — Health check fails; FMEA engine maps to a failure mode and computes RPN
2. **Active** — Incident is created with a fingerprint (failure mode + endpoint). Duplicate fingerprints are deduplicated
3. **Healing** — Self-healer applies the appropriate tier. Tier 0 restarts are immediate; Tier 1 uses a healthy endpoint for diagnosis; Tier 2 queues for approval
4. **Recovering** — Spontaneous recovery detected (health check passes without intervention). The observer distinguishes this from healed-by-intervention
5. **Resolved** — Outcome recorded. The adaptive learner adjusts S/O/D scores based on whether the fix succeeded, how long it took, and whether the issue was user-reported or auto-detected

**Healing event audit trail**: Every remediation attempt is recorded in the `healing_events` PostgreSQL table — including ACP escalations, which log the full prompt/response exchange. This provides a complete audit trail for post-incident analysis and for training the adaptive learner.

**Scheduled transition awareness**: The observer consults the `AgendaTracker` before creating incidents. Endpoints currently in a makespan-scheduled transition (e.g., model swap during GPU eviction) are excluded from incident creation, preventing false positives during planned operations.

**ACP escalation**: When an incident exceeds RPN 300 or fails three local remediation attempts, the observer escalates via the Agent Client Protocol. Default ACP is grok-build on local thinking (Qwen3.8-27B via Engine/Complete); subscription grok-build is used only when a task needs it. The ACP agent analyzes the failure using MCP tools, identifies gaps in the `/health fix` framework, and commits improvements to the `acp/health-fix` branch for human review. Cadence limits (max 3 issues/24h, min 5 min between restarts) prevent runaway automation.

## Subchapters

- [FMEA Framework](./fmea.md) — Risk scoring details and failure mode catalog
- [Remediation Strategies](./remediation.md) — Fix strategies and tier system
- [Health Observer](./health-observer.md) — Continuous monitoring daemon
- [Guru Meditation Codes](./guru-codes.md) — Error identification system
