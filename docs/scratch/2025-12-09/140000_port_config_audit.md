# Port Configuration Audit and Fixes

## Summary

Audited hardcoded port references across the codebase and updated to use engine-managed endpoints (agent-first architecture).

## Canonical Port Assignments (agents.conf)

| Endpoint     | Port | Model                                    |
|--------------|------|------------------------------------------|
| orchestrator | 8080 | nvidia/Orchestrator-8B                   |
| reasoning    | 8081 | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |
| coding       | 8082 | deepseek-ai/deepseek-coder-6.7b-instruct |
| fast         | 8083 | mistralai/Mistral-7B-Instruct-v0.3       |
| fast-2       | 8085 | mistralai/Mistral-7B-Instruct-v0.3       |

## Fixes Applied

### 1. `inference/config.py`
- Fixed `vllm_url` default: 8084 → 8080
- Fixed `_discover_vllm_endpoint()` orchestrator: 8084 → 8080
- Fixed fallback default: 8084 → 8080

### 2. `mcp_server.py`
- `model_launch_coding`: Now uses `ensure_endpoint("coding")` instead of hardcoded 8082
- `model_generate_code`: Now uses engine to get coding endpoint dynamically

### 3. `agents/modeladd/tools.py`
- `get_coding_model()`: Uses engine proxy instead of hardcoded 8082
- `check_coding_endpoint()`: Prefers engine status, falls back to HTTP check

## Remaining Work

### CLI (`cli.py`)
- Lines 1083, 1186-1194: Still reference port 8082
- Should use engine proxy

### Models Registry (`models/registry.py`)
- Lines 221, 253, 282, 312, 344, 375: `default_port` values
- These define model capabilities, may be intentional defaults

### Core Config (`core/config.py`)
- Lines 95, 104: VLLMEndpointConfig and OptillmConfig defaults
- Lines 444, 450: Config loading

### Inference layer
- `orchestrator.py:178`: url default
- `scheduler.py:188, 569`: optillm url
- `router.py:454`: url default
- `manager.py:211`: common_ports list

## Architectural Decision

The engine is now the source of truth for endpoint ports. Code should:
1. Use `ensure_endpoint(name)` to start/verify endpoints
2. Get port from the result, not from hardcoded values
3. Only use hardcoded ports as last-resort fallbacks (with LEGACY_FALLBACK warnings)

## Config Files

Two places define endpoints:
- `config/agents.conf`: Agent definitions with ports (gaius.agents.*)
- `config/base.conf`: Inference endpoints (gaius.inference.endpoints.*)

These should be kept in sync. Consider consolidating to single source.
