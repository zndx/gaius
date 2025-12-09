# Dynamic GPU Allocation Implementation

**Date**: 2025-12-08
**Status**: Complete

## Summary

Implemented dynamic GPU allocation for gaius-engine supporting 4 specialized endpoints in the default state, with automatic resource swapping when the 4-GPU reasoning model is needed.

## Default GPU Layout (6 GPUs Total)

| Endpoint | Model | GPUs | Port |
|----------|-------|------|------|
| orchestrator | nvidia/Orchestrator-8B | 2 (TP=2) | 8084 |
| fast | mistralai/Mistral-7B-Instruct-v0.3 | 1 | 8083 |
| fast-2 | mistralai/Mistral-7B-Instruct-v0.3 | 1 | 8085 |
| coding | Qwen/Qwen2.5-Coder-32B-Instruct | 2 (TP=2) | 8082 |

## Reasoning Mode Swap

When DeepSeek-R1-Distill-Qwen-32B (4-GPU) is needed:
1. **Stop**: coding + fast + fast-2 (frees 4 GPUs)
2. **Keep Running**: orchestrator (2 GPUs)
3. **Start**: reasoning (4 GPUs)

## Files Modified

### config/agents.conf
- Added `fast-2` endpoint (second Mistral-7B instance)
- Updated `coding` to use `Qwen/Qwen2.5-Coder-32B-Instruct` with TP=2
- Changed `preload-endpoints` to `["orchestrator", "fast", "fast-2", "coding"]`

### src/gaius/inference/orchestrator.py
- Rewrote `_load_config()` to use engine config (`gaius.agents`)
- Added endpoint discovery API:
  - `get_configured_endpoints()` - all endpoint names from config
  - `get_preload_endpoints()` - endpoints to start on boot
  - `get_endpoint_config()` - config for specific endpoint
  - `get_running_endpoints()` - currently healthy endpoints
  - `discover_running_endpoints()` - probe ports for running endpoints
  - `get_default_endpoint()` - best available endpoint

### src/gaius/inference/manager.py
- Removed hardcoded `self._default_endpoint = "orchestration"`
- Added dynamic discovery with `_discover_default_endpoint()`
- Added `get_default_endpoint()` with caching
- Added `get_configured_endpoints()` and `get_running_endpoints()`
- Fixed `stop_endpoint()` return type

### src/gaius/engine/resources/manager.py
- Added `SwapPlan` dataclass for GPU swapping
- Added `plan_swap_for_reasoning()` - plan default → reasoning transition
- Added `plan_restore_default()` - plan reasoning → default transition
- Added `can_execute_swap()` - validate swap plan
- Added `get_current_mode()` - detect current allocation mode

### Other files updated
- `src/gaius/app.py` - Changed "orchestration" to "orchestrator"
- `src/gaius/cli.py` - Changed default endpoint to "orchestrator"
- `src/gaius/inference/config.py` - Updated endpoint names
- `src/gaius/agents/evolution/orchestrated.py` - Updated default endpoint

## Verification

```bash
# Test endpoint discovery
uv run python -c "
from gaius.inference.orchestrator import get_orchestrator
orch = get_orchestrator()
print('Endpoints:', orch.get_configured_endpoints())
print('Preload:', orch.get_preload_endpoints())
"

# Test swap planning
uv run python -c "
from gaius.engine.config import load_config
from gaius.engine.resources import ResourceManager
rm = ResourceManager(load_config())
# ... simulate allocations ...
plan = rm.plan_swap_for_reasoning()
print('Stop:', plan.endpoints_to_stop)
print('Start:', plan.endpoints_to_start)
"

# Test CLI
uv run gaius-cli --cmd "/inference status"
```

## Next Steps

- Execute swap plans via orchestrator service (not yet wired)
- Add CLI commands for swap operations
- BDD tests for tier-4 reasoning transitions
