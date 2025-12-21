# Engine FSM Reconciliation Loop Design

**Date**: 2025-12-20
**Status**: Design Proposal
**Related**: Pre-flight validation, Agent-first architecture

## The Problem

The Gaius Engine manages GPU resources and vLLM processes, but its internal state can drift from reality when:

1. Processes are killed externally (OOM killer, manual pkill, crashes)
2. Port conflicts occur (Tilt, other services)
3. GPU memory isn't freed properly (CUDA context leaks)
4. Engine restarts while processes continue running

The current approach: Engine tracks allocations in memory, but has no mechanism to **reconcile** with ground truth (nvidia-smi, port scans, process table).

## Proposed Solution: FSM-Based Reconciliation

### Core Insight

Each **endpoint** (orchestrator, reasoning, fast, coding, embedding) is an independent finite state machine. The reconciliation loop observes reality and triggers state transitions.

### Endpoint FSM States

```
┌─────────────┐
│   ABSENT    │ ◄─── No process, no GPU allocation
└──────┬──────┘
       │ allocate()
       ▼
┌─────────────┐
│  ALLOCATED  │ ◄─── GPUs reserved, process not started
└──────┬──────┘
       │ start()
       ▼
┌─────────────┐
│  STARTING   │ ◄─── Process launched, health checks pending
└──────┬──────┘
       │ healthy()
       ▼
┌─────────────┐
│   HEALTHY   │ ◄─── Process running, responding to /health
└──────┬──────┘
       │ unhealthy() / crash()
       ▼
┌─────────────┐
│  UNHEALTHY  │ ◄─── Process exists but not responding
└──────┬──────┘
       │ stop() or recover()
       ▼
┌─────────────┐
│  STOPPING   │ ◄─── Graceful shutdown in progress
└──────┬──────┘
       │ stopped()
       ▼
┌─────────────┐
│   ABSENT    │
└─────────────┘

Additional transitions:
- Any state → ORPHANED: Process exists but engine doesn't track it
- ORPHANED → ABSENT: After cleanup
- Any state → FAILED: Unrecoverable error (wrong model, config issue)
```

### Observation Sources

The reconciliation loop gathers observations from multiple sources:

| Source | Provides | Frequency |
|--------|----------|-----------|
| `nvidia-smi` | GPU memory per process, PIDs | 5s |
| `ss -tlnp` | Port → PID mapping | 5s |
| `/proc/<pid>/status` | Process alive, memory | 5s |
| `curl /health` | Endpoint responding | 10s |
| `curl /v1/models` | Model loaded correctly | 30s |

### Reconciliation Algorithm

```python
@dataclass
class EndpointObservation:
    """What we observe about an endpoint."""
    name: str
    expected_state: EndpointState  # What engine thinks

    # From nvidia-smi
    gpu_pids: set[int]  # PIDs using expected GPUs
    gpu_memory_mb: dict[int, int]  # GPU → memory used

    # From ss/netstat
    port_pid: int | None  # PID listening on expected port
    port_in_use: bool

    # From /proc
    tracked_pid_alive: bool

    # From HTTP health
    health_ok: bool
    model_loaded: str | None


def reconcile(obs: EndpointObservation) -> EndpointState:
    """Determine actual state from observations."""

    # Case 1: Engine thinks HEALTHY but process dead
    if obs.expected_state == HEALTHY and not obs.tracked_pid_alive:
        return ORPHANED  # GPU may still be allocated

    # Case 2: Engine thinks ABSENT but something on port
    if obs.expected_state == ABSENT and obs.port_in_use:
        if obs.model_loaded == expected_model(obs.name):
            return HEALTHY  # Externally started, adopt it
        else:
            return CONFLICT  # Wrong service on our port

    # Case 3: Engine thinks HEALTHY but health fails
    if obs.expected_state == HEALTHY and not obs.health_ok:
        return UNHEALTHY

    # Case 4: GPU memory used but no tracked process
    if obs.gpu_memory_mb and not obs.tracked_pid_alive:
        return ORPHANED  # Leaked GPU memory

    # Case 5: Everything matches
    return obs.expected_state


def remediate(name: str, actual: EndpointState, desired: EndpointState):
    """Take action to move from actual to desired state."""

    if actual == ORPHANED:
        # Kill orphan, free GPU, transition to ABSENT
        kill_orphan_processes(name)
        release_gpu_allocation(name)
        return ABSENT

    if actual == CONFLICT:
        # Log warning, don't kill - might be intentional
        logger.warning(f"Port conflict on {name}, manual intervention needed")
        return CONFLICT

    if actual == UNHEALTHY and desired == HEALTHY:
        # Attempt restart
        restart_endpoint(name)
        return STARTING

    if actual == ABSENT and desired == HEALTHY:
        # Full startup sequence
        allocate_and_start(name)
        return STARTING
```

### Port Allocation Strategy

To coexist with Tilt and K8s services, use **dynamic port allocation** with ranges:

| Service Category | Port Range | Notes |
|------------------|------------|-------|
| vLLM endpoints | 8080-8089 | Engine-managed |
| optillm proxy | 8000 | Fixed |
| Tilt K8s | 9080-9089 | Moved from 8xxx |
| NiFi | 8450 | Fixed |
| Engine gRPC | 50051 | Fixed |
| Prometheus | 9090 | Standard |

The engine should:
1. Check port availability before starting vLLM
2. Dynamically assign from pool if preferred port busy
3. Register actual port in service discovery

### Implementation Phases

**Phase 1: Observation Loop (Week 1)**
- Add `ReconciliationService` with periodic observations
- Implement nvidia-smi parser, port scanner, health checker
- Log discrepancies without taking action

**Phase 2: State Machine (Week 2)**
- Define `EndpointState` enum and transitions
- Add `reconcile()` function to determine actual state
- Update `orchestrator_status` to show actual vs expected

**Phase 3: Remediation (Week 3)**
- Implement `remediate()` actions
- Add configurable policies (auto-restart, alert-only)
- Integration with FMEA failure modes

**Phase 4: Dynamic Ports (Week 4)**
- Port pool manager
- Service discovery registration
- Update optillm to query engine for backends

## FSM Visualization

```
           ┌─────────────────────────────────────────────┐
           │           RECONCILIATION LOOP               │
           │                                             │
           │  ┌─────────┐    ┌─────────┐    ┌────────┐  │
           │  │nvidia-smi│    │ss -tlnp │    │ /health│  │
           │  └────┬────┘    └────┬────┘    └───┬────┘  │
           │       │              │              │       │
           │       └──────────────┼──────────────┘       │
           │                      ▼                      │
           │              ┌──────────────┐               │
           │              │  OBSERVATION │               │
           │              └──────┬───────┘               │
           │                     │                       │
           │                     ▼                       │
           │              ┌──────────────┐               │
           │              │  RECONCILE   │               │
           │              └──────┬───────┘               │
           │                     │                       │
           │         ┌───────────┼───────────┐           │
           │         ▼           ▼           ▼           │
           │    ┌────────┐  ┌────────┐  ┌────────┐       │
           │    │ENDPOINT│  │ENDPOINT│  │ENDPOINT│       │
           │    │  FSM   │  │  FSM   │  │  FSM   │       │
           │    │(orch)  │  │(reason)│  │ (fast) │       │
           │    └────────┘  └────────┘  └────────┘       │
           │                                             │
           └─────────────────────────────────────────────┘
```

## Integration with Pre-flight

The `/preflight` command should use the reconciliation observations:

```python
async def preflight_check() -> list[CheckResult]:
    """Run pre-flight checks using reconciliation data."""

    obs = await reconciliation_service.observe_all()

    results = []

    # Check each endpoint
    for endpoint in obs.endpoints:
        if endpoint.actual_state == endpoint.expected_state:
            results.append(CheckResult(
                name=f"Endpoint {endpoint.name}",
                passed=True,
                message=f"State: {endpoint.actual_state.value}"
            ))
        else:
            results.append(CheckResult(
                name=f"Endpoint {endpoint.name}",
                passed=False,
                message=f"Drift: expected {endpoint.expected_state}, actual {endpoint.actual_state}"
            ))

    return results
```

## Error Codes

Add to Guru Meditation catalog:

| Code | Meaning | Remediation |
|------|---------|-------------|
| `#EN.00000010.DRIFT` | State drift detected | `/health fix engine` |
| `#EN.00000011.ORPHAN` | Orphaned process | Auto-cleanup or `/gpu cleanup` |
| `#EN.00000012.CONFLICT` | Port conflict | Manual intervention |
| `#EN.00000013.GPULEAK` | GPU memory leak | `gpu:deep-cleanup` task |

## Benefits

1. **Self-healing**: Engine automatically recovers from crashes
2. **Observability**: Clear visibility into actual vs expected state
3. **Coexistence**: Dynamic ports allow K8s services alongside vLLM
4. **Pre-flight**: Quick validation before starting work
5. **FMEA integration**: Failure modes mapped to detection and remediation

## Related Work

- Kubernetes controller pattern (reconciliation loops)
- Erlang/OTP supervisors (process monitoring)
- systemd watchdog (health-based restart)
- Consul/Nomad (service discovery + health)
