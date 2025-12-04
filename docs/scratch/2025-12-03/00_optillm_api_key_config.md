# optillm API Key Configuration Fix

## Summary

Updated the inference module to consistently use configuration-based API key loading instead of direct environment variable access.

## Changes Made

### 1. `src/gaius/inference/config.py`

- Added `optillm_api_key` field to `InferenceConfig` dataclass
- Priority: `GAIUS_OPTILLM_API_KEY` > `OPTILLM_API_KEY` > default `sk-optillm`
- Aligned with HOCON config naming convention

```python
optillm_api_key: str = field(
    default_factory=lambda: os.getenv("GAIUS_OPTILLM_API_KEY") or os.getenv("OPTILLM_API_KEY", "sk-optillm")
)
```

### 2. `src/gaius/inference/client.py`

- `_init_clients()`: Now uses `self.config.optillm_api_key` instead of direct env var
- `check_backends()`: Uses config for Authorization header

### 3. `src/gaius/inference/scheduler.py` (unchanged)

- Already has correct fallback pattern: tries HOCON config first, falls back to env var

## Configuration Hierarchy

1. **HOCON config** (`config/base.conf`): `gaius.inference.optillm.api_key`
2. **Environment**: `GAIUS_OPTILLM_API_KEY` or `OPTILLM_API_KEY`
3. **Default**: `sk-optillm`

## Testing

```bash
uv run python -c "
from gaius.inference.config import InferenceConfig
config = InferenceConfig.from_env()
print(f'optillm_api_key: {config.optillm_api_key[:12]}...')
"
```
