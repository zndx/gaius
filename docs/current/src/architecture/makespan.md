# Makespan Scheduling

Makespan scheduling optimizes GPU utilization across multi-step workloads that require endpoint transitions (eviction, loading, inference, restoration).

## What is a Makespan?

A makespan is the total time from start to finish of a complex workload that may require:

1. **GPU eviction**: Stopping a low-priority endpoint to free GPUs
2. **Endpoint startup**: Loading a different model
3. **Workload execution**: Running the actual inference
4. **Baseline restoration**: Reloading the original endpoint

## Example: Render Pipeline

```
makespan.execute
├── allocate_gpus              # OR-Tools resource assignment
├── evict_if_needed            # Preemption decisions
├── start_endpoints            # vLLM process spawning
│   └── endpoint.start: rendering
│       ├── process_spawn
│       ├── model_load         # ~240s for large models
│       └── health_check
├── execute_workload           # Actual inference/rendering
└── restore_baseline           # Return to set points
```

## AgendaTracker

The AgendaTracker records scheduled endpoint transitions so the Health Observer can distinguish intentional state changes from failures:

```python
tracker.register_operation(
    operation_id=op_id,
    workload_id=wl_id,
    control_mode=ControlMode.POSITIVE,
    target_endpoints=["reasoning", "fast"],
)
```

### Control Modes

| Mode | Purpose |
|------|---------|
| `POSITIVE` | Planned operation (start/stop) |
| `FAILURE` | Responding to detected failure |
| `RESTART_RECOVERY` | Restarting after failure resolution |

## Tracing

Each makespan is traced as a parent span with child spans for each operation phase. This enables end-to-end visibility into complex multi-step operations, including time spent in external API calls (treated as black-box stages).
