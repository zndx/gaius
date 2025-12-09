# Legacy Fallback Warning Instrumentation

## Summary

Added `logger.warning("LEGACY_FALLBACK: ...")` to all legacy fallback code paths across the codebase to surface tech debt for future refactoring.

## Warning Locations

### MCP Server (`src/gaius/mcp_server.py`)
- `scheduler_status` - Direct scheduler access
- `orchestrator_status` - Direct orchestrator access
- `orchestrator_clean_start` - Direct clean_start call
- `orchestrator_start` - Direct start_endpoint call
- `orchestrator_stop` - Direct stop_endpoint call
- `orchestrator_restart` - Direct restart call
- `orchestrator_logs` - Direct get_logs call
- `gpu_health` - Direct health monitor access

### CLI (`src/gaius/cli.py`)
- `/gpu` command - All subcommands when engine unavailable

### TUI (`src/gaius/app.py`)
- `/evolve start` - clean_start when engine unavailable

### Inference Layer
- `InferenceManager.__init__()` - Legacy orchestrator initialization
- `InferenceScheduler._init_orchestrator_components()` - Legacy orchestrator startup
- `ModelRouter._try_start_endpoint_on_demand()` - Direct orchestrator start

### Evolution Agent (`src/gaius/agents/evolution/orchestrated.py`)
- `_observe_system()` - Endpoint status via legacy orchestrator
- `_execute_restart_endpoint()` - Restart via legacy orchestrator

### ModelAdd Agent (`src/gaius/agents/modeladd/orchestrator.py`)
- `_consult_orchestrator()` - Using router instead of scheduler proxy

## Pattern Used

```python
logger.warning("LEGACY_FALLBACK: <function> bypassing engine - tech debt")
```

## Cleanup Performed

Removed `_warning` fields from JSON responses in MCP server - warnings should only be in logs, not in API responses.

## Verification

```bash
# All imports successful
uv run python -c "from gaius.mcp_server import create_server; ..."

# CLI working via engine
uv run gaius-cli --cmd "/gpu status" --format json
```

## Next Steps

1. Monitor log files for LEGACY_FALLBACK warnings during operation
2. Prioritize refactoring based on frequency of warnings
3. Eventually remove legacy fallbacks once engine-first is stable
