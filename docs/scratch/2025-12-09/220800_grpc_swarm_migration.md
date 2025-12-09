# gRPC Swarm Migration Complete

## Summary

Migrated all swarm functionality from client-side scheduler (which used hardcoded model names) to gRPC engine (which uses capability-based routing via `agents.conf`).

## Problem

The swarm was failing with 404 errors like `"The model 'Qwen/QwQ-32B' does not exist"` because:

1. **Two schedulers existed**:
   - `src/gaius/engine/services/scheduler_service.py` - Engine-side, correct
   - `src/gaius/inference/scheduler.py` - Client-side, bypasses gRPC

2. **Client scheduler used hardcoded model names** from `roles.py::preferred_model_id`

3. **Loaded models differ** from hardcoded names (agents.conf defines actual deployment)

## Solution

Route all swarm calls through gRPC engine, deprecate client-side scheduler.

## Files Modified

| File | Change |
|------|--------|
| `src/gaius/client/grpc_client.py` | Added `_run_swarm_via_grpc()` method |
| `src/gaius/client/engine_proxy.py` | Added `run_swarm()` to SchedulerProxy |
| `src/gaius/cli.py` | Updated `_cmd_swarm()` to use gRPC |
| `src/gaius/app.py` | Updated `_complete_swarm_analysis()` to use gRPC |
| `src/gaius/mcp_server.py` | Updated `run_swarm` and `scheduler_run_swarm` tools |
| `src/gaius/agents/evolution/daemon.py` | Updated scheduler queue check to use gRPC |
| `src/gaius/models/tiered_evaluation.py` | Updated to use gRPC scheduler |
| `src/gaius/inference/scheduler.py` | Added deprecation warnings |

## Capability-to-Endpoint Mapping

```python
ROLE_TO_ENDPOINT = {
    "Leader": "orchestrator",      # reasoning/synthesis
    "Risk": "fast",                # analysis
    "Optimizer": "fast",           # analysis
    "Planner": "orchestrator",     # reasoning
    "Critic": "fast",              # adversarial/analysis
    "Executor": "fast",            # execution
    "Adversary": "fast",           # adversarial
}
```

## Test Results

```
/swarm pension - SUCCESS
- 7/7 agents completed
- Total latency: ~67 seconds
- Models used: nvidia/Orchestrator-8B, mistralai/Mistral-7B-Instruct-v0.3
- Content successfully extracted
```

## Architecture

```
Before:
  CLI -> inference/scheduler.py -> Direct HTTP -> vLLM (hardcoded model names)
                                                   ❌ 404 errors

After:
  CLI -> engine_proxy.py -> gRPC -> gaius-engine -> agents.conf -> vLLM
                                     ✅ capability-based routing
```

## Deprecation

The client-side scheduler (`src/gaius/inference/scheduler.py`) is now deprecated.
Use `get_scheduler_proxy()` from `gaius.client.engine_proxy` instead.

## KB Persistence

Swarm results are now automatically saved to KB for future reference:

```
current/agents/swarm/{date}/{HHMMSS}_{domain}.md
```

Example: `current/agents/swarm/2025-12-09/223537_pension.md`

Each document includes:
- Summary statistics (agents, tokens, latency)
- Full responses from all 7 agents in role order (Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary)
- Model/endpoint metadata for each agent
- Zettelkasten-style formatting

This enables:
- Historical analysis of swarm outputs
- Comparison of findings over time
- Building institutional knowledge in the KB

### Consolidated KB Persistence (2025-12-09)

KB persistence has been consolidated into `SchedulerProxy.run_swarm()` so all callers automatically get KB persistence:

| Path | Uses gRPC | Saves to KB |
|------|-----------|-------------|
| CLI `/swarm` | ✓ | ✓ |
| TUI `/swarm` | ✓ | ✓ |
| MCP `run_swarm` | ✓ | ✓ |
| MCP `scheduler_run_swarm` | ✓ | ✓ |

**Implementation:**

1. Moved `save_swarm_to_kb()` from CLI to shared `src/gaius/storage/kb_ops.py`
2. `SchedulerProxy.run_swarm()` now returns `tuple[dict, str]` (results, saved_path)
3. All callers updated to unpack the tuple and display/include saved_path

**Design Rationale:**

- Engine-centric: KB persistence happens at proxy level, not scattered across CLI/TUI/MCP
- Single code path: All swarm invocations produce same artifacts
- Always save: Normal operations always persist (evolution daemon has separate RL framework)
