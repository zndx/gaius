# Gaius Engine Phase 1 Complete

## Summary

Implemented the foundation layer for gaius-engine - a centralized daemon that will replace singleton patterns in TUI/MCP/CLI with Aeron IPC communication.

## Files Created

### Configuration
- `config/gaius.fbs` - FlatBuffers schema for IPC messages with TraceContext for OpenTelemetry
- `config/agents.conf` - HOCON configuration for 11 agents with model pairings

### Engine Core
- `src/gaius/engine/__init__.py` - Package exports
- `src/gaius/engine/config.py` - HOCON config loader with dataclasses
- `src/gaius/engine/server.py` - Main engine daemon with service handlers

### Transport Layer
- `src/gaius/engine/transport/__init__.py`
- `src/gaius/engine/transport/protocol.py` - JSON serialization with OpenTelemetry trace context
- `src/gaius/engine/transport/aeron_bridge.py` - Aeron IPC abstraction with Unix socket fallback

### Package Structure (empty __init__.py)
- `src/gaius/engine/resources/`
- `src/gaius/engine/backends/`
- `src/gaius/engine/services/`
- `src/gaius/engine/compute/`
- `src/gaius/engine/generated/`
- `src/gaius/client/`

### Modified
- `pyproject.toml` - Added gaius-engine script and engine dependencies
- `devenv.nix` - Added aeron-cpp, flatbuffers, and engine processes

## Key Design Decisions

1. **Native C++ aeron-cpp** instead of Java (matching asf-kudu approach)
2. **FlatBuffers schema** for robust message versioning (upgrade path from JSON)
3. **OpenTelemetry trace context** propagation in all IPC messages
4. **Unix socket fallback** when aeronmd not running (development convenience)
5. **No singleton fallbacks** - engine will fully replace TUI/MCP/CLI functionality

## Agent Configuration

11 agents configured across two backends:

| Alias | Model | Backend | GPUs |
|-------|-------|---------|------|
| orchestrator | nvidia/Orchestrator-8B | vllm | 2 |
| reasoning | Qwen/QwQ-32B | vllm | 2 |
| coding | Qwen/Qwen3-Coder-30B-A3B-Instruct | vllm | 1 |
| fast | mistralai/Mistral-7B-Instruct-v0.3 | vllm | 1 |
| leader | Mistral-7B | optillm | - |
| risk | Mistral-7B | optillm | - |
| critic | Mistral-7B | optillm | - |
| optimizer | Mistral-7B | optillm | - |
| domain | Mistral-7B | optillm | - |
| synthesis | Mistral-7B | optillm | - |
| validator | Mistral-7B | optillm | - |

## Stream IDs
- 100: Requests
- 101: Responses
- 102: Events
- 103: Health

## Test Results

```
Loaded config with 11 agents
Engine module imports OK!
Protocol module tests passed!
```

## Next Phase

Phase 2: Resource Management + Backend Controllers
- ResourceManager with GPU allocation
- optillm_controller.py
- vllm_controller.py
- backend_router.py
