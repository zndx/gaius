# Engine Services

The engine hosts 37 services organized into four groups: resource management, intelligence, data, and external integration. All services run in a single daemon process, enabling zero-cost inter-service calls and shared access to GPU resources.

## Service Groups

### Resource Management

| Service | Purpose |
|---------|---------|
| OrchestratorService | vLLM endpoint lifecycle, GPU allocation, capability-based scheduling |
| SchedulerService | Priority job queue (CRITICAL→EVOLUTION), OR-Tools makespan optimization, XAI budget |
| HealthService | GPU health via pynvml, endpoint liveness, FMEA score computation |
| AgendaTracker | Tracks scheduled endpoint transitions to suppress false-positive health incidents |

### Intelligence

| Service | Purpose |
|---------|---------|
| EvolutionService | Agent prompt optimization via APO/GEPA during GPU idle periods |
| CognitionService | Autonomous thought generation — pattern, connection, curiosity, self-observation |
| CLTService | Cross-Layer Transcoder sparse feature extraction (20,480-dim, ~115 active) |
| TopologyService | Semantic attractor detection, drift monitoring via CLT features |
| NGRCPredictor | Reservoir computing (NVAR) for temporal prediction of embedding trajectories |

### Data

| Service | Purpose |
|---------|---------|
| DatasetService | NiFi SoM dataset generation for agent training |
| FlowSchedulerService | Metaflow pipeline scheduling and execution |
| KBService | Knowledge base CRUD operations |
| LineageService | OpenLineage event materialization into Apache AGE graph |

### External Integration

| Service | Purpose |
|---------|---------|
| XBookmarksService | X (Twitter) bookmark synchronization with folder-first sync |

## Background Tasks

Several services run scheduled background tasks without external cron:

| Task | Service | Schedule | Purpose |
|------|---------|----------|---------|
| `cognition_cycle` | CognitionService | Every 4h | Detect patterns across recent KB entries |
| `self_observation` | CognitionService | Every 8h | Meta-cognitive reflection on thought quality |
| `engine_audit` | CognitionService | Every 12h | System health patterns, resource utilization |
| Evolution cycle | EvolutionService | GPU idle (<30% for 60s) | Agent prompt optimization via APO/GEPA |
| Health check | HealthService | Every 30s | Endpoint liveness polling |
| X bookmark sync | XBookmarksService | Configurable | Folder-first bookmark synchronization |

## Service Dependencies

Services form a directed dependency graph. The orchestrator and scheduler are foundational:

```
OrchestratorService → VLLMController → GPU Pool (6x NVIDIA)
SchedulerService → OrchestratorService → BackendRouter
EvolutionService → SchedulerService (submits jobs at EVOLUTION priority)
CognitionService → SchedulerService (submits jobs at NORMAL priority)
HealthService → GPU Pool (via pynvml, not via orchestrator)
TopologyService → CLTService → circuit-tracer (BluelightAI)
NGRCPredictor → TopologyService (embedding centroid trajectories)
```

## Service Lifecycle

Each service implements a standard lifecycle:

```python
class SomeService:
    async def start(self) -> None:
        """Initialize resources, start background tasks."""
        ...

    async def stop(self) -> None:
        """Clean shutdown, release resources."""
        ...
```

Services are registered at engine startup and torn down in reverse order. Background tasks use `asyncio.create_task()` with structured cancellation on shutdown.

## See Also

- [Orchestrator](./orchestrator.md) — GPU allocation and endpoint lifecycle
- [Scheduler](./scheduler.md) — Priority queue and makespan optimization
- [vLLM Controller](./vllm.md) — Process management and health monitoring
