# InferenceClient Model Discovery Fix

**Date**: 2025-12-03
**Issue**: LLM-based mini-grid explanations failing with local inference
**Status**: RESOLVED

## Problem

When testing LLM-based mini-grid explanations, the InferenceClient was failing to use local vLLM inference:

```
WARNING:gaius.inference.client:Fallback backend (vllm) failed:
Error code: 404 - {'error': {'message': 'The model `Qwen/Qwen3-Coder-30B-A3B-Instruct` does not exist.'}}
```

Two issues were identified:

1. **Wrong vLLM URL**: Default was `http://localhost:8088/v1` (legacy single endpoint), but the orchestration endpoint runs on `http://localhost:8084/v1`

2. **Wrong Model Name**: The client was requesting `Qwen/Qwen3-Coder-30B-A3B-Instruct` but the orchestration endpoint has `nvidia/Orchestrator-8B` loaded

## Solution

### 1. Updated Default vLLM URL

Changed in `src/gaius/inference/config.py`:

```python
# Before
vllm_url: str = "http://localhost:8088/v1"

# After
# Default to orchestration endpoint (8084) which supports general-purpose tasks
# Other endpoints: reasoning=8081, coding=8082, fast=8083
vllm_url: str = "http://localhost:8084/v1"
```

### 2. Added Dynamic Model Discovery

Added `_discover_vllm_model()` method in `src/gaius/inference/client.py`:

```python
async def _discover_vllm_model(self) -> str | None:
    """Discover available model from vLLM endpoint.

    Queries /v1/models and caches the first available model.
    """
    if hasattr(self, "_vllm_model") and self._vllm_model:
        return self._vllm_model

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.config.vllm_url.rstrip('/v1')}/v1/models",
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("data"):
                    self._vllm_model = data["data"][0]["id"]
                    return self._vllm_model
    except Exception:
        pass
    return None
```

The fallback chain now calls `_discover_vllm_model()` before using vLLM:

```python
# In the fallback chain
if backend_name == "vllm":
    await self._discover_vllm_model()
```

And `_get_model_for_backend()` uses the discovered model:

```python
def _get_model_for_backend(self, backend: str) -> str:
    if backend == "vllm":
        # Use cached model if available
        return getattr(self, "_vllm_model", None) or self.config.model
```

## Verification

```python
# Test showed successful local inference:
>>> result = await explain_position(ctx, client=client)
>>> print(f'Backend: vLLM ({client._vllm_model})')
Backend: vLLM (nvidia/Orchestrator-8B)

# Logs confirmed:
INFO:gaius.inference.client:Fallback to vllm succeeded
```

## Multi-Endpoint Architecture

The system now supports dynamic model discovery across multiple endpoints:

| Endpoint | Port | Model | Purpose |
|----------|------|-------|---------|
| reasoning | 8081 | Qwen/QwQ-32B | Complex analysis |
| coding | 8082 | Qwen/Qwen3-Coder-30B-A3B-Instruct | Code generation |
| fast | 8083 | mistralai/Mistral-7B-Instruct-v0.3 | Quick responses |
| orchestration | 8084 | nvidia/Orchestrator-8B | General-purpose |

The `GAIUS_VLLM_URL` environment variable can override the default endpoint:
```bash
export GAIUS_VLLM_URL="http://localhost:8082/v1"  # Use coding endpoint
```

## Impact on Future Orchestrator Agent

The orchestrator agent should:
1. Start appropriate endpoints based on task type
2. Set `GAIUS_VLLM_URL` or update client config for task routing
3. Use model discovery to verify correct model is loaded
4. Handle endpoint failures with automatic fallback
