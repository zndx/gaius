# BDD Test Implementation Progress

## Summary

Implementation of comprehensive BDD test infrastructure following the 6-tier architecture:

- Tier 0: CLI Pure (no external dependencies)
- Tier 1: CLI + DB (PostgreSQL)
- Tier 2: CLI + Engine (gaius-engine gRPC)
- Tier 3: MCP Pure (FastMCP in-process)
- Tier 4: MCP + Engine (gaius-engine proxy)
- Tier 5: TUI (Textual Pilot)
- Tier 6: Full Integration (all services)

## Completed Work

### Phase 1: Foundation Layer

1. **features/steps/shared_steps.py** - 30+ reusable assertion steps
   - Result assertions (contains, has_key, equals, successful, error)
   - File system assertions (exists, contains)
   - State assertions (view_mode, overlay_mode, domain, cursor)
   - Environment assertions

2. **features/steps/test_fixtures.py** - 20+ common setup steps
   - KB fixtures (root, notes, directory structure)
   - State fixtures (cursor, domain, view mode, overlay)
   - CLI fixtures (initialization, JSON mode)
   - Inference fixtures (availability check)

3. **features/environment.py** - Enhanced with:
   - Per-scenario KB isolation (`build/test/scratch/{date}/{scenario-id}/`)
   - Tag-based skip logic for @db-required, @engine-integration, @grpc-integration
   - TUI pilot lifecycle management (context._app_cm pattern)
   - Environment variable restoration in after_scenario

### Phase 2: CLI Tests (Tier 0)

- **11 scenarios passing** in workflow.feature @cli
- Commands tested: /profile, /domain, /project, /thoughts, /search, /evolve status

### Phase 3: MCP Tests (Tier 1-2)

- **15 scenarios passing** in mcp.feature @tier1
- Tools tested: create_kb, read_kb, search_kb, list_kb, update_kb, delete_kb
- Security tests for path validation and directory traversal

### Phase 4: Engine/gRPC Tests (Tier 2)

- Step definitions complete in engine_steps.py and grpc_steps.py
- Requires gaius-engine running for integration tests
- Tests will auto-skip if engine not available

## Test Commands

```bash
# Run CLI pure tests (no dependencies)
uv run behave --tags=@cli --tags=~@db-required --tags=~@workflow

# Run MCP tier 1 tests (KB and models)
uv run behave features/mcp.feature --tags=@tier1

# Run engine integration tests (requires devenv up)
GAIUS_RUN_ENGINE_TESTS=true uv run behave features/engine.feature

# Run gRPC integration tests (requires gaius-engine gRPC)
GAIUS_RUN_GRPC_TESTS=true uv run behave features/grpc.feature
```

## Duplicate Cleanup

Resolved step definition conflicts between:
- shared_steps.py (canonical for assertions)
- workflow_steps.py (CLI workflow specific)
- navigation_steps.py (TUI navigation specific)
- test_fixtures.py (setup fixtures)

## Remaining Work

1. **TUI Tests (Tier 5)** - Create tui_steps.py with navigation and panel steps
2. **Inference Tests (Tier 3)** - Tests that require vLLM/optillm stack
3. **Subprocess MCP Testing** - Real mcp-client for protocol compliance
4. **Concurrency Tests (Tier 6)** - Multi-client scenarios

## Key Files Modified

- `features/environment.py` - Enhanced lifecycle management
- `features/steps/shared_steps.py` - NEW - Reusable assertions
- `features/steps/test_fixtures.py` - Enhanced setup steps
- `features/steps/workflow_steps.py` - Cleaned up duplicates
- `features/steps/navigation_steps.py` - Cleaned up duplicates
