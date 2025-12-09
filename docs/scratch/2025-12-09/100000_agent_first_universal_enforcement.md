# Agent-First Architecture: Universal Enforcement

## Summary

Enforced agent-first semantics universally across MCP server, TUI, CLI, and all agent-enabled functions. All GPU orchestration and endpoint management now goes through the engine client (`ensure_endpoint()`) instead of spawning vLLM directly.

## Files Modified

### MCP Server (`src/gaius/mcp_server.py`)

Updated the following tools to use engine client:
- `model_launch_coding()` - Uses `ensure_endpoint("coding")` with fail-fast
- `model_stop_coding()` - Uses engine proxy to stop
- `orchestrator_clean_start()` - Uses engine proxy with fallback
- `orchestrator_start()` - Uses `ensure_endpoint()` for proper resource management
- `orchestrator_stop()` - Uses engine proxy
- `orchestrator_restart()` - Uses engine proxy
- `orchestrator_logs()` - Uses engine proxy's async logs method

### CLI (`src/gaius/cli.py`)

Updated `/gpu` command to use engine client:
- `status` - Uses engine proxy's async status
- `start` - Uses `ensure_endpoint()` with resource checking
- `stop` - Uses engine proxy
- `restart` - Uses engine proxy with status check
- `logs` - Uses engine proxy's async logs method

Added fail-fast check for `/model add` command:
- Checks `use_engine_proxy()` before running agent workflow
- Returns clear error with hint to start engine

### TUI (`src/gaius/app.py`)

Updated `/evolve start` command:
- Uses engine proxy for `clean_start()` when engine available
- Falls back to legacy orchestrator if needed

### Evolution Agent (`src/gaius/agents/evolution/orchestrated.py`)

Updated system observation and endpoint restart:
- `_observe_system()` - Uses engine proxy for endpoint status
- `_execute_restart_endpoint()` - Uses engine proxy for restart

### Inference Manager (`src/gaius/inference/manager.py`)

Complete rewrite to support both modes:
- `__init__()` - Detects engine availability, lazy-initializes orchestrator
- `_get_engine_proxy()` - Async proxy getter
- `_discover_default_endpoint()` - Works in both modes
- `get_configured_endpoints()` - Returns standard endpoints in engine mode
- `get_running_endpoints()` - Sync interface limited in engine mode
- `get_status()` - Uses engine proxy for status in agent-first mode
- `ensure_orchestrator_running()` - Uses `ensure_endpoint()` in engine mode
- `start_endpoint()` - Uses `ensure_endpoint()` in engine mode
- `stop_endpoint()` - Uses engine proxy

### Inference Scheduler (`src/gaius/inference/scheduler.py`)

Updated initialization to prefer engine:
- `_init_orchestrator_components()` - Skips legacy orchestrator when engine running

### ModelAdd Orchestrator (`src/gaius/agents/modeladd/orchestrator.py`)

Already updated in previous session:
- `_tool_launch_coding()` - Uses `ensure_endpoint()`
- `_tool_stop_coding()` - Uses engine proxy
- `_consult_orchestrator()` - Uses scheduler proxy when available

### Engine Proxy (`src/gaius/client/engine_proxy.py`)

Added new methods:
- `get_endpoint_status()` - Get status of specific endpoint
- `get_logs_async()` - Async version of get_logs

### Inference Router (`src/gaius/inference/router.py`)

Updated on-demand start to prefer engine:
- `_try_start_endpoint_on_demand()` - Uses engine client first, fallback to legacy

## Architecture Pattern

All components now follow this pattern:

```python
from ..client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

# Check if engine is available
if use_engine_proxy():
    # Engine mode - use ensure_endpoint for proper resource management
    orch = await get_orchestrator_proxy()
    result = await orch.ensure_endpoint(endpoint_name)

    if result.get("healthy"):
        # Success
    else:
        # Handle error with informative message
        error = result.get("message", result.get("status"))
else:
    # Fallback to legacy orchestrator
    from .inference.orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    # ... legacy code path
```

## Key Benefits

1. **Centralized GPU Management**: All GPU allocations tracked by ResourceManager
2. **No Conflicts**: CLI, TUI, MCP, and agents can't conflict on GPU resources
3. **Resource Awareness**: `ensure_endpoint` checks resources before starting
4. **Clear Error Messages**: Informative messages when resources unavailable
5. **Backwards Compatible**: Legacy mode still works when engine not running

## Testing

All imports verified successful:
```bash
uv run python -c "
from gaius.mcp_server import create_server
from gaius.cli import GaiusCLI
from gaius.app import GaiusApp
from gaius.agents.evolution.orchestrated import OrchestratedEvolution
from gaius.inference.manager import InferenceManager
from gaius.client.engine_proxy import use_engine_proxy
print('✓ All imports successful')
print(f'Engine proxy available: {use_engine_proxy()}')
"
# ✓ All imports successful
# Engine proxy available: True
```

CLI test:
```bash
uv run gaius-cli --cmd "/gpu status" --format json
# Returns engine status via proxy
```
