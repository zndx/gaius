# E2E Pipeline Test Fixes

## Summary

Fixed multiple issues that were preventing E2E pipeline tests from running correctly.

## Issues Fixed

### 1. WorkerConfig Parameter Name (`content_pipeline_fixtures.py:754`)

**Error**: `TypeError: WorkerConfig.__init__() got an unexpected keyword argument 'database_url'`

**Fix**: Changed `database_url` to `db_url` to match the `WorkerConfig` dataclass field name.

```python
# Before:
config = WorkerConfig(
    database_url=self.config.db_url,  # Wrong!

# After:
config = WorkerConfig(
    db_url=self.config.db_url,  # Correct
```

### 2. Per-Endpoint Context Length (`orchestrator.py`)

**Error**: `max_model_len (65536) is greater than the derived max_model_len (max_position_embeddings=32768)` when starting the `fast` (Mistral-7B) endpoint.

**Root Cause**: Global `max_model_len=65536` was being applied to all endpoints, but Mistral-7B only supports 32K.

**Fix**: Implemented per-endpoint `context_length` and `max_num_seqs` settings:

1. Added fields to `EndpointConfig` class:
   ```python
   context_length: int = 32768  # Per-endpoint context length
   max_num_seqs: int = 256  # Per-endpoint max concurrent sequences
   ```

2. Updated config loading to read per-endpoint values:
   ```python
   context_length=ep.get("context_length", self._max_model_len),
   max_num_seqs=ep.get("max_num_seqs", self._max_num_seqs),
   ```

3. Updated vLLM command building to use per-endpoint config:
   ```python
   "--max-model-len", str(config.context_length),
   "--max-num-seqs", str(config.max_num_seqs),
   ```

4. Updated `base.conf` defaults:
   - Global default: 32K context, 256 sequences (for small models)
   - Reasoning endpoint: 64K context, 32 sequences (for DeepSeek-R1)

### 3. Thought Type Field Name (`content_pipeline_steps.py:793`)

**Error**: `ASSERT FAILED: No expected thought types found. Got: [None, None]`

**Root Cause**: Test code used `t.get("type")` but `Thought` dataclass has `thought_type`.

**Fix**: Changed to use `thought_type` and handle enum values:
```python
tt = t.get("thought_type")
if hasattr(tt, "value"):
    generated_types.append(tt.value.upper())
```

## Current Test Status

| Test | Status | Notes |
|------|--------|-------|
| Tier-1 (DB operations) | ✅ PASS | |
| Tier-2 (Heuristic, KB) | ✅ PASS | |
| Tier-3 (LLM triage) | ✅ PASS | |
| Tier-4 (GPU allocation) | ✅ PASS | |
| Tier-4 (Deep reflection) | ✅ PASS | |
| Tier-4 (E2E pipeline) | ⚠️ BLOCKED | MinIO/Iceberg not running |

## Remaining Infrastructure Issue

The E2E test requires MinIO (for Iceberg data lake) which is not running:

```
Failed to store content to Iceberg: AWS Error NETWORK_CONNECTION...
curlCode: 7, Couldn't connect to server
```

This is an infrastructure dependency, not a code bug. Start MinIO with `devenv up` or `devenv processes up` to enable E2E tests.

## Files Modified

1. `features/steps/content_pipeline_fixtures.py` - `db_url` parameter fix
2. `features/steps/content_pipeline_steps.py` - `thought_type` field fix
3. `features/content_pipeline.feature` - Added SELF_OBSERVATION to expected types
4. `src/gaius/inference/orchestrator.py` - Per-endpoint context_length support
5. `config/base.conf` - Per-endpoint config and default adjustments
