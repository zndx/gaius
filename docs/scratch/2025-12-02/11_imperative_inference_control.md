# Imperative Inference Control with Progress Tracking

**Date:** 2025-12-02
**Context:** Implementing "scale to zero" architecture with visible startup sequence

## Architecture Shift

Moving from "on-demand" to "service lifecycle" model:
- Inference stack (orchestrator + models) runs as background service
- TUI/CLI are clients that attach to running services
- nvidia/Orchestrator-8B is the default model, starts at TUI startup
- Progress visible through background tasks panel

## Implementation

### 1. InferenceManager (`src/gaius/inference/manager.py`)

New high-level service manager providing:

**Core Methods:**
- `ensure_orchestrator_running()` - Startup sequence with progress callbacks
- `get_status()` - Current state of all endpoints
- `start_endpoint()` - Start specific endpoint
- `stop_endpoint()` - Stop specific endpoint
- `restart_endpoint()` - Restart endpoint

**Status Tracking:**
```python
@dataclass
class InferenceStatus:
    orchestrator_running: bool
    endpoints_running: dict[str, ProcessStatus]
    scheduler_healthy: bool
    default_model_ready: bool  # nvidia/Orchestrator-8B
    total_requests: int
    queue_depth: int
```

**Progress Reporting:**
- Callback interface: `progress_callback(task_name, progress_0_1, message)`
- Integrates with TUI BackgroundTask system
- Shows status during model loading (STARTING → HEALTHY)

### 2. TUI Startup Sequence (`src/gaius/app.py`)

**Added `_start_inference_stack()` method (line 1913-1966):**
- Creates BackgroundTask for visibility
- Calls `ensure_orchestrator_running()` with progress callback
- Updates task status and progress in real-time
- Refreshes ThinkPanel to show progress

**Wired into `on_mount()` (line 1904-1905):**
```python
# Start inference stack (orchestrator + nvidia/Orchestrator-8B)
self._start_inference_stack()
```

### 3. /inference Commands (`src/gaius/app.py`)

**New slash commands (line 2540-2542):**
```
/inference status              - Show all endpoints and queue status
/inference start <endpoint>    - Start specific endpoint
/inference stop <endpoint>     - Stop specific endpoint
/inference restart <endpoint>  - Restart specific endpoint
```

**Implementation (`_handle_inference_command`, line 1305-1431):**
- Symmetric async operations for all subcommands
- Status shows: orchestrator state, endpoints, scheduler, metrics
- Start/stop/restart provide feedback and error handling
- All operations are non-blocking (asyncio.create_task)

**Help text updated (line 1922):**
Added `/inference` to command list

### 4. Configuration

**Existing config** (`config/base.conf`):
- Line 154-159: nvidia/Orchestrator-8B configured at port 8084, GPU 4
- Line 198: `auto_start = false` (currently manual, will change)
- Line 193-222: Full orchestrator configuration

## Architecture Benefits

1. **Visibility**: Background tasks panel shows model loading progress
2. **Control**: Imperative commands for all lifecycle operations
3. **Symmetric**: Same operations work in TUI and CLI (CLI TODO)
4. **Non-blocking**: UI remains responsive during startup
5. **Fail-safe**: Clear error reporting if startup fails

## What's Running

**On TUI startup:**
1. TUI mounts
2. Background task: "Starting nvidia/Orchestrator-8B"
3. Progress: "Checking orchestrator status" (0%)
4. Progress: "Starting orchestrator endpoint" (20%)
5. Progress: "Waiting for model to load" (40%)
6. Progress: "Loading model into VRAM" (40-90%, time-based)
7. Complete: "nvidia/Orchestrator-8B ready" (100%)

**Model purpose:**
- nvidia/Orchestrator-8B handles:
  - TUI main event loop reasoning
  - Command interpretation
  - Agent workflow coordination
  - Future: Gang scheduling with ortools

## Next Steps

1. **CLI symmetry** - Add same commands to gaius-cli
2. **Auto-start config** - Enable `auto_start = true` for orchestration endpoint
3. **Scale-to-zero** - Idle timeout and graceful shutdown
4. **Usage tracking** - Log which models are used by which agents
5. **Dynamic model mix** - Adapt hot set based on workflow stage

## Testing

TUI starts without errors. To test:

```bash
uv run gaius
# Press 'g' to see ThinkPanel with background tasks
# Run /inference status to see endpoint state
# Run /inference start reasoning to start another endpoint
```

## Status

✅ InferenceManager created
✅ Startup sequence with progress tracking
✅ /inference commands implemented
✅ Help text updated
✅ TUI starts successfully
⏳ CLI operations (TODO)
⏳ Config changes for auto-start (TODO)
