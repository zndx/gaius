# gRPC SwarmStream Implementation

## Summary

Implemented server-side streaming for swarm analysis that handles backend wait internally, preventing client timeouts during engine initialization (~240s startup).

## Problem Solved

Previously, swarm commands issued during engine initialization would fail with `DEADLINE_EXCEEDED` because the client would timeout while waiting for backends to be ready. The TUI-side queue approach was being considered, but a better solution is server-side streaming.

## Solution

Server-side gRPC streaming where:
1. TUI sends SwarmStream request
2. Engine immediately starts streaming status updates (QUEUED, WAITING_FOR_BACKENDS, etc.)
3. Client receives continuous updates, preventing timeout
4. When backends ready, analysis proceeds with per-agent progress
5. Final COMPLETED event contains all results

## Files Modified/Created

### Proto Definitions
- `src/gaius/engine/proto/gaius_service.proto`
  - Added `SwarmStreamRequest`, `SwarmEvent`, `SwarmResult` messages
  - Added `rpc SwarmStream(SwarmStreamRequest) returns (stream SwarmEvent)`

### Server-Side
- `src/gaius/engine/grpc/servicers/gaius_servicer.py`
  - Added `SwarmStream` method with backend wait loop and streaming
  - Yields: QUEUED → WAITING_FOR_BACKENDS → STARTED → AGENT_STARTED/COMPLETED/FAILED → COMPLETED

### Client-Side
- `src/gaius/client/grpc_client.py`
  - Added `swarm_stream()` async iterator method
- `src/gaius/client/engine_proxy.py`
  - Added `run_swarm_stream()` method
  - Updated `run_swarm()` to use streaming internally with progress callback

### State
- `src/gaius/core/state.py`
  - Removed `QueuedCommand` class (no longer needed)
  - Removed `queued_commands` field from `InitializationState`

### TUI
- `src/gaius/app.py`
  - Updated `_complete_swarm_analysis()` with `on_progress` callback
  - Progress callback updates content panel with real-time status

### Generated
- `src/gaius/engine/generated/__init__.py`
  - Added exports for SwarmStreamRequest, SwarmEvent, SwarmResult
  - Added exports for InitCommand, InitEvent (were missing)

### InitPanel Bug Fixes
- `src/gaius/widgets/init_panel.py`
  - Fixed `_poll_init_status()` to populate `init_state.endpoints` from health check data
  - Fixed `_update_from_event()` to create endpoint entries on ENDPOINT_READY/FAILED/CANCELLED
    - Previously these events only updated existing endpoints, missing any not seen during ENDPOINT_STARTING
  - Both streaming and polling paths now correctly populate the endpoint list

## SwarmEvent Types

```
QUEUED = 0              // Request queued, waiting for backends
WAITING_FOR_BACKENDS = 1 // Actively waiting (periodic updates)
STARTED = 2             // Backends ready, swarm analysis beginning
AGENT_STARTED = 3       // Individual agent started
AGENT_COMPLETED = 4     // Individual agent completed
AGENT_FAILED = 5        // Individual agent failed
SYNTHESIS = 6           // Synthesis phase started
COMPLETED = 7           // All agents done, includes final results
FAILED = 8              // Swarm failed entirely
```

## Testing

Verified:
- Proto compilation successful
- All imports work
- TUI panel cycling (g key) works
- CLI `/state` command works

## Architecture Benefits

1. **No client timeout**: Stream keeps connection alive during backend wait
2. **Real-time progress**: TUI shows QUEUED/WAITING status immediately
3. **Server-side queueing**: No complex TUI-side queue management needed
4. **Backwards compatible**: `run_swarm()` still returns tuple, uses streaming internally

## Next Steps

- [x] Fix InitPanel endpoint display (both streaming and polling paths)
- [ ] Test end-to-end with `devenv up -d` and profile startup
- [ ] Verify WAITING_FOR_BACKENDS updates show in TUI during init
