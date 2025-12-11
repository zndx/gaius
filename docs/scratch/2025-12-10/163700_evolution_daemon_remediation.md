# Evolution Daemon Remediation Implementation

Added automated remediation for "Evolution Daemon: warn (not running)" health check.

## Files Created/Modified

| File | Change |
|------|--------|
| `build/dev/current/heuristics/gaius/evolution/daemon_not_running.md` | NEW: Heuristic KB entry |
| `src/gaius/health/service_fixes.py` | Added `EvolutionFixStrategy` class |
| `src/gaius/health/checker.py` | Updated suggestion and heuristic_id references |

## Implementation Details

### 1. Heuristic KB Entry

Created `build/dev/current/heuristics/gaius/evolution/daemon_not_running.md` following the 4-component format:

- **Symptom**: Health check shows "Evolution Daemon: warn - Daemon not running"
- **Cause**: Evolution daemon requires engine running + enabled config + manual/auto start
- **Observation**: Automation Level A (fully automatable detection via gRPC)
- **Solution**: Automation Level B (partial - gRPC StartEvolution is a stub)

### 2. EvolutionFixStrategy

Added to `src/gaius/health/service_fixes.py`:

```python
class EvolutionFixStrategy(ServiceFixStrategy):
    def create_fix_actions(self, check_result: dict | None = None) -> list[RemediationAction]:
        actions = []
        # 1. Check if engine is running, add engine start if needed
        # 2. Request evolution start via gRPC
        # 3. Provide manual alternative guidance
        return actions
```

Registered as `"evolution"` and `"evolve"` aliases in `SERVICE_STRATEGIES`.

### 3. Health Check Updates

Updated `_check_evolution_daemon_status()` in checker.py:
- Changed suggestion from "Start daemon with: /evolve start" to "Run: /health fix evolution"
- Added `heuristic_id="evolution/daemon_not_running"` to all failure paths

## Discovery: gRPC StartEvolution is a Stub

During implementation, discovered that `engine/server.py:_start_evolution()` is a stub:

```python
async def _start_evolution(self) -> dict:
    logger.info("Starting evolution (stub)")
    return {"started": True}
```

The evolution daemon runs inside the engine process and the gRPC endpoint doesn't wire to the actual `EvolutionService.start()`. This is why `/evolve start` (which does full orchestration) is more reliable.

## Testing

```bash
# Dry-run shows all 5 actions that would be executed
uv run gaius-cli --cmd "/health fix evolution --dry-run" --format json

# Output shows:
# 1. Start devenv services
# 2. Wait for engine startup
# 3. Reset gRPC singleton
# 4. Request evolution start
# 5. Manual alternative guidance
```

## Limitation

The automated fix provides a best-effort start via gRPC, but recommends `/evolve start` for full orchestrated evolution with:
- GPU cleanup
- Stale process detection
- Parallel endpoint management
- Full daemon initialization

This limitation is documented in both the heuristic KB entry (Automation Level B) and the fix strategy's manual alternative action.
