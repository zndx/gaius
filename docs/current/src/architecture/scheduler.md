# Scheduler

The SchedulerService provides a priority-based job queue for inference requests with XAI budget management and weighted completion time minimization.

## Priority Levels

| Priority | Weight | Use Case |
|----------|--------|----------|
| `CRITICAL` (0) | 1.0 | User-facing interactive requests |
| `HIGH` (1) | 2.0 | Interactive queries |
| `NORMAL` (2) | 4.0 | Background processing |
| `LOW` (3) | 8.0 | Batch operations |
| `EVOLUTION` (4) | 16.0 | Agent evolution (lowest priority) |

Lower weights receive preferential scheduling. Critical requests preempt everything.

## Job Submission

```python
from gaius.engine.services import SchedulerService, InferenceJob, JobPriority

scheduler = SchedulerService()

job = InferenceJob(
    prompt="Analyze the risk factors...",
    priority=JobPriority.HIGH,
    max_tokens=2048,
)
result = await scheduler.submit(job)
```

## XAI Budget

The scheduler tracks daily usage of external AI APIs (xAI Grok) to prevent runaway costs:

```python
budget = scheduler.get_xai_budget()
# budget.daily_remaining: tokens left for today
# budget.daily_limit: configured daily cap
# budget.reset_time: when the budget resets
```

Requests exceeding the budget are rejected with a clear error message.

## Makespan Scheduling

For complex workloads that require multiple inference calls (e.g., agent evolution with candidate generation + evaluation), the scheduler uses makespan optimization to minimize total completion time:

1. Decompose workload into individual inference jobs
2. Assign priorities based on workload urgency
3. Schedule across available endpoints
4. Track completion via the AgendaTracker

See [Makespan Scheduling](./makespan.md) for the optimization details.

## Timeouts

| Context | Default Timeout |
|---------|----------------|
| General gRPC calls | 30s |
| Inference (completions) | 120s |
| Evaluation | 120s |

A 24B model with `cot_reflection` takes 15-20 seconds per completion. Timeouts are set per-call:

```python
result = await client.call("ModelInfer", request, timeout=120)
```

Override the default via `GAIUS_ENGINE_TIMEOUT` environment variable.
