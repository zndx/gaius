# Aeron Removal and gRPC Migration

## Summary

Completed migration from Aeron/socket transport to gRPC-only transport for gaius-engine communication. The `GAIUS_ENABLE_FALLBACKS` feature flag is no longer needed.

## Changes Made

### CLI (`src/gaius/cli.py`)

1. **`_get_engine_client_cached()`** - Now uses `GrpcEngineClient` instead of socket-based `EngineClient`
2. **`_cmd_engine()`** - Completely rewritten to use gRPC:
   - `/engine status` - Reports gRPC connection status
   - `/engine test` - Tests round-trip via gRPC
   - `/engine reconnect` - Reconnects gRPC client

### Engine Fixtures (`features/steps/engine_fixtures.py`)

1. Removed socket-related code
2. `EngineProcessManager` now only checks gRPC connectivity
3. `get_health()` uses `GrpcEngineClient`

### Engine Steps (`features/steps/engine_steps.py`)

1. Removed Aeron/socket-related steps:
   - `Aeron bindings are not available`
   - `I check engine transport availability`
   - `Unix socket transport should not be used`
   - `Aeron IPC should be required`
   - `Unix socket transport should be used as fallback`
2. Service status steps now use `GrpcEngineClient`

### Engine Feature (`features/engine.feature`)

1. Removed fallback/socket-related scenarios
2. Updated service status assertions to match actual gRPC responses:
   - Orchestrator: `total_gpus`, `available_gpus`
   - Scheduler: empty dict (successful if no error)
   - Evolution: `mode`

### Environment (`features/environment.py`)

1. Removed engine-integration test skipping - tests now start engine if needed
2. Simplified `_check_engine_available()` to just check gRPC
3. Simplified `_check_grpc_available()` - removed env var requirements

## Test Results

### Engine-Running Scenarios (6/6 passing)
- Check engine status when running
- Test engine round-trip
- Reconnect to engine
- Query orchestrator status via engine
- Query scheduler status via engine
- Query evolution status via engine

### CLI Commands Working
```json
/engine status -> connected: true, transport: "grpc"
/engine test   -> test: "passed", latency_ms: 1
/engine reconnect -> reconnected: true
```

## Remaining Work

1. Remove remaining `GAIUS_ENABLE_FALLBACKS` references in:
   - `src/gaius/mcp_server.py`
   - `src/gaius/client/engine_proxy.py`
   - `src/gaius/client/__init__.py`

2. Consider removing:
   - `src/gaius/client/aeron_client.py`
   - `src/gaius/engine/transport/aeron_bridge.py`

3. Update engine-not-running scenarios to work with test isolation
