# InitPanel and gRPC Connection Fixes

## Issues Addressed

### 1. InitPanel Showing Static Endpoints
**Problem**: InitPanel was showing hardcoded endpoints from `config/agents.conf` (orchestrator, fast, fast-2, coding) instead of actual endpoints being loaded (e.g., deepseek-R1-distill).

**Root Cause**: The `InitController._get_status_data()` only returned endpoints from its internal `_state.endpoints` dictionary, which was populated from the config's `preload_endpoints` list, not from actual orchestrator state.

**Fix** (`init_controller.py`): Enhanced `_get_status_data()` to:
1. Start with preload tracking data
2. Query `_orchestrator_service.get_status()` for actual running endpoints
3. Merge dynamically started endpoints into the response
4. Update preload endpoints with actual orchestrator status if healthy

This ensures the engine is the source of truth, not just the config.

### 2. gRPC Fork Spam and ENHANCE_YOUR_CALM Errors
**Problem**: Log spam with:
- `fork_posix.cc:71: Other threads are currently calling into gRPC, skipping fork() handlers`
- `GOAWAY received; Error... ENHANCE_YOUR_CALM`

**Root Causes**:
1. The `get_grpc_client()` singleton had a race condition causing concurrent connection attempts
2. sklearn/UMAP use joblib with multiprocessing (fork) by default, which conflicts with gRPC's C-core

**Fixes**:

1. **Connection lock** (`grpc_client.py`): Added asyncio lock to prevent concurrent connect attempts:
```python
async def get_grpc_client() -> GrpcEngineClient:
    if not _grpc_client.is_connected:
        async with _get_connect_lock():
            if not _grpc_client.is_connected:
                connected = await _grpc_client.connect()
```

2. **Use threading backend for joblib** (`app.py`, `cli.py`, `engine/server.py`):
```python
from joblib import parallel_config
parallel_config(backend="threading", n_jobs=-1)
```

The threading backend preserves parallelism while avoiding fork(). This works well for NumPy/sklearn/UMAP since they release the GIL in compiled code.

3. **Backup suppression** (`devenv.nix`): Added `GRPC_ENABLE_FORK_SUPPORT=0` as a fallback for any remaining fork scenarios (e.g., vLLM subprocess startup).

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/engine/init_controller.py` | Enhanced `_get_status_data()` to include actual orchestrator endpoints |
| `src/gaius/client/grpc_client.py` | Added lock to prevent concurrent connection attempts |
| `src/gaius/app.py` | Configure joblib threading backend at startup |
| `src/gaius/cli.py` | Configure joblib threading backend at startup |
| `src/gaius/engine/server.py` | Configure joblib threading backend at startup |
| `devenv.nix` | Added `GRPC_ENABLE_FORK_SUPPORT=0` as backup |
