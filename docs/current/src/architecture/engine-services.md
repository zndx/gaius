# Engine Services

The engine hosts 37 services organized into four groups: resource management, intelligence, data, and external integration.

## Service Groups

### Resource Management

| Service | Purpose |
|---------|---------|
| OrchestratorService | vLLM endpoint lifecycle and GPU allocation |
| SchedulerService | Priority-based job queue with XAI budget |
| HealthService | GPU and endpoint health monitoring |
| AgendaTracker | Tracks scheduled endpoint transitions for makespan operations |

### Intelligence

| Service | Purpose |
|---------|---------|
| EvolutionService | Agent prompt optimization via APO |
| CognitionService | Autonomous thought generation (every 4h) |
| CLTService | Cross-Layer Transcoder feature extraction |
| TopologyService | Semantic attractor detection and drift |
| NGRCPredictor | Reservoir computing for temporal prediction |

### Data

| Service | Purpose |
|---------|---------|
| DatasetService | NiFi SoM dataset generation |
| FlowSchedulerService | Metaflow pipeline scheduling |
| KBService | Knowledge base CRUD operations |
| LineageService | Provenance tracking |

### External Integration

| Service | Purpose |
|---------|---------|
| XBookmarksService | X (Twitter) bookmark synchronization |

## Service Registration

Services register with the engine during startup. Each service implements a standard lifecycle:

```python
class SomeService:
    async def start(self) -> None:
        """Initialize resources, start background tasks."""
        ...

    async def stop(self) -> None:
        """Clean shutdown, release resources."""
        ...
```

## Background Tasks

Several services run scheduled background tasks:

| Task | Service | Schedule | Purpose |
|------|---------|----------|---------|
| `cognition_cycle` | CognitionService | Every 4h | Pattern detection in KB activity |
| `self_observation` | CognitionService | Every 8h | Meta-cognitive reflection |
| `engine_audit` | CognitionService | Every 12h | System health analysis |
| Evolution cycle | EvolutionService | GPU idle | Agent prompt optimization |
| Health check | HealthService | Every 30s | Endpoint liveness |

## Service Dependencies

Services form a dependency graph. The orchestrator and scheduler are foundational — most other services depend on them for inference access:

```
OrchestratorService → vLLM Controller → GPU Pool
SchedulerService → OrchestratorService
EvolutionService → SchedulerService
CognitionService → SchedulerService
HealthService → GPU Pool (via pynvml)
TopologyService → CLTService
```

See the individual service chapters for implementation details:
- [Orchestrator](./orchestrator.md)
- [Scheduler](./scheduler.md)
