# Operations/Incidents Separation

**Date:** 2026-01-02
**Status:** Complete

## Summary

Refactored the Agenda-Centric Incident Model to separate routine workload tracking (operations) from actual problems (incidents). This ensures Metabase dashboards display meaningful incident data rather than hundreds of routine success metrics.

## Architectural Change

### Before
- Single `agenda_incidents` table for all workload tracking
- Routine FULFILLED operations mixed with actual BLOCKED/FAILED problems
- Metabase showed "incidents" that were actually normal successful operations

### After
- `agenda_operations`: All workload executions (metrics, state recovery)
- `agenda_incidents`: Only problems requiring attention (ACP escalation)
- HealthObserverService responsible for escalating operations to incidents

## Implementation

### Database Migration (`20260102000003_agenda_operations_split.sql`)

| Table/View | Purpose |
|------------|---------|
| `agenda_operations` | Routine workload tracking (state recovery, metrics) |
| `agenda_incidents` | Problems only (BLOCKED, FAILED, DEGRADED requiring ACP) |
| `meta.ambient_cycle_metrics` | Hourly aggregates from operations |
| `meta.agenda_resolution_daily` | Daily completion rates with escalation rate |
| `meta.recent_agendas_summary` | Last 24 hours of operations |
| `meta.control_mode_health` | Weekly positive control rate trends |
| `meta.active_incidents` | Currently active incidents (for ACP/Health dashboard) |
| `meta.incident_summary` | Daily incident summary by type and escalation reason |

### AgendaTracker Refactoring

The `AgendaTracker` now:
1. Creates `AgendaOperation` on workload begin (not `AgendaIncident`)
2. Writes to `agenda_operations` table
3. Provides callback `on_control_degraded()` for HealthObserver escalation
4. No longer manages incidents directly

### Key Code Changes

| File | Change |
|------|--------|
| `src/gaius/engine/services/agenda_tracker.py` | Added `AgendaOperation` dataclass, refactored to write to `agenda_operations` |
| `db/migrations/20260102000003_agenda_operations_split.sql` | Created tables, migrated data, updated views |

### New Columns on `agenda_incidents`

| Column | Purpose |
|--------|---------|
| `escalation_reason` | Why operation became incident (e.g., "control_degraded") |
| `source_operation_id` | Links back to `agenda_operations` if escalated |
| `acp_escalated` | Whether incident was escalated to ACP |
| `acp_escalated_at` | Timestamp of ACP escalation |

## Verification

```sql
-- Operations table has routine tracking
SELECT COUNT(*) FROM agenda_operations;  -- 5+ records

-- Incidents table is empty (no problems have occurred)
SELECT COUNT(*) FROM agenda_incidents;  -- 0 records

-- Meta views query operations for metrics
SELECT * FROM meta.recent_agendas_summary LIMIT 5;
```

## Escalation Flow

```
AgendaTracker.on_workload_begin()
    → creates AgendaOperation in agenda_operations
    → on_control_degraded callback if control degrades

HealthObserverService
    → monitors for problems via on_control_degraded callback
    → creates AgendaIncident in agenda_incidents when escalation needed
    → may escalate to ACP if threshold exceeded
```

## Next Steps

1. Implement escalation logic in HealthObserverService
2. Add incident creation when control mode degrades from POSITIVE
3. Wire ACP escalation for high-severity incidents
