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
   - **RPN > 300**: Escalates to ACP (Claude Code) for meta-level intervention
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

## Self-Healing First

When encountering unhealthy services, always try `/health fix` before manual intervention:

1. **`/health fix <service>`** — Let Gaius attempt self-healing
2. **`just restart-clean`** — Only if self-healing fails
3. **Manual investigation** — Last resort

This ensures the self-healing system gets exercised and improved over time.

## Subchapters

- [FMEA Framework](./fmea.md) — Risk scoring details and failure mode catalog
- [Remediation Strategies](./remediation.md) — Fix strategies and tier system
- [Health Observer](./health-observer.md) — Continuous monitoring daemon
- [Guru Meditation Codes](./guru-codes.md) — Error identification system
