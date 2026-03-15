# Scheduler

The SchedulerService provides a priority-based job queue for inference requests with XAI budget management, weighted completion time minimization, and OR-Tools constraint satisfaction for multi-GPU workload planning.

## Priority Levels

| Priority | Weight | Use Case |
|----------|--------|----------|
| `CRITICAL` (0) | 1.0 | User-facing interactive requests |
| `HIGH` (1) | 2.0 | Interactive queries |
| `NORMAL` (2) | 4.0 | Background processing |
| `LOW` (3) | 8.0 | Batch operations |
| `EVOLUTION` (4) | 16.0 | Agent evolution (lowest priority) |

Lower weights receive preferential scheduling. Critical requests preempt everything — if a CRITICAL job arrives while all endpoints are busy with EVOLUTION work, the scheduler preempts the lowest-priority running job.

## Job Flow

```
InferenceJob → SchedulerService.submit()
    → priority_queue.push()  (heapq ordered by priority weight)
    → wait for endpoint availability
    → VLLMController.infer()  (dispatched to appropriate backend)
    → InferenceResponse
```

The scheduler routes through the `BackendRouter`, which dispatches to vLLM (standard inference), optillm (reasoning techniques like `cot_reflection` or `bon`), or external providers (xAI Grok, Cerebras) based on request parameters. The `technique` field on `InferenceRequest` selects optillm; the `provider` field selects external backends.

## XAI Budget

The scheduler tracks daily usage of external AI APIs to prevent runaway costs:

```python
budget = scheduler.get_xai_budget()
# budget.daily_remaining: tokens left for today
# budget.daily_limit: configured daily cap
# budget.reset_time: when the budget resets (midnight UTC)
```

Requests exceeding the daily budget are rejected with guru code `#SCHED.00001.BUDGETEXHAUSTED`. The budget resets at midnight UTC. Budget state persists in PostgreSQL so it survives engine restarts.

## Makespan Scheduling

For compound workloads requiring multiple inference calls — agent evolution (candidate generation + evaluation), render pipelines (evict → load → execute → restore), or swarm runs (N agents × M rounds) — the scheduler delegates to the OR-Tools CP-SAT solver for makespan optimization.

The `AgendaTracker` coordinates with the `HealthObserver` to suppress false-positive incidents during planned transitions. When an endpoint is part of a scheduled makespan operation, health checks skip incident creation.

See [Makespan Scheduling](./makespan.md) for constraint model details.

## Timeouts

| Context | Default Timeout | Rationale |
|---------|----------------|-----------|
| General gRPC calls | 30s | `GrpcClientConfig.timeout` |
| Inference (completions) | 120s | A 24B model with `cot_reflection` takes 15-20s |
| Evaluation | 120s | xAI evaluator may have network latency |
| Model loading | 300s | A 70B model takes ~240s to load to VRAM |

Timeouts are set per-call in `_client.call(..., timeout=N)`. Override the default via `GAIUS_ENGINE_TIMEOUT` environment variable.

## Backend Integration

The scheduler sits between clients and the backend layer:

```
CLI/TUI/MCP → gRPC → SchedulerService → BackendRouter
                                            ├── VLLMController (local GPU)
                                            ├── OptillmController (reasoning techniques)
                                            ├── EmbeddingController (Nomic 768-dim)
                                            ├── ColPaliController (multi-vector)
                                            └── ExternalInferenceRouter
                                                 ├── xAI (Grok 4.1 Fast)
                                                 └── Cerebras (fast inference)
```

The `ExternalInferenceRouter` provides access to frontier models for evaluation and calibration. Budget tracking applies only to external providers; local GPU inference is unlimited.
