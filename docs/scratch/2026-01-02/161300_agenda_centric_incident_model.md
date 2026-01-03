# Agenda-Centric Incident Model Implementation

**Date:** 2026-01-02
**Status:** Complete (Phase 1)

## Summary

Implemented the Agenda-Centric Incident Model for Gaius HealthObserver. This shifts incident tracking from endpoint-centric ("VLLM_001:coding is unhealthy") to agenda-centric ("Agenda X is BLOCKED at phase 3").

## Key Design Principles

1. **Agenda is the unit of health** - Not individual endpoints
2. **Makespan fulfillment is the success metric** - Did we achieve the projected schedule?
3. **Positive control is required for resolution** - Failures and restarts don't count; only intentional transitions
4. **Endpoints are means, not goals** - Tracked as diagnostic detail

## Implementation

### Database Schema

Created `db/migrations/20250102000001_agenda_incidents.sql` with:

- **agenda_type**: ENUM (ambient_cycle, swarm, evolution, inference, flow)
- **agenda_status**: ENUM (scheduling, on_track, delayed, blocked, fulfilled, failed, degraded)
- **control_mode**: ENUM (positive, failure_recovery, restart_recovery)
- **agenda_incidents** table: Core incident tracking
- **agenda_phase_events** table: Event-sourced phase transitions
- **active_agendas** view: Currently active agendas with progress
- **agenda_health_summary** view: Aggregate stats

### Core Model

Created `src/gaius/engine/incidents/agenda_incident.py`:

```python
class AgendaIncident:
    """Tracks whether an Agenda is proceeding according to makespan projections."""
    - phases: list[AgendaPhase]
    - current_phase_index: int
    - makespan_projection_ms: int
    - status: AgendaStatus
    - control_mode: ControlMode  # Degrades on any non-positive transition
```

Key behaviors:
- `record_transition()` automatically degrades control_mode if transition is non-positive
- `mark_fulfilled()` validates control_mode == POSITIVE, else marks DEGRADED
- `calculate_agenda_severity()` computes severity from variance + control mode + status

### AgendaTracker Service

Created `src/gaius/engine/services/agenda_tracker.py`:

- Lifecycle hooks: `on_workload_begin()`, `on_workload_complete()`
- Transition tracking: `on_endpoint_transition()`
- Engine restart detection: `on_engine_restart()`
- Database persistence with restoration on startup
- Callback system for incident lifecycle events

### Integration Points

1. **OrchestratorService** (`orchestrator_service.py:232-244`)
   - Added `set_agenda_tracker()` method
   - Wired `on_workload_begin()` after active workload tracking
   - Wired `on_workload_complete()` after baseline restoration

2. **ReconciliationService** (`reconciliation.py:1652-1674`)
   - Added `set_agenda_tracker()` method
   - Added `_notify_agenda_tracker()` for state transition callbacks
   - Tracks previous states to detect actual transitions

3. **GaiusEngine** (`server.py:958-1089`)
   - Added `_create_agenda_tracker()` daemon creation
   - Added `_on_agenda_incident()` callback for BLOCKED escalation
   - Added `_escalate_agenda_to_health_observer()` for ACP integration

## Control Mode Detection

```python
def detect_control_mode(endpoint, from_state, to_state, planned_transitions):
    # Positive: Transition was in the agenda's plan
    if planned_transitions and transition_in_plan(...):
        return ControlMode.POSITIVE

    # Failure recovery: Endpoint failed, recovered automatically
    if from_state == "UNHEALTHY" and to_state == "HEALTHY":
        return ControlMode.FAILURE_RECOVERY

    # Restart recovery: Engine restart caused transition
    if from_state == "ABSENT" and to_state == "HEALTHY":
        return ControlMode.RESTART_RECOVERY
```

## Resolution Criteria

An AgendaIncident is resolved **only** when:
1. All phases completed successfully
2. System returned to baseline configuration
3. Return was under **positive control** (not via failure/restart)

If control mode degrades during the agenda, final status is DEGRADED (not FULFILLED).

## Severity Calculation

```python
severity = base_severity * makespan_factor * control_factor * status_factor * 5 * 5

# Factors:
# - makespan_factor: 1.0-2.0 based on variance (>20% increases severity)
# - control_factor: 1.0 (positive), 1.5 (failure_recovery), 2.0 (restart_recovery)
# - status_factor: 0.5-2.0 based on status (BLOCKED = 2.0)
```

## Files Created/Modified

| File | Change |
|------|--------|
| `db/migrations/20250102000001_agenda_incidents.sql` | NEW: Schema |
| `src/gaius/engine/incidents/__init__.py` | NEW: Package exports |
| `src/gaius/engine/incidents/agenda_incident.py` | NEW: Model & enums |
| `src/gaius/engine/services/agenda_tracker.py` | NEW: Service |
| `src/gaius/engine/services/orchestrator_service.py` | Wire workload lifecycle |
| `src/gaius/engine/resources/reconciliation.py` | Add transition callbacks |
| `src/gaius/engine/server.py` | Initialize AgendaTracker |

## Next Steps (Future Phases)

1. Add MCP tool for agenda status (`/agenda status`)
2. Enhance ACP prompts with agenda context for better diagnosis
3. Add metrics/observability for agenda fulfillment rates
4. Integration testing with actual evolution cycles
