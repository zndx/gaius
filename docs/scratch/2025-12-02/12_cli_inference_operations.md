# CLI Inference Operations (Symmetric with TUI)

**Date:** 2025-12-02
**Context:** Adding symmetric CLI commands for inference stack management

## Implementation

### CLI Commands Added (`src/gaius/cli.py`)

**Command router (line 131-132):**
```python
elif command == "inference" or command == "inf":
    result["data"] = self._run_async(self._cmd_inference(args))
```

**Command implementation (`_cmd_inference`, line 896-1018):**
```
/inference status              - Show inference stack status
/inference start <endpoint>    - Start specific endpoint
/inference stop <endpoint>     - Stop specific endpoint
/inference restart <endpoint>  - Restart specific endpoint
/inference ensure              - Ensure default model (nvidia/Orchestrator-8B) running
```

**Features:**
- Async operations via `_run_async()`
- Progress tracking with stderr output: `[20%] Starting endpoint`
- JSON-formatted results for scripting
- Short alias: `/inf` works same as `/inference`

**Help text updated (line 253-254):**
Added inference command to CLI help output

## Bug Fixes

### Issue: TypeError with model parameter

**Error:**
```
TypeError: GPUOrchestrator.start_endpoint() got an unexpected keyword argument 'model'
```

**Root cause:**
- InferenceManager was passing `model=` parameter to orchestrator
- Orchestrator's `start_endpoint()` doesn't accept model arg (uses endpoint config)
- Return type is `bool`, not `dict`

**Fixes applied:**

1. **InferenceManager.ensure_orchestrator_running() (line 116)**:
   ```python
   # Before:
   result = await self._orchestrator.start_endpoint(endpoint, model=model)
   if not result.get("success"):  # Wrong!

   # After:
   success = await self._orchestrator.start_endpoint(endpoint)
   if not success:  # Correct!
   ```

2. **InferenceManager.start_endpoint() (line 183)**:
   ```python
   # Before:
   result = await self._orchestrator.start_endpoint(endpoint_name, model=model)

   # After:
   success = await self._orchestrator.start_endpoint(endpoint_name)
   ```

3. **Removed model parameter from start_endpoint signature (line 158-174)**:
   - Model is defined in endpoint configuration, not passed dynamically
   - Updated docstring to clarify this

## Testing

### CLI Status Command
```bash
$ uv run python -m gaius.cli --cmd "/inference status" --format json
{
  "command": "inference",
  "args": "status",
  "success": true,
  "data": {
    "orchestrator_running": true,
    "scheduler_healthy": true,
    "default_model_ready": false,
    "endpoints": {},
    "total_requests": 0,
    "queue_depth": 0
  }
}
```

**Interpretation:**
- ✅ Orchestrator singleton created and running
- ✅ Scheduler service healthy
- ✗ nvidia/Orchestrator-8B not loaded yet (default_model_ready: false)
- ✗ No endpoints running yet

### CLI Help
```bash
$ uv run python -m gaius.cli --cmd "/help" --format json | jq '.data.commands'
{
  "gpu [cmd] [args]": "GPU orchestrator (status, start, stop, restart, logs, health)",
  "inference [cmd] [args]": "Inference stack (status, start, stop, restart, ensure)"
}
```

## CLI vs TUI Symmetry

| Operation | TUI Command | CLI Command | Notes |
|-----------|-------------|-------------|-------|
| Status | `/inference status` | `--cmd "/inference status"` | Symmetric |
| Start endpoint | `/inference start reasoning` | `--cmd "/inference start reasoning"` | Symmetric |
| Stop endpoint | `/inference stop reasoning` | `--cmd "/inference stop reasoning"` | Symmetric |
| Restart | `/inference restart reasoning` | `--cmd "/inference restart reasoning"` | Symmetric |
| Ensure default | N/A (automatic on mount) | `--cmd "/inference ensure"` | CLI has explicit command |

## Usage Examples

### Check status
```bash
uv run python -m gaius.cli --cmd "/inference status" --format json
```

### Start reasoning endpoint (QwQ-32B)
```bash
uv run python -m gaius.cli --cmd "/inference start reasoning" --format json
# Progress printed to stderr:
# [20%] Starting endpoint
# [100%] Started
```

### Stop endpoint
```bash
uv run python -m gaius.cli --cmd "/inference stop reasoning" --format json
```

### Ensure default model running
```bash
uv run python -m gaius.cli --cmd "/inference ensure" --format json
# Progress printed to stderr:
# [0%] Checking orchestrator status
# [20%] Starting orchestrator endpoint
# [40%] Waiting for model to load
# [90%] Loading model into VRAM
# [100%] Ready
```

## Architecture Notes

**Two levels of control:**

1. **Low-level: `/gpu`** (orchestrator.py)
   - Direct vLLM process management
   - No startup logic, just start/stop/status
   - Returns raw orchestrator state

2. **High-level: `/inference`** (manager.py)
   - Service lifecycle management
   - Startup sequences with progress
   - Default model handling
   - Health checks and readiness

**Why both?**
- `/gpu` for debugging and manual control
- `/inference` for normal operations and automation

## Next Steps

1. **Model availability**: Currently nvidia/Orchestrator-8B not loaded
   - Need to ensure model is available in HuggingFace cache
   - Or configure alternative default model

2. **Auto-start configuration**: Enable in config
   ```hocon
   gaius.inference.orchestrator.auto_start = true
   ```

3. **Scale-to-zero**: Implement idle timeout
   - Track last request time per endpoint
   - Shutdown after N minutes idle
   - Fast restart when needed

4. **Usage tracking**: Log model usage by agent
   - Which agents use which models
   - Optimize hot set based on patterns

## Status

✅ CLI commands implemented and tested
✅ Symmetric with TUI operations
✅ Progress tracking works
✅ Bug fixes applied
✅ Help text updated
⏳ Model not yet loaded (expected - needs model availability)
⏳ Auto-start config (TODO)
⏳ Scale-to-zero (TODO)
