# Orchestrator

The OrchestratorService manages vLLM endpoint lifecycle and GPU allocation across 6 NVIDIA GPUs. It decides which models are loaded, on which GPUs, and handles startup sequencing, shutdown, preemption, and recovery.

## Endpoint Lifecycle

Endpoints transition through these states:

```
PENDING → STARTING → HEALTHY
                  ↘ UNHEALTHY → FAILED
HEALTHY → STOPPING → STOPPED
```

### EndpointStatus

```python
@dataclass
class EndpointStatus:
    name: str           # "reasoning", "coding", etc.
    state: str          # "healthy", "starting", "unhealthy", "stopped"
    gpus: list[int]     # Allocated GPU indices
    pid: int | None     # vLLM process ID
    port: int           # Serving port
    model: str          # HuggingFace model ID
    uptime_seconds: int
```

## Capability-Based Scheduling

The orchestrator follows a Yunikorn-inspired capability-based model:

1. **Requests declare capabilities, not endpoints**: A workload asks for "reasoning" capability, not a specific GPU or model. The orchestrator maps capabilities to endpoints.
2. **Priority-based preemption**: When a higher-priority workload needs a GPU that is occupied by lower-priority work, the orchestrator evicts the lower-priority endpoint, executes the workload, and restores baseline.
3. **Makespan fulfillment**: The OR-Tools CP-SAT solver plans multi-step operations. The orchestrator executes the plan, tracking progress through the `AgendaTracker`.

### Baseline Set Points

The orchestrator maintains a *baseline configuration* — the steady-state GPU allocation. After transient workloads (rendering, evolution), it restores baseline automatically. This means interactive inference is never permanently degraded by batch operations.

## GPU Allocation

| Endpoint | GPUs | TP | Purpose |
|----------|------|----|---------|
| reasoning | 0, 1 | 2 | Large model inference (24B-70B) |
| coding | 2, 3 | 2 | Code generation |
| embedding | 4 | 1 | Nomic 768-dim vectors |
| (available) | 5 | — | Rendering, evolution, overflow |

## Clean Start

The `clean_start()` operation handles recovery from corrupted state — orphan processes, stale PID files, CUDA memory leaks:

```python
result = await orch.clean_start(endpoints=["reasoning"])
# result.killed_processes — stale vLLM processes terminated
# result.freed_gpus — GPUs reclaimed
# result.started_endpoints — freshly started endpoints
```

This is the programmatic equivalent of `just restart-clean`, available via gRPC for use by the health system and ACP agent.

## Health Integration

The orchestrator provides the `AgendaTracker` for the Health Observer. When an endpoint is part of a scheduled makespan operation, health checks skip incident creation:

```python
if tracker.is_endpoint_in_scheduled_transition("reasoning"):
    expected = tracker.get_scheduled_endpoint_state("reasoning")
    # Don't create incident — this is planned
```

Three `ControlMode` values distinguish contexts:
- `POSITIVE`: Planned operation (start/stop)
- `FAILURE`: Responding to detected failure
- `RESTART_RECOVERY`: Restarting after failure with extended grace period

## Checking Status

```bash
# All endpoints
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[]'

# Watch during restart
for i in $(seq 1 15); do
    sleep 10
    uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[] | {name, status}'
done
```
