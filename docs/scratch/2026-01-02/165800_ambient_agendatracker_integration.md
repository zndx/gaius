# Ambient Workload AgendaTracker Integration

**Date:** 2026-01-02
**Status:** Complete

## Summary

Integrated the `/ambient` workload with the AgendaTracker system to exercise the Agenda-Centric Incident Model during continuous background operations.

## Implementation

### Files Modified

| File | Change Type | Description |
|------|-------------|-------------|
| `src/gaius/engine/services/ambient_service.py` | MODIFY | Added `set_agenda_tracker()`, endpoint transition tracking in eviction/restoration |
| `src/gaius/engine/server.py` | MODIFY | Wired AgendaTracker to AmbientWorkloadService |
| `db/migrations/20260102000002_ambient_metrics_views.sql` | NEW | Metabase-friendly views for ambient metrics |

### Key Integration Points

1. **AgendaTracker Wiring** (`ambient_service.py:258-265`)
   - Added `set_agenda_tracker()` method
   - Added instance variables `_agenda_tracker`, `_current_workload_id`, `_evicted_endpoints`

2. **Eviction Tracking** (`ambient_service.py:1052-1068`)
   - Records `HEALTHY -> ABSENT` transitions with `ControlMode.POSITIVE`
   - Captures evicted endpoints for later restoration tracking

3. **Restoration Tracking** (`ambient_service.py:1124-1141`)
   - Records `ABSENT -> HEALTHY` transitions with `ControlMode.POSITIVE`
   - Clears tracking state after successful restoration

4. **Server Wiring** (`server.py:992-995`)
   - Wires AgendaTracker to AmbientWorkloadService during initialization

### Metabase Views

| View | Purpose |
|------|---------|
| `meta.ambient_cycle_metrics` | Hourly aggregates by status/control mode |
| `meta.agenda_phase_metrics` | Phase-level latency percentiles |
| `meta.endpoint_transition_metrics` | Transition counts by control mode |
| `meta.agenda_resolution_daily` | Daily fulfillment rates |
| `meta.recent_agendas_summary` | Last 24 hours summary |
| `meta.control_mode_health` | Weekly positive control rate trends |

## Verification

Ran a 2-cycle ambient workload test:

```sql
-- Agenda incident created and fulfilled under positive control
SELECT agenda_id, status, control_mode, makespan_variance_pct
FROM agenda_incidents
WHERE agenda_id LIKE 'ambient%';

          agenda_id           |  status   | control_mode | makespan_variance_pct
------------------------------+-----------+--------------+-----------------------
 ambient-reasoning-1767372699 | fulfilled | positive     |            0.14168462
```

```sql
-- 11 endpoint transitions recorded with POSITIVE control
SELECT agenda_id, jsonb_array_length(endpoint_transitions) as transition_count
FROM agenda_incidents WHERE agenda_id LIKE 'ambient%';

          agenda_id           | transition_count
------------------------------+------------------
 ambient-reasoning-1767372699 |               11
```

## Success Criteria Met

1. **AgendaIncident created** for each ambient reasoning cycle
2. **Endpoint transitions tracked** with POSITIVE control mode during eviction/restoration
3. **Makespan variance calculated** (14.17% within tolerance)
4. **Metrics visible in Metabase** via the new views
5. **Status FULFILLED** under positive control
