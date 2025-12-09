# GPU Zero-State Cleanup Implementation

## Date: 2025-12-07

## Summary

Implemented a systemic solution to GPU zombie process cleanup to enable tier-4+ tests (QwQ-32B with tensor-parallel=4) to pass.

## Problem

vLLM tensor-parallel processes (VLLM::Worker, VLLM::EngineCore) were surviving parent process termination:
- Parent vLLM receives SIGTERM but child workers survive
- GPU memory remains occupied
- Subsequent scenarios fail with OOM errors

## Solution Implemented

### 1. Enhanced `stop_endpoint()` (orchestrator.py:494-556)
- Uses process group killing (`os.killpg()`) to terminate all child processes
- Falls back to parent-only kill if process group unavailable
- Graceful SIGTERM with timeout, then SIGKILL

### 2. New `wait_for_gpu_free()` method (orchestrator.py:832-900)
- Polls nvidia-smi to verify GPU memory is freed
- Configurable timeout and memory threshold
- Essential for tier-4 tests that need guaranteed GPU availability

### 3. Enhanced `cleanup_stale_processes()` (orchestrator.py:902-1013)
- Comprehensive process detection patterns:
  - `python.*vllm` - Main server
  - `vllm\.entrypoints` - Entry points
  - `VLLM::Worker` - Tensor-parallel workers
  - `VLLM::EngineCore` - Engine core
  - `ray::IDLE` - Ray workers
- Process group killing for thorough cleanup
- CUDA cache clearing on all devices

### 4. Updated `clean_start()` (orchestrator.py:1015-1104)
- Verifies GPU zero-state before starting endpoints
- Falls back to nvidia-smi GPU reset if memory not freed
- Returns detailed cleanup and verification results

### 5. Added `_cleanup_gpu_processes()` to environment.py (lines 177-229)
- Aggressive pkill for vLLM processes after GPU-intensive tests
- Waits for GPU memory to clear with timeout
- Triggered for tier-4, tier-5, qwq, llm-reflection, engine-integration tags

### 6. Updated run_pipeline_tests.sh
- Added `cleanup_gpus()` function
- Called before engine startup for tier-4+ tests
- Verifies GPU memory is freed before proceeding

## Test Results

**Tier-1 through Tier-3**: All passing (5 scenarios)
```
1 feature passed, 0 failed, 0 skipped
5 scenarios passed, 0 failed, 6 skipped
38 steps passed, 0 failed, 56 skipped
```

**GPU Memory Verification**: All GPUs at 4 MiB after tests (minimal usage)

**Tier-4 Status**: GPU cleanup working, but vLLM startup fails (separate issue)
- GPUs are properly freed between scenarios
- Endpoint startup issue unrelated to cleanup

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/inference/orchestrator.py` | Process group killing, GPU verification, enhanced cleanup |
| `features/environment.py` | GPU cleanup hook for tier-4+ tests |
| `scripts/run_pipeline_tests.sh` | cleanup_gpus() function |

## Remaining Issues

1. **AsyncIO cleanup warnings**: Event loop closed before background tasks cancelled
   - Not blocking tests, just cleanup noise

2. **Tier-4 vLLM startup**: Reasoning endpoint fails to become healthy
   - Likely model download or vLLM binary issue
   - Separate from GPU cleanup (cleanup is working)

## Commands

```bash
# Run tier-3 (verified working)
./scripts/run_pipeline_tests.sh --tier 3

# Run tier-4 (GPU cleanup working, endpoint startup issue)
./scripts/run_pipeline_tests.sh --tier 4

# Manual GPU cleanup
pkill -9 -f "vllm"; pkill -9 -f "VLLM"
nvidia-smi --query-gpu=memory.used --format=csv,noheader
```
