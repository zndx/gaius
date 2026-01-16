# FSM Reconciliation Loop Implementation

**Date**: 2025-12-20/21 (late session)
**Status**: Phase 2 Complete - Self-healing enabled by default

## Summary

Implemented the FSM-based reconciliation loop for the Gaius Engine as designed in `230000_engine_fsm_reconciliation.md`. This is a critical improvement that allows the engine to detect state drift between its internal tracking and actual GPU/process reality.

## Files Created/Modified

### New Files

1. **`src/gaius/engine/resources/reconciliation.py`** (~770 lines)
   - `EndpointState` enum with all FSM states
   - `EndpointObservation` dataclass for ground truth gathering
   - Observation functions:
     - `observe_gpu_processes()` - nvidia-smi process query
     - `observe_port_listeners()` - ss port scan
     - `check_endpoint_health()` - HTTP health checks
     - `is_pid_alive()` - /proc check
   - `reconcile_state()` - core FSM logic
   - `ReconciliationService` class with periodic observation loop

### Modified Files

1. **`src/gaius/engine/resources/__init__.py`**
   - Added exports for `ReconciliationService`, `EndpointState`, etc.

2. **`src/gaius/engine/server.py`**
   - Added `_reconciliation_service` field
   - Added `_init_reconciliation_service()` method
   - Added stop handling in `stop()` method
   - Enhanced `reconcile` action in orchestrator handler
   - Added `reconcile_status` action

## FSM State Machine

```
EndpointState values:
- absent    - No process, no GPU allocation
- allocated - GPUs reserved, process not started
- starting  - Process launched, health checks pending
- healthy   - Process running, responding to /health
- unhealthy - Process exists but not responding
- stopping  - Graceful shutdown in progress
- orphaned  - GPU memory leaked (CUDA context without process)
- conflict  - Port in use by different service
- failed    - Unrecoverable error
```

## Observation Sources Tested

| Source | Method | Status |
|--------|--------|--------|
| nvidia-smi | `--query-compute-apps` | ✓ Working |
| ss | `-tlnp` port scan | ✓ Working |
| /proc | PID alive check | ✓ Working |
| HTTP | /health, /v1/models | ✓ Working |

## Key Findings During Testing

1. **Stale CUDA Context Detected**: Found PID 2665786 holding GPU contexts on all 6 GPUs, but the process was dead. This is exactly what ORPHANED detection catches.

2. **optillm Fallback**: Health check on port 8000 showed `gpt-4o-mini` model, indicating optillm is falling back to OpenAI instead of routing to local vLLM.

3. **vLLM OOM**: Attempted vLLM launch on port 8094 failed with "Free memory on device (0.69/23.43 GiB) on startup is less than desired" - caused by the orphaned CUDA context.

## Reconciliation Logic

The key fix was adding orphaned GPU detection when expected state is ABSENT:

```python
if obs.expected_state == EndpointState.ABSENT:
    # Check for orphaned GPU memory (leaked CUDA contexts)
    if obs.has_gpu_memory and not obs.tracked_pid_alive:
        return EndpointState.ORPHANED
```

This catches the case where:
- Engine thinks nothing is running (ABSENT)
- But nvidia-smi shows GPU memory allocated
- And no tracked process is alive

## Testing Results

```
Test: Expected ABSENT but GPU memory leaked
  Expected state: absent
  Reconciled state: orphaned
  Drift detected: True

Test: Expected HEALTHY but process crashed
  Expected state: healthy
  Reconciled state: orphaned
  Drift detected: True

Test: Really ABSENT (clean state)
  Expected state: absent
  Reconciled state: absent
  Drift detected: False
```

## Integration Points

1. **gRPC API**:
   - `Orchestrator.reconcile` - Run observation and return drift status
   - `Orchestrator.reconcile_status` - Get service status

2. **Engine Startup**:
   - ReconciliationService starts after orchestrator init
   - Observation loop runs every 10 seconds (configurable)
   - **Remediation enabled by default** (self-healing is the point)

## Phase 2: Remediation Actions (Complete)

Added automatic remediation for detected drift states:

### Remediation Functions

1. **`remediate_orphaned()`**: Cleans up ORPHANED state
   - Kills orphan processes using `os.kill(SIGTERM/SIGKILL)`
   - Clears GPU memory via process termination
   - Releases allocation in ResourceManager
   - Falls back to warning if nvidia-smi --gpu-reset needed

2. **`remediate_unhealthy()`**: Restarts UNHEALTHY endpoints
   - Uses OrchestratorService.restart_endpoint()
   - Verifies health after restart

3. **`remediate_conflict()`**: Alerts on CONFLICT state
   - Does NOT automatically kill unknown processes
   - Returns critical severity with requires_approval=True
   - Logs actionable error with Guru Meditation code

### New gRPC Actions

- `Orchestrator.enable_remediation` - Enable/disable auto-remediation
- Status now includes `remediation_count` and `successful_remediations`

### Test Results

```
Test 1: ORPHANED state remediation
  Remediation action: clear_orphaned
  Remediation success: True
  New state: absent

Test 2: CONFLICT state
  Remediation action: alert_conflict
  Severity: critical
  Requires approval: True

Test 3: HEALTHY state
  Remediation needed: False
```

## Next Steps (Phases 3-4)

1. **Phase 3**: Dynamic port allocation
   - Port pool manager
   - Service discovery registration
   - Tilt/K8s coexistence

2. **Phase 4**: Integration with pre-flight command
   - `/preflight` command uses reconciliation observations
   - Quick system validation before starting work

## Guru Meditation Codes

Related error codes from the FMEA catalog:

| Code | Meaning | Remediation |
|------|---------|-------------|
| `#EN.00000010.DRIFT` | State drift detected | `/health fix engine` |
| `#EN.00000011.ORPHAN` | Orphaned process | Auto-cleanup or `/gpu cleanup` |
| `#EN.00000012.CONFLICT` | Port conflict | Manual intervention |
| `#EN.00000013.GPULEAK` | GPU memory leak | `nvidia-smi --gpu-reset` |
