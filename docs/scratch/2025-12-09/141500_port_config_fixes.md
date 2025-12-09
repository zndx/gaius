# Port Configuration Fixes Summary

## Date: 2025-12-09

## Summary

Completed comprehensive port configuration audit and fixes to ensure consistency across the codebase. All hardcoded port references now align with agents.conf or use engine proxy for dynamic discovery.

## Canonical Port Assignments (agents.conf)

| Endpoint     | Port | Model                                    |
|--------------|------|------------------------------------------|
| orchestrator | 8080 | nvidia/Orchestrator-8B                   |
| reasoning    | 8081 | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |
| coding       | 8082 | deepseek-ai/deepseek-coder-6.7b-instruct |
| fast         | 8083 | mistralai/Mistral-7B-Instruct-v0.3       |
| fast-2       | 8085 | mistralai/Mistral-7B-Instruct-v0.3       |
| optillm      | 8088 | (proxy to vLLM backends)                 |

## Fixes Applied

### 1. `inference/config.py`
- Fixed `vllm_url` default: 8084 -> 8080 (orchestrator)
- Fixed `_discover_vllm_endpoint()` orchestrator: 8084 -> 8080
- Fixed fallback default: 8084 -> 8080

### 2. `mcp_server.py`
- `model_launch_coding`: Now uses `ensure_endpoint("coding")` instead of hardcoded 8082
- `model_generate_code`: Now uses engine to get coding endpoint dynamically

### 3. `agents/modeladd/tools.py`
- `get_coding_model_endpoint()`: Uses engine proxy instead of hardcoded 8082
- `check_coding_endpoint()`: Prefers engine status, falls back to HTTP check

### 4. `cli.py`
- `_get_coding_model()`: Uses engine proxy instead of hardcoded 8082
- Updated docstrings to reference engine-managed endpoints

### 5. `inference/scheduler.py`
- Fixed fallback endpoint URL: 8088 -> 8080 (orchestrator)
- Added LEGACY_FALLBACK warning for fallback path

### 6. `core/config.py`
- Fixed `VllmConfig.url` default: 8088 -> 8082 (coding endpoint)
- Fixed fallback in config loading: 8088 -> 8082

## Not Changed (Intentional)

### models/registry.py
- `default_port` values are model-specific preferences (not endpoint assignments)
- These define preferred ports when serving models directly, separate from engine endpoints

### optillm references (8088)
- Port 8088 is correct for optillm proxy
- This is a separate service from vLLM endpoints

## Architectural Decision

The engine is now the **single source of truth** for endpoint ports. Code should:
1. Use `ensure_endpoint(name)` to start/verify endpoints
2. Get port from the result, not from hardcoded values
3. Only use hardcoded ports as last-resort fallbacks (with LEGACY_FALLBACK warnings)

## ThinkPanel Verification

ThinkPanel now correctly shows engine status:
- `engine_healthy: True` when engine is connected
- `endpoints_running: N` shows count of healthy endpoints
- Real data from engine, not defaults

## Files Modified

- `src/gaius/inference/config.py`
- `src/gaius/mcp_server.py`
- `src/gaius/agents/modeladd/tools.py`
- `src/gaius/cli.py`
- `src/gaius/inference/scheduler.py`
- `src/gaius/core/config.py`
- `src/gaius/inference/manager.py` (handle list format for endpoints)
- `src/gaius/client/grpc_client.py` (added Cognition handler, Health check action)
