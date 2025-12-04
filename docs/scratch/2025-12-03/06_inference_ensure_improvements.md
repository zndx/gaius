# /inference ensure Improvements

**Date**: 2025-12-03
**Issue**: Poor progress feedback and duplicate process detection
**Status**: RESOLVED

## Problems Addressed

### 1. Uninformative Progress Messages
Previously, `/inference ensure` showed repetitive "Status: unknown" messages during startup:
```
[40%] Status: unknown
[41%] Status: unknown
...
```

### 2. No Detection of External Processes
The CLI/TUI orchestrator didn't detect vLLM processes started by MCP or previous sessions, leading to:
- Duplicate process attempts on same port
- GPU memory conflicts
- Unnecessary timeouts

## Solutions

### 1. vLLM Output Regex Patterns (orchestrator.py)

Added pattern matching to parse vLLM stdout/stderr for meaningful progress:

```python
VLLM_PROGRESS_PATTERNS: list[tuple[str, str, float]] = [
    (r"Initializing .* engine", "Initializing engine", 0.05),
    (r"Loading model weights", "Loading model weights", 0.10),
    (r"Loading checkpoint shards.*?(\d+)%", "Loading checkpoint: {0}%", 0.15),
    (r"CUDA graphs", "Building CUDA graphs", 0.60),
    (r"Uvicorn running", "Server running", 0.95),
    (r"Application startup complete", "Startup complete", 0.98),
    # Error patterns
    (r"OutOfMemoryError|OOM", "Out of memory error", -1.0),
    (r"Free memory.*less than", "Insufficient GPU memory", -1.0),
]
```

Added `get_startup_progress()` method to extract status from buffers:
```python
def get_startup_progress(self, endpoint: str) -> tuple[str, float]:
    """Get startup progress from vLLM output buffers."""
```

### 2. Port Detection (orchestrator.py)

Added `_check_port_in_use()` to detect already-responding endpoints:
```python
async def _check_port_in_use(self, url: str) -> bool:
    """Check if an endpoint is already responding at the given URL."""
```

Modified `start_endpoint()` to check before starting:
```python
if await self._check_port_in_use(config.url):
    logger.info(f"Endpoint {endpoint} already responding, assuming healthy")
    return True
```

### 3. HTTP Health Check in Status (manager.py)

Updated `get_status()` to also check via HTTP (catches external processes):
```python
# Also check via HTTP (catches external processes like MCP-started ones)
if not default_ready:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{base_url}/v1/models", timeout=3)
        if r.status_code == 200:
            default_ready = True
```

## Results

### Before:
```
[0%] Checking orchestrator status
[20%] Starting orchestrator endpoint
[40%] Waiting for model to load
[40%] Status: unknown
[41%] Status: unknown
... (repeated for 120s)
[0%] Timeout after 120s
```

### After (fresh start):
```
[0%] Checking orchestrator status
[20%] Starting orchestrator endpoint
[40%] Waiting for model to load
[43%] Initializing engine
[55%] Loading model weights
[70%] Building CUDA graphs
[94%] Startup complete
[100%] Ready
```

### After (already running):
```
[0%] Checking orchestrator status
[100%] Already running
```

## Files Modified

- `src/gaius/inference/orchestrator.py`
  - Added `VLLM_PROGRESS_PATTERNS` constant
  - Added `get_startup_progress()` method
  - Added `get_recent_output()` method
  - Added `_check_port_in_use()` method
  - Modified `start_endpoint()` to check port first

- `src/gaius/inference/manager.py`
  - Modified `get_status()` to include HTTP health check
  - Modified `ensure_orchestrator_running()` to use vLLM progress parsing

## Future Improvements

1. Add more detailed patterns for model-specific loading stages
2. Parse checkpoint loading progress (e.g., "Loading checkpoint shards: 45%")
3. Add estimated time remaining based on historical data
4. Consider shared state between CLI and MCP orchestrators
