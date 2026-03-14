# Orchestrator

The OrchestratorService manages vLLM endpoint lifecycle and GPU allocation. It decides which models are loaded, on which GPUs, and handles startup, shutdown, and recovery.

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

## Workload Management

The orchestrator follows Yunikorn-style capability-based scheduling:

1. **Requests declare capabilities, not endpoints**: A workload asks for "reasoning" capability, not a specific model
2. **Priority-based preemption**: Idle endpoints can be evicted for higher-priority work
3. **Makespan fulfillment**: The engine ensures work completes, then restores baseline set points

### Example: Render Pipeline

When the viz pipeline needs a GPU for LuxCore rendering:

1. Workload requests GPU with `allow_baseline_eviction=True`
2. Orchestrator evicts lowest-priority endpoint from target GPU
3. Rendering completes
4. Orchestrator restores the evicted endpoint

## Clean Start

The `clean_start()` operation handles recovery from corrupted state:

```python
result = await orch.clean_start(endpoints=["reasoning"])
# Kills stale vLLM processes
# Cleans up CUDA memory
# Restarts endpoints fresh
```

## Health Integration

The orchestrator works with the AgendaTracker to distinguish intentional state changes from failures. When an endpoint is part of a scheduled makespan operation, the Health Observer skips incident creation:

```python
if tracker.is_endpoint_in_scheduled_transition("reasoning"):
    # Don't create incident — this is planned
    expected = tracker.get_scheduled_endpoint_state("reasoning")
```

## Checking Status

```bash
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[]'
```
