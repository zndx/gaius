# Health Check Enhancements + Routing Analytics

Implemented comprehensive health check expansion and capability-based routing analytics.

## Part 1: New Health Checks

Added 6 new health checks to `src/gaius/health/checker.py`:

| Check | Category | Purpose |
|-------|----------|---------|
| `evolution_daemon` | evolution | Monitors if evolution daemon is running, cycles completed |
| `gpu_temperature` | inference | WARN > 75°C, FAIL > 85°C |
| `scheduler_queue` | inference | WARN if queue > 10 or avg wait > 30s |
| `xai_budget` | inference | Tracks XAI API usage against daily/weekly limits |
| `stale_processes` | engine | Detects orphan vLLM processes not managed by engine |
| `routing_quality` | inference | Monitors capability mismatch rate, starved agents |

### Sample Output

```
Evolution Daemon: warn - Daemon not running
GPU Temperature:  pass - 6 GPUs, max 48°C
Scheduler Queue:  pass - Queue depth: 0
XAI Budget:       warn - Check failed (needs server-side action)
Stale Processes:  pass - No vLLM processes running
Model Routing:    pass - No routing decisions recorded yet
```

## Part 2: Routing Analytics System

### Database Schema

New table `routing_decisions` tracks every agent inference request:

```sql
CREATE TABLE routing_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_role TEXT,
    agent_alias TEXT NOT NULL,
    workflow_phase TEXT,
    requested_capabilities TEXT[] DEFAULT '{}',
    preferred_model TEXT,
    actual_endpoint TEXT NOT NULL,
    actual_model TEXT NOT NULL,
    fallback_used BOOLEAN DEFAULT FALSE,
    fallback_reason TEXT,
    capability_mismatch BOOLEAN DEFAULT FALSE,
    mismatched_capabilities TEXT[] DEFAULT '{}',
    success BOOLEAN NOT NULL,
    latency_ms INTEGER NOT NULL
);
```

### New Module

`src/gaius/inference/routing_analytics.py`:

- `RoutingOutcome` enum: OPTIMAL, CAPABILITY_MATCH, CAPABILITY_FALLBACK, DEFAULT_FALLBACK
- `RoutingDecision` dataclass with all routing metadata
- `RoutingAnalyticsCollector`: Buffered writes (100 records or 30s interval)
- `record_routing_decision()` convenience function

### Router Instrumentation

`EndpointRouter.get_endpoint_for_role_with_outcome()` returns routing metadata:

```python
endpoint, outcome = router.get_endpoint_for_role_with_outcome(AgentRole.LEADER)
# outcome = {
#     'outcome': 'capability_fallback',
#     'requested_capabilities': ['reasoning', 'long_context'],
#     'preferred_model': 'Qwen/QwQ-32B',
#     'mismatched_capabilities': ['Qwen/QwQ-32B'],
#     'fallback_reason': 'Preferred model Qwen/QwQ-32B not available'
# }
```

`complete_for_role()` now automatically records routing decisions to PostgreSQL.

### Health Check Integration

The `routing_quality` check queries the last 24 hours:

- WARN if mismatch_rate > 50%
- Shows starved_agents (>50% suboptimal routing)
- Lists top capability gaps

## Files Changed

| File | Changes |
|------|---------|
| `src/gaius/health/checker.py` | +6 health check definitions, +6 check implementations |
| `src/gaius/inference/routing_analytics.py` | NEW: RoutingDecision, Collector |
| `src/gaius/inference/router.py` | Instrumented get_endpoint_for_role(), complete_for_role() |
| `src/gaius/storage/database.py` | +3 routing query functions |
| `db/migrations/20251210000001_routing_analytics.sql` | NEW: routing_decisions table |

## Known Issues

- XAI Budget check requires server-side "budget" action in Scheduler gRPC service (not yet implemented)
- Routing analytics only tracks `complete_for_role()` calls, not direct `complete()` calls

## Testing

```bash
# Run health checks
uv run gaius-cli --cmd "/health" --format json

# Verify routing outcome tracking
uv run python -c "
from gaius.inference.router import get_endpoint_router
from gaius.agents.roles import AgentRole
router = get_endpoint_router()
endpoint, outcome = router.get_endpoint_for_role_with_outcome(AgentRole.LEADER)
print(f'Endpoint: {endpoint}')
print(f'Outcome: {outcome}')
"
```
