"""Engine services (orchestrator, scheduler, evolution, health, cognition, CLT)."""

from .orchestrator_service import (
    CleanupResult,
    EndpointStatus,
    OrchestratorService,
)
from .scheduler_service import (
    AgentMetrics,
    InferenceJob,
    JobPriority,
    SchedulerService,
    XAIBudget,
)
from .evolution_service import (
    CycleStatus,
    EvolutionConfig,
    EvolutionCycle,
    EvolutionService,
    EvolutionStrategy,
)
from .health_service import (
    EndpointHealth,
    GPUHealth,
    HealthService,
    SystemHealth,
)
from .cognition_service import (
    CognitionConfig,
    CognitionService,
)
from .dataset_service import (
    BackendNotAvailableError,
    DatasetJob,
    DatasetJobConfig,
    DatasetService,
    DatasetServiceConfig,
    DatasetServiceError,
    GenerationError,
    ProgressEvent,
    ProgressEventType,
)
# CLT service is lazy-loaded to avoid heavy transformer_lens import at startup
# Use: from gaius.engine.services.clt_service import CLTService
# Or just access gaius.engine.services.CLTService (uses __getattr__ below)
from .topology_service import (
    AgentPosition,
    DriftMetrics,
    SemanticAttractor,
    SwarmSnapshot,
    TopologyService,
)
from .ngrc import (
    NGRCConfig,
    NGRCPredictor,
    NGRCPrediction,
    NGRCState,
    predict_future_state,
    train_ngrc_for_domain,
)
from .health_observer_service import (
    HealthIncident,
    HealthObserverService,
    ObserverConfig,
)
from .x_bookmarks_service import (
    XBookmark,
    XBookmarksConfig,
    XBookmarksService,
    XSyncRun,
)

__all__ = [
    # Orchestrator
    "CleanupResult",
    "EndpointStatus",
    "OrchestratorService",
    # Scheduler
    "AgentMetrics",
    "InferenceJob",
    "JobPriority",
    "SchedulerService",
    "XAIBudget",
    # Evolution
    "CycleStatus",
    "EvolutionConfig",
    "EvolutionCycle",
    "EvolutionService",
    "EvolutionStrategy",
    # Health
    "EndpointHealth",
    "GPUHealth",
    "HealthService",
    "SystemHealth",
    # Cognition
    "CognitionConfig",
    "CognitionService",
    # Dataset
    "BackendNotAvailableError",
    "DatasetJob",
    "DatasetJobConfig",
    "DatasetService",
    "DatasetServiceConfig",
    "DatasetServiceError",
    "GenerationError",
    "ProgressEvent",
    "ProgressEventType",
    # CLT
    "AgentCLTState",
    "CLTProjectionBridge",
    "CLTService",
    "SwarmCLTResult",
    # Topology
    "AgentPosition",
    "DriftMetrics",
    "SemanticAttractor",
    "SwarmSnapshot",
    "TopologyService",
    # NG-RC
    "NGRCConfig",
    "NGRCPredictor",
    "NGRCPrediction",
    "NGRCState",
    "predict_future_state",
    "train_ngrc_for_domain",
    # Health Observer
    "HealthIncident",
    "HealthObserverService",
    "ObserverConfig",
    # X Bookmarks
    "XBookmark",
    "XBookmarksConfig",
    "XBookmarksService",
    "XSyncRun",
    # CLT (lazy-loaded)
    "AgentCLTState",
    "CLTProjectionBridge",
    "CLTService",
    "SwarmCLTResult",
]


# Lazy loading for CLT service (avoids heavy transformer_lens import at startup)
_CLT_NAMES = {"AgentCLTState", "CLTProjectionBridge", "CLTService", "SwarmCLTResult"}


def __getattr__(name: str):
    """Lazy-load CLT service components on first access."""
    if name in _CLT_NAMES:
        from .clt_service import (
            AgentCLTState,
            CLTProjectionBridge,
            CLTService,
            SwarmCLTResult,
        )
        return {
            "AgentCLTState": AgentCLTState,
            "CLTProjectionBridge": CLTProjectionBridge,
            "CLTService": CLTService,
            "SwarmCLTResult": SwarmCLTResult,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
