# Inference Architecture Fixes

**Date:** 2025-12-01
**Session:** Inference fixes and cognition demonstration

## Summary

Fixed the inference architecture to be properly local-first with XAI as the outsider evaluation model, and demonstrated the cognition system capabilities.

## Fixes Applied

### 1. Database URL Quoting Issue

**Problem:** `.env` file had quoted DATABASE_URL causing asyncpg to fail with "invalid DSN: scheme is expected to be either 'postgresql' or 'postgres', got ''"

**Solution:**
- Fixed `.env` to use unquoted value: `DATABASE_URL=postgres://localhost:5438/zndx_gaius?sslmode=disable`
- Added defensive quote stripping in `core/config.py`:
  ```python
  db_url = g.get("database.url", ...)
  if isinstance(db_url, str):
      db_url = db_url.strip('"').strip("'")
  ```

### 2. Inference Client Architecture

**Problem:** Inference was defaulting to OpenAI fallback instead of using local resources.

**Solution:** Restructured `inference/client.py` with tiered architecture:

```
optillm (8080) → vLLM (8088) with optimization techniques
     ↓ (fallback)
vLLM (8088) direct local inference
     ↓ (evaluation)
XAI Grok (outsider perspective for evals)
     ↓ (last resort)
OpenAI (if API key available)
```

**Key changes:**
- Added XAI backend support to `InferenceBackend` enum
- Added `xai_url`, `xai_api_key`, `xai_model` to `InferenceConfig`
- Client now initializes all available backends as a pool
- Fallback chain properly tries local backends first
- New `evaluate()` method prefers XAI for objective evaluation
- Added `check_backends()` for health monitoring
- Added `backend` field to `CompletionResult` for traceability

### 3. optillm API Key

**Problem:** optillm was returning 401 due to incorrect default API key.

**Solution:** The optillm server was started with `sk-optillm` as the API key. Updated code to use `sk-optillm` as default (matching the running service).

## Files Modified

- `/home/rch/local/src/zndx/gaius/.env` - Removed quotes from DATABASE_URL
- `src/gaius/inference/config.py` - Added XAI backend and config fields
- `src/gaius/inference/client.py` - Restructured with tiered local-first architecture
- `src/gaius/core/config.py` - Added defensive quote stripping for database URL

## Verification

### Backend Availability Test
```
optillm: UP (with sk-optillm auth)
vllm: UP (Qwen/Qwen3-Coder-30B-A3B-Instruct)
xai: UP (grok-3-latest)
openai: available if key set
```

### Cognition MCP Tools Tested
- `trigger_cognition` - Generated 3 thoughts (patterns, curiosities)
- `what_are_you_thinking` - Produced synthesis of knowledge base
- `start_session` - Session management working
- `reflect` - Quick reflection on specific topics working

### Sample Cognition Output
```json
{
  "thoughts": [
    {"type": "pattern", "title": "Distributed Systems & Consensus Algorithms"},
    {"type": "pattern", "title": "Philosophy and Cognitive Science Events"},
    {"type": "curiosity", "title": "How might swarm intelligence..."}
  ],
  "synthesis": "The knowledge base reveals a striking convergence..."
}
```

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                    Gaius Inference                       │
├─────────────────────────────────────────────────────────┤
│  Primary: optillm (8080)                                │
│  ├── Proxies to vLLM (8088)                            │
│  ├── Adds optimization techniques (COT, MOA, etc.)     │
│  └── Model: Qwen/Qwen3-Coder-30B-A3B-Instruct         │
├─────────────────────────────────────────────────────────┤
│  Local Fallback: vLLM direct (8088)                     │
│  └── Direct inference without optimization              │
├─────────────────────────────────────────────────────────┤
│  Evaluation: XAI Grok                                   │
│  ├── "Outsider" model for objective assessment         │
│  └── Model: grok-3-latest                              │
├─────────────────────────────────────────────────────────┤
│  Last Resort: OpenAI                                    │
│  └── Only if local backends unavailable                 │
└─────────────────────────────────────────────────────────┘
```

## Next Steps

1. Restart terminal/shell to pick up corrected `.env`
2. Test UI startup greeting with `uv run gaius`
3. Verify cognition notes appear in scratch directory
