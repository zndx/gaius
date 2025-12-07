# BDD Test Suite Complete

## Summary

Comprehensive BDD test coverage established with 45 scenarios passing across 4 test features. Aeron transport removed in favor of gRPC-only.

## Test Results

| Feature | Scenarios | Status |
|---------|-----------|--------|
| CLI Workflow (`@cli`) | 12 | Passing |
| MCP Tier 1 (`@tier1`) | 15 | Passing |
| Engine Integration | 6 | Passing |
| TUI Navigation | 12 | Passing |
| **Total** | **45** | **All Pass** |

## Key Changes

### Transport Migration
- Removed Aeron IPC transport completely
- gRPC is now the only engine transport (port 50051)
- Eliminated `GAIUS_ENABLE_FALLBACKS` environment variable
- Updated `src/gaius/client/__init__.py`, `engine_proxy.py`, `cli.py`

### Test Infrastructure
- `features/steps/shared_steps.py` - Common assertion steps
- `features/steps/test_fixtures.py` - KB, CLI, inference fixtures
- `features/environment.py` - Enhanced with MCP cleanup, TUI focus handling
- `features/steps/engine_fixtures.py` - gRPC-only engine management

### TUI Testing
- Fixed focus issue: Press `escape` and clear focus before navigation
- Navigation via `h/j/k/l` keys works correctly
- Mini-grid and panel tests gracefully handle optional components

## Running Tests

```bash
# CLI tests
uv run behave features/workflow.feature --tags=@cli

# MCP tests
uv run behave features/mcp.feature --tags=@tier1

# Engine tests (requires running engine)
uv run behave features/engine.feature -n "Check engine status when running|Test engine round-trip|Reconnect to engine|Query"

# Navigation tests
uv run behave features/navigation.feature

# All tests
uv run behave features/workflow.feature features/mcp.feature features/navigation.feature --tags=@cli,@tier1
```

## Files Modified

### Source
- `src/gaius/cli.py` - gRPC-only engine commands
- `src/gaius/client/__init__.py` - Removed socket exports
- `src/gaius/client/engine_proxy.py` - gRPC connectivity check

### Features
- `features/engine.feature` - Removed fallback scenarios
- `features/steps/engine_steps.py` - gRPC service calls
- `features/steps/engine_fixtures.py` - gRPC-only manager
- `features/steps/navigation_steps.py` - TUI focus handling, mini-grid steps
- `features/environment.py` - MCP cleanup, simplified engine checks
