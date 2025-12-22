# HuggingFace Cache Consolidation

## Issue

There are two HuggingFace cache directories being used:
- `/raid/cache/rch/huggingface/` (user-specific)
- `/raid/cache/huggingface/` (shared)

This causes:
1. Duplicate model downloads
2. Inconsistent HF_HOME settings across scripts
3. Confusion about which cache is being used

## Current State

The Devstral model was downloaded to `/raid/cache/rch/huggingface/`:
```
/raid/cache/rch/huggingface/models--mistralai--Devstral-Small-2-24B-Instruct-2512/
```

## Recommendation

Consolidate to `/raid/cache/huggingface/` (the shared cache):

1. **Move existing models**:
   ```bash
   mv /raid/cache/rch/huggingface/models--* /raid/cache/huggingface/
   ```

2. **Update environment variables**:
   - Set `HF_HOME=/raid/cache/huggingface` in shell profile
   - Update any scripts that reference `/raid/cache/rch/huggingface`

3. **Verify symlink approach** (alternative):
   ```bash
   ln -s /raid/cache/huggingface /raid/cache/rch/huggingface
   ```

## Action Items

- [ ] Decide on canonical cache location
- [ ] Move Devstral model to shared cache
- [ ] Update HF_HOME in devenv or profile
- [ ] Verify vLLM can find models in new location
