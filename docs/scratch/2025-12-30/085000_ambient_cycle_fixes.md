# Ambient Cycle Fixes

## Summary

Fixed multiple issues in the ambient computing workload cycle that were preventing the reasoning phase from executing correctly.

## Issues Fixed

### 1. WorkloadRequest API Mismatch (ambient_service.py:518-540)

**Problem**: `_evict_for_reasoning()` was calling `begin_workload()` with keyword arguments instead of a `WorkloadRequest` dataclass object.

**Error**: `OrchestratorService.begin_workload() got an unexpected keyword argument 'workload_id'`

**Fix**: Created proper WorkloadRequest object:
```python
from ..workloads import WorkloadRequest, WorkloadType, JobPriority
from gaius.models.registry import TaskType

request = WorkloadRequest(
    workload_id=f"ambient-reasoning-{int(time.time())}",
    workload_type=WorkloadType.INFERENCE,
    required_capabilities=[TaskType.REASONING],
    priority=JobPriority.HIGH,
    estimated_duration_s=120,
    estimated_memory_mb=32000,
    preemptible=False,
)
result = await self._orchestrator.begin_workload(request)
```

### 2. TaskType Import Location (ambient_service.py:521)

**Problem**: TaskType was being imported from `orchestrator_service` where it doesn't exist.

**Error**: `cannot import name 'TaskType' from 'gaius.engine.services.orchestrator_service'`

**Fix**: Import from correct location:
```python
from gaius.models.registry import TaskType
```

### 3. Missing start_model Method (vllm_controller.py:300-363)

**Problem**: `orchestrator_service._start_capability_endpoint()` was calling `start_model()` but VLLMController only had `start_endpoint()` for agent-configured endpoints.

**Error**: `'VLLMController' object has no attribute 'start_model'`

**Fix**: Added `start_model()` method that accepts dynamic model parameters:
```python
async def start_model(
    self,
    endpoint_name: str,
    model_id: str,
    port: int,
    gpu_ids: list[int],
    serve_command: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
    context_length: int = 32768,
    max_num_seqs: int = 256,
    tensor_parallel: int = 1,
) -> VLLMProcess:
```

Also updated `_start_vllm_process()` to accept optional `serve_command` and `extra_env` parameters.

### 4. serve_command String-to-List Conversion (orchestrator_service.py:826-830)

**Problem**: `model_spec.serve_command()` returns a string, but `start_model()` expects a list. When a string is passed as a list, Python iterates character by character.

**Error**: Command appeared with spaces between every character: `v l l m   s e r v e   Q w e n / Q w Q - 3 2 B`

**Fix**: Use `shlex.split()` to properly parse the command string:
```python
cmd_str, env = model_spec.serve_command(port=port, gpus=gpus)
import shlex
cmd = shlex.split(cmd_str)
```

### 5. Error Message Propagation (ambient_service.py:541-544)

**Problem**: When `begin_workload()` failed, the error message wasn't being captured and returned, resulting in "Failed to prepare for reasoning: unknown".

**Fix**: Capture the error field from WorkloadResult:
```python
response = {
    "success": result.success,
    "evicted": list(result.evicted_endpoints) if result.evicted_endpoints else [],
    "restore_plan": list(result.restore_plan) if result.restore_plan else [],
    "wait_time_ms": result.wait_time_ms,
}
# Include error message from WorkloadResult if present
if not result.success and result.error:
    response["error"] = result.error
return response
```

## Verification

After fixes, the ambient cycle correctly:
1. Verifies baseline health (3/3 healthy endpoints)
2. Runs baseline workload tasks (3/3 tasks complete)
3. Evicts baseline endpoints to free GPUs
4. Starts the reasoning model (Qwen/QwQ-32B)
5. Properly reports capability allocation failures with actionable error messages

The reasoning model startup failure (resource/capacity issue) is now correctly detected and escalated through the health observer tiers:
```
08:39:56 [INFO] gaius.engine.backends.vllm_controller: Starting vLLM for cap_reasoning: CUDA_VISIBLE_DEVICES=0,1,2,3 vllm serve Qwen/QwQ-32B --port=8080 --tensor-parallel-size=4 --gpu-memory-utilization=0.9 --max-num-seqs=256 --dtype=auto --max-model-len=32768 --trust-remote-code
```

## Files Changed

- `src/gaius/engine/services/ambient_service.py` - WorkloadRequest API fix, TaskType import, error propagation
- `src/gaius/engine/services/orchestrator_service.py` - serve_command string-to-list conversion
- `src/gaius/engine/backends/vllm_controller.py` - Added start_model() method, updated _start_vllm_process() signature
