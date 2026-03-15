# Makespan Scheduling

Makespan scheduling optimizes GPU utilization across multi-step workloads that require endpoint transitions — eviction, loading, inference, and restoration. The scheduler uses OR-Tools CP-SAT for constraint-based resource assignment.

## What is a Makespan?

A makespan is the total time from start to finish of a complex workload that may require multiple GPU state transitions:

1. **GPU eviction** — Stop a low-priority endpoint to free GPUs
2. **Endpoint startup** — Load a different model (~240s for large models)
3. **Workload execution** — Run the actual inference or rendering
4. **Baseline restoration** — Reload the original endpoint to its set point

The scheduler minimizes total makespan by solving a constraint satisfaction problem over GPU assignments, endpoint capacities, and tensor parallelism requirements.

## OR-Tools CP-SAT Integration

The scheduler (`inference/scheduler.py`) formulates GPU assignment as a CP-SAT model (Google, 2024):

```
Minimize: weighted_completion_time = Σ priority_weight[j] × completion_time[j]

Subject to:
  - Each job assigned to exactly one endpoint
  - Endpoint GPU capacity not exceeded
  - Tensor parallelism requirements met (e.g., 70B model needs 4 GPUs)
  - GPU memory limits respected per device
```

Four priority levels control preemption:

| Priority | Level | Weight | Preemption |
|----------|-------|--------|------------|
| CRITICAL (0) | User-facing, leader synthesis | 8x | Can preempt all lower |
| HIGH (1) | Swarm agent calls | 4x | Can preempt NORMAL/LOW |
| NORMAL (2) | Background tasks | 2x | Queue-ordered |
| LOW (3) | Speculative inference | 1x | Fills idle capacity |

## AgendaTracker

The `AgendaTracker` (`engine/services/agenda_tracker.py`) records scheduled endpoint transitions so the Health Observer can distinguish intentional state changes from failures. Without this, a planned GPU eviction for rendering would trigger a false FMEA incident.

| Control Mode | Purpose |
|-------------|---------|
| `POSITIVE` | Planned operation (start/stop/swap) |
| `FAILURE` | Responding to detected failure |
| `RESTART_RECOVERY` | Restarting after failure resolution |

The Health Observer checks `is_endpoint_in_scheduled_transition()` before creating incidents — endpoints in a POSITIVE transition are excluded.

## Example: Render Pipeline

The visualization render workload demonstrates a full makespan:

```
makespan.execute("render_cards")
├── allocate_gpus              # CP-SAT assigns GPU 5 (least-loaded)
├── evict_if_needed            # Stop vLLM coding endpoint on GPU 5
│   └── agenda_tracker.register(mode=POSITIVE, endpoints=["coding"])
├── start_endpoints            # Load LuxCore renderer
│   └── endpoint.start: rendering
│       ├── process_spawn
│       └── health_check
├── execute_workload           # Path-trace 20 cards (PATHOCL, 20s/128spp each)
├── clear_embeddings           # Release Nomic model (~3GB) from GPU
└── restore_baseline           # Restart coding endpoint to set point
    └── agenda_tracker.complete(operation_id)
```

## Tracing

Each makespan is traced as a parent OpenTelemetry span with child spans for each phase. This provides end-to-end latency visibility, including time in external API calls (treated as black-box stages). Traces flow through the standard OTel Collector → Prometheus pipeline.
