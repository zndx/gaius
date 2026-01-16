# Ambient Cycle Recovery Failure Analysis

**Status: FIXED** (2025-12-30 17:45 UTC)

## Summary

During `/ambient cycle` testing on 2025-12-30, a critical recovery failure was observed where the engine became stuck in a partially restored state after a workload timeout. The engine required manual restart to recover.

**Root cause**: `complete_workload()` in `orchestrator_service.py` was not stopping transient endpoints (like `cap_reasoning`) before attempting to restore evicted baseline endpoints.

**Fix**: Modified `complete_workload()` to:
1. Stop all transient endpoints allocated for the workload
2. Wait for GPU memory release (3 seconds)
3. Then restore evicted baseline endpoints

The full ambient cycle now completes successfully without engine restart.

## Symptoms

1. **Stale process state**: The `/gpu status` command showed processes as `PROCESS_STATUS_STOPPING` indefinitely
2. **No ACP escalation**: Despite the degraded state, no ACP intervention was triggered
3. **Manual restart required**: The engine had to be manually restarted via `devenv processes down && devenv processes up`

## Timeline

1. `/ambient cycle` started successfully
2. Baseline verification: 3/3 endpoints healthy
3. Baseline workload: 3/3 tasks completed
4. Scheduler eviction: Evicted orchestrator, fast, coding
5. Reasoning endpoint (cap_reasoning) started on GPUs [1,2,3,4]
6. **Reasoning task completed successfully (7626ms)**
7. Baseline restoration started
8. **CLI timeout (5 minutes) during restoration**
9. Engine stuck with stale process records

## Root Causes

### 1. Stale VLLMProcess Records

The `VLLMController` maintains a `_processes` dict that maps endpoint names to `VLLMProcess` objects. When the CLI times out mid-restoration, these records are never cleaned up because:

- `stop_endpoint()` may have been called but not awaited to completion
- New processes started but the old process records weren't removed
- The controller's state became inconsistent with reality

**Location**: `src/gaius/engine/backends/vllm_controller.py:_processes`

### 2. Missing Workload Timeout Handling

The `complete_workload()` method in `OrchestratorService` doesn't have a timeout on the restoration operations. If restoration takes longer than the caller's timeout, the workload is left in a partially completed state.

**Location**: `src/gaius/engine/services/orchestrator_service.py:complete_workload()`

### 3. No HealthObserver Detection

The HealthObserver should detect:
- Workloads that are stuck (started but not completed within expected duration + buffer)
- Endpoints that are stuck in STOPPING state
- Inconsistency between process records and actual running processes

**Location**: `src/gaius/health/observe.py`

## Remediation Recommendations

### Short-term Fixes

1. **Add process reconciliation on engine startup**
   - On startup, scan for orphaned vLLM processes and kill them
   - Clear all process records and rebuild from actual running processes

2. **Add timeout to complete_workload()**
   ```python
   async def complete_workload(
       self, workload_id: str, timeout_s: float = 300
   ) -> bool:
   ```

3. **Add stuck workload detection in HealthObserver**
   - Check for workloads that have exceeded their estimated_duration + buffer
   - Emit healing event for stuck workloads

### Long-term Fixes

1. **Process state reconciliation daemon**
   - Periodically compare VLLMController's `_processes` with actual processes via `pgrep`
   - Clean up stale records automatically

2. **ACP escalation for stuck workloads**
   - When a workload is stuck beyond threshold, create GitHub issue for ACP intervention
   - Include diagnostic information: which endpoints stuck, GPU allocation state

3. **Graceful timeout handling in ambient cycle**
   - If restoration is taking too long, the cycle should complete with a warning
   - The engine should continue to work on restoration in background

## Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#WL.00000001.STUCKWORKLOAD` | Workload exceeded expected duration |
| `#VLLM.00000002.STALEPROC` | VLLMController has stale process record |
| `#VLLM.00000003.ORPHANPROC` | Orphaned vLLM process found without record |
| `#RESTORE.00000001.TIMEOUT` | Baseline restoration timed out |

## Test Case

```bash
# Start ambient cycle with 5 minute timeout
timeout 300 uv run gaius-cli --cmd "/ambient cycle" --format json

# If this times out during restoration, the engine is now stuck
# Verify with:
uv run gaius-cli --cmd "/gpu status" --format json
# Shows endpoints stuck in PROCESS_STATUS_STOPPING

# Manual recovery required:
devenv processes down && devenv processes up
```

## Related Files

- `src/gaius/engine/backends/vllm_controller.py` - VLLMController with _processes dict
- `src/gaius/engine/services/orchestrator_service.py` - complete_workload()
- `src/gaius/engine/services/ambient_service.py` - _restore_baseline()
- `src/gaius/health/observe.py` - HealthObserver daemon
- `src/gaius/acp/` - ACP client for escalation
