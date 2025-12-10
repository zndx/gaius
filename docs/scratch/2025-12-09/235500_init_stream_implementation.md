# gRPC InitStream Implementation Complete

## Summary

Implemented bidirectional gRPC streaming for real-time initialization progress during the ~240s engine startup phase.

## Problem Solved

Previously, the gRPC server started AFTER vLLM endpoints finished preloading, meaning TUI/MCP clients could not connect during initialization. Users had no visibility into the startup process.

## Solution

Reordered startup to start gRPC first, then use bidirectional streaming to report progress while heavy initialization runs in the background.

## Files Modified/Created

### Proto Definitions
- `src/gaius/engine/proto/gaius_service.proto` - Added InitStream RPC, InitCommand, InitEvent messages

### Server-Side
- `src/gaius/engine/init_controller.py` (NEW) - InitController class with command queue, pause/resume, cancel endpoints
- `src/gaius/engine/server.py` - Reordered startup sequence (gRPC first)
- `src/gaius/engine/grpc/server.py` - Added init_controller to ServiceRegistry
- `src/gaius/engine/grpc/servicers/gaius_servicer.py` - Added InitStream handler
- `src/gaius/engine/generated/__init__.py` - Export InitCommand, InitEvent

### Client-Side
- `src/gaius/client/grpc_client.py` - Added init_stream() and send_init_command() methods

### TUI
- `src/gaius/core/state.py` - Added CenterPanelMode.INIT, InitializationState, EndpointInitProgress
- `src/gaius/widgets/init_panel.py` (NEW) - Rich progress bar widget for initialization
- `src/gaius/app.py` - Integrated InitPanel, updated g key cycling

## Key Features

1. **Bidirectional Streaming**: `rpc InitStream(stream InitCommand) returns (stream InitEvent)`
2. **Command Types**: SUBSCRIBE, HEALTH, STATUS, CANCEL, SKIP, PAUSE, RESUME
3. **Event Types**: PHASE_STARTED, PROGRESS, ENDPOINT_READY, ENDPOINT_FAILED, etc.
4. **Init-Aware Panel Cycling**:
   - During init: INIT → GRAPH → THINK → EVOLUTION → NONE → INIT
   - After ready: GRAPH → THINK → EVOLUTION → NONE → GRAPH (skips INIT)

## Testing

Verified with textual pilot:
- g key cycles correctly through all modes during initialization (includes INIT)
- g key correctly skips INIT after initialization completes
- CLI commands work (`/state` returns valid JSON)

## UX Improvements (Second Pass)

Based on feedback, two UX issues were fixed:

1. **InitPanel now shows by default during startup** (`src/gaius/app.py:3808-3810`)
   - `_apply_center_panel_mode()` now checks `initialization_state.is_ready`
   - If not ready, automatically sets mode to INIT

2. **Scheduler waits for backends before processing** (`src/gaius/engine/services/scheduler_service.py:377-448`)
   - Added `_wait_for_backends()` method with exponential backoff
   - Added `_any_backend_ready()` to check vLLM and optillm status
   - Inference requests are queued until endpoints are healthy

## Next Steps

- Manual test with `devenv up -d` to verify end-to-end
- Add cancel button in InitPanel to cancel slow model downloads
