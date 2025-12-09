# Agent-First Engine Architecture Implementation

## Summary

Implemented the agent-first architecture where CLI commands and agents communicate with the engine rather than spawning vLLM processes directly. The engine is now the single source of truth for GPU resources and model lifecycle.

## Key Changes

### 1. New `ensure_endpoint` Method

Added to `OrchestratorService` (src/gaius/engine/services/orchestrator_service.py:168-256):
- Checks if endpoint is already healthy
- Validates resource availability via ResourceManager
- Checks for contiguous GPUs when tensor_parallel > 1
- Starts endpoint only if resources are available
- Returns informative status (healthy, insufficient_resources, no_contiguous_gpus)

### 2. Engine Server Handler

Added `ensure` action handler in engine server (src/gaius/engine/server.py:675-698):
- Routes to OrchestratorService.ensure_endpoint()
- Returns comprehensive status including healthy flag, port, gpu_ids, model

### 3. OrchestratorProxy Client Method

Added `ensure_endpoint()` to proxy client (src/gaius/client/engine_proxy.py:71-91):
- Provides simple interface for CLI and agents
- Returns dict with healthy, status, port, gpu_ids, message

### 4. ModelAdd Orchestrator Updates

Updated `_tool_launch_coding` (src/gaius/agents/modeladd/orchestrator.py:558-644):
- Uses engine client's `ensure_endpoint` instead of legacy orchestrator
- Handles specific failure reasons (insufficient_resources, no_contiguous_gpus)
- Fails fast if engine not running

Updated `_tool_stop_coding` (src/gaius/agents/modeladd/orchestrator.py:646-662):
- Uses engine proxy to stop endpoints

Updated `_consult_orchestrator` (src/gaius/agents/modeladd/orchestrator.py:205-274):
- Prefers engine scheduler for inference when available
- Falls back to router for backwards compatibility

### 5. CLI Fail-Fast Behavior

Added engine check in `/model add` command (src/gaius/cli.py:846-854):
- Checks `use_engine_proxy()` before running agent workflow
- Returns clear error with hint to start engine
- Offers `--legacy` flag as alternative

### 6. Router Updates

Updated `_try_start_endpoint_on_demand` (src/gaius/inference/router.py:584-719):
- Prefers engine client for on-demand start
- Falls back to legacy nvidia-smi based startup
- Maintains backwards compatibility

## Architecture Flow

```
CLI/TUI Commands ──────┐
                       │
Agent Workflows ───────┼──► use_engine_proxy() ─► Engine Client ──► GaiusEngine
                       │         │                                       │
MCP Server ────────────┘         │                          ┌────────────┴────────┐
                          Check if engine                   │                     │
                          is available               OrchestratorSvc        ResourceManager
                                                           │                     │
                                              ensure_endpoint()            GPU Allocations
                                                           │
                                                      VLLMController
                                                           │
                                                      vLLM Processes
```

## Key Benefits

1. **Centralized GPU Management**: All GPU allocations tracked by ResourceManager
2. **Conflict Prevention**: No more GPU allocation conflicts between CLI and engine
3. **Resource Awareness**: `ensure_endpoint` checks resources before starting
4. **Clear Errors**: Informative error messages when resources unavailable
5. **Backwards Compatible**: Legacy mode still works with `--legacy` flag

## Testing Notes

The engine must be restarted to pick up config changes (e.g., new coding model). The stale state in the running engine was still showing Qwen2.5-Coder-32B instead of the configured deepseek-coder-6.7b-instruct.

To restart with fresh config:
```bash
# Stop current engine endpoints
gaius-engine stop

# Start with clean config
gaius-engine start
```

## Files Modified

| File | Change |
|------|--------|
| src/gaius/engine/services/orchestrator_service.py | Added ensure_endpoint(), _find_contiguous_gpus() |
| src/gaius/engine/server.py | Added "ensure" action handler |
| src/gaius/client/engine_proxy.py | Added ensure_endpoint() to OrchestratorProxy |
| src/gaius/client/grpc_client.py | Added ensure action routing |
| src/gaius/agents/modeladd/orchestrator.py | Updated tools to use engine client |
| src/gaius/cli.py | Added fail-fast check for engine |
| src/gaius/inference/router.py | Updated on-demand start to prefer engine |
