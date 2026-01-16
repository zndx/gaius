# Ambient Cycle Feature Plan

## Current Status

The ambient cycle successfully runs baseline phases but fails during reasoning phase:

```
✓ [AMBIENT_PHASE_BASELINE_HEALTH] Baseline health verified (3/3 healthy)
✓ [AMBIENT_PHASE_BASELINE_WORKLOAD] Baseline workload complete (3/3 tasks)
✓ [AMBIENT_PHASE_REASONING_EVICTION] Preparing for reasoning workload
✗ [AMBIENT_PHASE_ERROR] Failed to prepare for reasoning: Failed to allocate reasoning:
```

## Expected Full Cycle Behavior

A complete `/ambient cycle` should demonstrate dynamic workload transitions:

### Phase 1: Baseline Health Check
- Verify baseline endpoints are healthy (fast, coding, orchestrator)
- Current: **WORKING** (3/3 healthy)

### Phase 2: Baseline Workload
- Run sample inference tasks across all baseline endpoints
- Measure latency per endpoint
- Current: **WORKING** (fast: ~700ms, coding: ~5s, orchestrator: ~5s)

### Phase 3: Reasoning Eviction (Model Changeover)
- Evict baseline endpoints from GPUs 0-3
- Track which endpoints were evicted for later restoration
- Current: **PARTIALLY WORKING** (eviction logic exists but allocation fails)

### Phase 4: Reasoning Workload
- Start reasoning model (Qwen/QwQ-32B) on freed GPUs
- Run reasoning tasks (complex analysis, chain-of-thought)
- Measure reasoning latency and quality
- Current: **NOT WORKING** - allocation fails with empty error message

### Phase 5: Baseline Restoration
- Stop reasoning model
- Restore evicted baseline endpoints
- Verify baseline health restored
- Current: **UNTESTED** - never reaches this phase

### Phase 6: Cycle Complete
- Report full cycle metrics
- Verify return to stable baseline
- Current: **UNTESTED** - never reaches this phase

## Root Cause Analysis

### Issue 1: Empty Error Message
The error `Failed to allocate reasoning:` shows no reason. The error message isn't propagating from the orchestrator's `_start_capability_endpoint()` method.

**File**: `src/gaius/engine/services/ambient_service.py:541-544`

### Issue 2: Reasoning Model Configuration
QwQ-32B requires:
- `tensor_parallel_size=4` (4 GPUs)
- `memory_mb=80000` (~80GB)

With 6x RTX 4090 (24GB each):
- Total available: 144GB across 6 GPUs
- Orchestrator facilitates eviction plan for non-orchestrator endpoints
- After baseline eviction: Should have Orchistrator endpoint active with 4 GPUs free
- But orchestrator may not be correctly freeing GPUs or assigning them

**File**: `src/gaius/engine/services/orchestrator_service.py:823-840`

### Issue 3: vLLM Controller start_model()
The `start_model()` method was recently added but may have issues with:
- GPU allocation planning
- Command construction (shlex.split was just fixed)
- Process startup verification

**File**: `src/gaius/engine/backends/vllm_controller.py:300-363`

### Issue 4: No ACP Escalation
When reasoning allocation fails, it should:
1. Detect persistent failure
2. Escalate to ACP (Claude Code)
3. ACP investigates and either fixes or creates GitHub issue

Currently the failure doesn't trigger HealthObserver escalation because it's treated as a "soft" failure within the ambient cycle, not a health check failure.

## GPU Layout

```
Current (Baseline Active):
GPU 0: vLLM fast (Qwen3-8B) - 23GB used
GPU 1: vLLM coding (Qwen3-32B-Coder-TP2) - 23GB used
GPU 2: vLLM coding (TP2 shard) - 22GB used
GPU 3: Free
GPU 4: Free
GPU 5: Free

After Eviction (Should Be):
GPU 0: Free
GPU 1: Free
GPU 2: Free
GPU 3: Free
GPU 4: Free
GPU 5: Free

Reasoning Active (Target):
GPU 0-3: QwQ-32B (TP=4) - ~80GB across 4 GPUs
GPU 4-5: Free (for fast endpoint if needed)
```

## Required Fixes

### 1. Error Message Propagation
Ensure all error messages from orchestrator → ambient service → CLI are fully propagated with actionable details.

### 2. GPU Allocation Verification
Add logging/verification that GPUs are actually freed after eviction before attempting reasoning model startup.

### 3. Integrate with HealthObserver
The ambient cycle should report persistent failures to HealthObserver for Tier 2 (ACP) escalation. This would trigger Claude Code to investigate and either:
- Fix the configuration issue
- Open a GitHub issue documenting the persistent failure

### 4. Baseline Restoration
Implement and test the restoration phase to ensure we always return to a healthy baseline state, even if reasoning fails.

## Testing Plan

1. Run `/ambient cycle --baseline-only` - verify baseline phases work
2. Run `/ambient cycle --dry-run` - show what eviction/restoration would do
3. Run `/ambient cycle` with verbose logging to trace GPU allocation
4. Verify ACP escalation when allocation persistently fails

## Files to Modify

- `src/gaius/engine/services/ambient_service.py` - Error propagation, HealthObserver integration
- `src/gaius/engine/services/orchestrator_service.py` - GPU allocation logging
- `src/gaius/engine/backends/vllm_controller.py` - start_model verification
- `src/gaius/engine/services/health_observer_service.py` - Ambient failure escalation
