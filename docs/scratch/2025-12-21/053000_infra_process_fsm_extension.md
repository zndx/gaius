# Infrastructure Process FSM Extension

**Date**: 2025-12-21
**Status**: Implemented

## Problem

Orphaned kubectl port-forward processes (PPID=1) cause restart loops in devenv/process-compose. The pattern:

1. User's session ends or crashes
2. kubectl port-forward gets reparented to init (PPID=1)
3. It keeps holding the port (e.g., 3000)
4. When devenv restarts, metaflow-port-forwards can't bind
5. Endless "Port-forward exited, restarting in 5s..." loop

## Solution

Extended the FSM reconciliation to handle **infrastructure processes** in addition to GPU endpoints.

### New Components

```
src/gaius/engine/resources/reconciliation.py
├── InfraProcessState (Enum)       # ABSENT, RUNNING, ORPHANED, CONFLICT
├── InfraProcessObservation        # Port → PID → PPID → cmdline mapping
├── InfraReconciliationResult      # Action taken, orphans killed, etc.
├── observe_infra_process()        # Gather observations
├── remediate_infra_orphans()      # Kill orphaned processes
└── ReconciliationService          # Now reconciles infra + endpoints
```

### Detection Logic

```python
def get_orphan_pids(self) -> list[int]:
    """PIDs with PPID=1 on our expected ports."""
    orphans = []
    for port in self.expected_ports:
        pid = self.port_pids.get(port)
        if pid and self.pid_ppids.get(pid) == 1:
            orphans.append(pid)
    return orphans
```

### Remediation Flow

1. **Observe**: Query `ss -tlnp` for port listeners
2. **Enrich**: Read `/proc/<pid>/status` for PPID, `/proc/<pid>/cmdline` for command
3. **Classify**:
   - PPID=1 → Orphan (kill it)
   - kubectl/tilt → Legitimate (ignore)
   - Unknown → Conflict (warn only)
4. **Remediate**: SIGTERM, wait 1s, SIGKILL if needed
5. **Log**: Guru code `#EN.00000013.ORPHAN_INFRA`

### Reconciliation Order

```python
async def _reconcile_all(self) -> None:
    # Phase 1: Infrastructure (clear orphans first!)
    await self._reconcile_infra_processes()

    # Phase 2: GPU endpoints (now ports are free)
    await self._reconcile_endpoints()
```

### Default Monitored Processes

```python
self._infra_processes = {
    "metaflow-port-forwards": [3000, 8083, 8180],
}
```

### API

```python
# Add more processes to monitor
service.add_infra_process("my-service", [8080, 8443])

# One-shot check (for pre-flight)
results = await service.check_infra_orphans()

# Status includes infra
status = service.get_status()
# status["infrastructure"]["metaflow-port-forwards"]["orphans_killed"]
```

## Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#EN.00000013.ORPHAN_INFRA` | Orphaned infrastructure process detected and killed |

## Testing

```python
from gaius.engine.resources.reconciliation import observe_infra_process

obs = await observe_infra_process('metaflow-port-forwards', [3000, 8083, 8180])
print(f"Orphans: {obs.get_orphan_pids()}")
print(f"Conflicts: {obs.get_conflict_ports()}")
```

## Future Work

1. **Auto-discover from process-compose**: Parse `process-compose.yaml` for port bindings
2. **K8s port-forward health**: Check if the target pod is healthy
3. **Metrics**: Prometheus counters for orphans_killed, conflicts_detected
