# /health fix endpoints Implementation

## Summary

Extended the `/health fix endpoints` command with intelligent multi-step remediation for inference endpoint issues. This creates an exemplary AIOps capability in Gaius.

## Changes Made

### 1. Enhanced `EndpointFixStrategy` (`service_fixes.py`)

Replaced simple `reconcile_state()` call with 4-step intelligent remediation:

1. **Diagnose** - Get endpoint status via `/gpu status`, identify stuck/unhealthy endpoints and orphan processes
2. **Kill Orphans** - Find vLLM processes not tracked by orchestrator and SIGTERM them
3. **Restart Unhealthy** - Force stop stuck "stopping" endpoints, reset+restart stuck "starting" endpoints, restart unhealthy/failed
4. **Verify** - Check final health state and report results

All steps use subprocess calls to CLI (`/gpu status`, `/gpu stop`, `/gpu start`) to avoid event loop issues with async code in executor context.

### 2. Added Health Checks (`checker.py`)

- **Stale Processes** (`_check_stale_processes`): Now has `heuristic_id="inference/stale_vllm_processes"` for KB linkage
- **Stuck Endpoints** (`_check_endpoint_stuck`): New check for endpoints stuck in "starting"/"stopping" state

Fixed event loop bug in `_check_endpoint_stuck` by using `get_health_proxy()` instead of `get_orchestrator_proxy()` (the latter's `get_status()` uses `run_until_complete` which conflicts with already-running event loops).

### 3. Added CLI Command

- `/gpu clean-start [endpoints]` - Kill stale processes and reset orchestrator state (uses `orch.clean_start()`)

### 4. Created KB Heuristics

- `inference/stale_vllm_processes.md` - Orphaned vLLM processes
- `inference/endpoint_stuck.md` - Endpoints stuck in transitional state
- `inference/endpoint_startup_failure.md` - Startup failures (OOM, model not found, port conflict, CUDA)

## Testing Results

```
/health fix endpoints
```

Output shows:
- 4/4 actions completed successfully
- Correctly identifies stuck endpoints (stopping/starting)
- Correctly reports no orphan processes
- Attempts to stop/restart stuck endpoints

## Known Limitation

The engine's orchestrator maintains endpoint state that can get out of sync with actual process state. When processes crash or are killed externally, the orchestrator may report endpoints as "starting" or "stopping" indefinitely.

Workaround: Use `/gpu clean-start` or restart the engine (`devenv processes restart gaius-engine`).

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/health/service_fixes.py` | Enhanced `EndpointFixStrategy` with 4-step remediation |
| `src/gaius/health/checker.py` | Added `_check_endpoint_stuck`, fixed async issue, added heuristic_id |
| `src/gaius/cli.py` | Added `/gpu clean-start` command |
| KB: `inference/stale_vllm_processes.md` | New heuristic |
| KB: `inference/endpoint_stuck.md` | New heuristic |
| KB: `inference/endpoint_startup_failure.md` | New heuristic |
