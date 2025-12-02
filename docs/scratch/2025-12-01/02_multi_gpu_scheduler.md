# Multi-GPU Inference Scheduler

**Date**: 2025-12-01
**Status**: Core capability implemented

## Overview

Intelligent inference scheduling across 6x 4090 GPUs using OR-Tools CP-SAT solver for optimal job assignment. Implemented as a core Gaius capability with:

- **SchedulerService**: Full job lifecycle management
- **CLI Commands**: `/scheduler`, `/submit`, `/swarm`
- **MCP Tools**: 6 scheduler-related tools for Claude Code integration
- **Event System**: Job lifecycle events for real-time updates
- **App Integration**: Auto-starts with Gaius TUI

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     InferenceScheduler                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Job Queue   │  │  OR-Tools    │  │  Endpoint    │          │
│  │  (Priority)  │→ │  CP-SAT      │→ │  Router      │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────┬─────────────┬─────────────┬─────────────┐
    │  GPU 0-1    │   GPU 2     │   GPU 3     │   GPU 4     │
    │  reasoning  │   coding    │    fast     │  orchestr.  │
    │  QwQ-32B    │  Qwen3-30B  │  Mistral-7B │  Orch-8B    │
    └─────────────┴─────────────┴─────────────┴─────────────┘
                                                    │
                                              ┌─────────────┐
                                              │   GPU 5     │
                                              │   standby   │
                                              │  (dynamic)  │
                                              └─────────────┘
```

## Key Components

### 1. Job (`inference/scheduler.py`)
```python
@dataclass
class Job:
    model: str              # Required model
    messages: list          # Chat messages
    priority: JobPriority   # CRITICAL, HIGH, NORMAL, LOW
    deadline_ms: int        # Max acceptable latency
    estimated_tokens: int   # For duration estimation
    role: str | None        # Agent role for affinity
```

### 2. EndpointState
Tracks each GPU endpoint:
- Current loaded model (warm vs cold)
- Queue depth
- VRAM usage
- Health status
- Throughput estimates (tokens/sec)

### 3. Scheduling Algorithms

**Single Job (Heuristic)**:
```
score = (model_load_time + inference_duration + queue_wait)
        × priority_factor
        + affinity_bonus
```

**Batch (OR-Tools CP-SAT)**:
- Decision vars: `x[job, endpoint]` ∈ {0, 1}
- Constraints:
  - Each job → exactly one endpoint
  - Endpoint queue ≤ max capacity
- Objective: Minimize weighted makespan

### 4. Model Affinity
Avoids cold starts by preferring endpoints with warm models:
- Warm model bonus: -3000ms to score
- Preferred endpoint: -5000ms to score

## Usage

```python
from gaius.inference.scheduler import get_scheduler, Job, JobPriority

scheduler = get_scheduler()

# Single job
job = Job(
    model="Qwen/QwQ-32B",
    priority=JobPriority.HIGH,
    deadline_ms=5000,
)
assignment = await scheduler.schedule(job)
print(f"→ {assignment.endpoint}, ETA: {assignment.estimated_duration_ms}ms")

# Swarm scheduling (optimal distribution)
from gaius.agents.roles import AgentRole
assignments = await scheduler.schedule_swarm(
    roles=[AgentRole.LEADER, AgentRole.RISK, ...],
    domain="pension asset allocation",
)
```

## Configuration

In `config/base.conf`:
```hocon
inference.endpoints {
  reasoning {
    url = "http://localhost:8081/v1"
    models = ["Qwen/QwQ-32B"]
    gpus = [0, 1]
    tensor_parallel = 2
  }
  coding { ... }
  fast { ... }
}
```

## Installation

```bash
# With OR-Tools for optimal scheduling
uv sync --extra scheduler

# Without (uses greedy heuristic)
uv sync
```

## Swarm Scheduling Example

For 7 agents with different model preferences:

| Agent     | Model        | Endpoint   | Reason           |
|-----------|--------------|------------|------------------|
| Leader    | QwQ-32B      | reasoning  | Strong reasoning |
| Critic    | QwQ-32B      | reasoning  | Find flaws       |
| Planner   | Qwen3-Coder  | coding     | Structured plans |
| Executor  | Qwen3-Coder  | coding     | Implementation   |
| Risk      | Mistral-7B   | fast       | Speed            |
| Optimizer | Mistral-7B   | fast       | Speed            |
| Adversary | grok-2       | (API)      | Frontier model   |

OR-Tools optimizes the distribution to:
1. Minimize total completion time
2. Avoid model loading (prefer warm endpoints)
3. Balance queue depth across GPUs
4. Respect priority ordering

## API Summary

### SchedulerService

```python
from gaius.inference.scheduler import get_scheduler_service

service = get_scheduler_service()

# Submit and wait
result = await service.submit(job)

# Submit async (background)
job_id = await service.submit_async(job)
result = await service.wait_for_result(job_id)

# Run swarm with optimal distribution
results = await service.run_swarm(domain="pension", roles=[...])

# Health & metrics
health = await service.health_check()
metrics = service.get_metrics()
```

### CLI Commands

```bash
# Check scheduler status
uv run gaius-cli --cmd "/scheduler status"

# Submit a job
uv run gaius-cli --cmd "/submit priority:high What is 2+2?"

# Run swarm analysis
uv run gaius-cli --cmd "/swarm pension risk assessment"
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `scheduler_status` | Get endpoints, queue, metrics |
| `scheduler_submit` | Submit job and wait |
| `scheduler_submit_async` | Submit for background execution |
| `scheduler_get_result` | Get result by job ID |
| `scheduler_run_swarm` | Run swarm with optimal scheduling |
| `scheduler_health_check` | Check endpoint health |
| `scheduler_metrics` | Get performance metrics |

### Event System

```python
from gaius.inference.scheduler import JobEvent

async def on_completed(event_data):
    print(f"Job {event_data.job.id} completed on {event_data.endpoint}")

service.on(JobEvent.COMPLETED, on_completed)
```

## Future Enhancements

1. **Job Persistence**: Store jobs in PostgreSQL for durability
2. **Dynamic Model Loading**: Load models on standby GPU on-demand
3. **Preemption**: Interrupt low-priority jobs for critical requests
4. **Batching**: Combine similar requests for throughput
5. **Speculative Execution**: Start on multiple endpoints, use first result
6. **Cost Optimization**: For API models (Grok, OpenAI) balance cost vs latency
