"""Engine services (orchestrator, scheduler, evolution, health, cognition, CLT).

LAZY PACKAGE (PEP 562). This package is the engine's import hub, and an eager
``from .orchestrator_service import ...`` here created a cycle:
``backends/__init__ → backend_router → resources/__init__ → reconciliation →
services.base_daemon → services/__init__ → orchestrator_service → backends``
(partially initialized → ImportError) for anything that imported
``gaius.engine.backends.*`` or ``gaius.engine.resources`` before ``services``
(``gaius.inference.manager``, ``backends.external.xai_backend`` in the flows,
``backends.gunicorn_config``, …). The eager ``gaius.engine.__init__`` used to
mask it by always importing ``.server`` first; now that that package is lazy
(so the protobuf probes stay light), the hub must be lazy too. Every public
name still resolves on first access: ``from gaius.engine.services import
OrchestratorService`` works; ``import gaius.engine.services.base_daemon`` no
longer drags in every service.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# name -> submodule (relative). Kept explicit so a typo fails loudly.
_ATTR_SOURCE: dict[str, str] = {
    # Orchestrator
    "CleanupResult": ".orchestrator_service",
    "EndpointStatus": ".orchestrator_service",
    "OrchestratorService": ".orchestrator_service",
    # Scheduler
    "AgentMetrics": ".scheduler_service",
    "InferenceJob": ".scheduler_service",
    "JobPriority": ".scheduler_service",
    "SchedulerService": ".scheduler_service",
    "XAIBudget": ".scheduler_service",
    # Evolution
    "CycleStatus": ".evolution_service",
    "EvolutionConfig": ".evolution_service",
    "EvolutionCycle": ".evolution_service",
    "EvolutionService": ".evolution_service",
    "EvolutionStrategy": ".evolution_service",
    # Health
    "EndpointHealth": ".health_service",
    "GPUHealth": ".health_service",
    "HealthService": ".health_service",
    "SystemHealth": ".health_service",
    # Cognition
    "CognitionConfig": ".cognition_service",
    "CognitionService": ".cognition_service",
    # Dataset
    "BackendNotAvailableError": ".dataset_service",
    "DatasetJob": ".dataset_service",
    "DatasetJobConfig": ".dataset_service",
    "DatasetService": ".dataset_service",
    "DatasetServiceConfig": ".dataset_service",
    "DatasetServiceError": ".dataset_service",
    "GenerationError": ".dataset_service",
    "ProgressEvent": ".dataset_service",
    "ProgressEventType": ".dataset_service",
    # CLT (heavy transformer_lens import — was already lazy)
    "AgentCLTState": ".clt_service",
    "CLTProjectionBridge": ".clt_service",
    "CLTService": ".clt_service",
    "SwarmCLTResult": ".clt_service",
    # Topology
    "AgentPosition": ".topology_service",
    "DriftMetrics": ".topology_service",
    "SemanticAttractor": ".topology_service",
    "SwarmSnapshot": ".topology_service",
    "TopologyService": ".topology_service",
    # NG-RC
    "NGRCConfig": ".ngrc",
    "NGRCPredictor": ".ngrc",
    "NGRCPrediction": ".ngrc",
    "NGRCState": ".ngrc",
    "predict_future_state": ".ngrc",
    "train_ngrc_for_domain": ".ngrc",
    # Health Observer
    "HealthIncident": ".health_observer_service",
    "HealthObserverService": ".health_observer_service",
    "ObserverConfig": ".health_observer_service",
    # X Bookmarks
    "XBookmark": ".x_bookmarks_service",
    "XBookmarksConfig": ".x_bookmarks_service",
    "XBookmarksService": ".x_bookmarks_service",
    "XSyncRun": ".x_bookmarks_service",
    # Prospects/Stewardship
    "CandidateInfo": ".prospects_service",
    "ProspectsConfig": ".prospects_service",
    "ProspectsError": ".prospects_service",
    "ProspectsService": ".prospects_service",
    "StrategyInfo": ".prospects_service",
    # FMP Client
    "CompanyProfile": ".fmp_client",
    "FMPClient": ".fmp_client",
    "FMPClientConfig": ".fmp_client",
    "FMPClientError": ".fmp_client",
    "InstitutionalHolder": ".fmp_client",
    "SECFiling": ".fmp_client",
    # Prospects Analysis
    "AnalysisError": ".prospects_analysis",
    "FilingAnalysis": ".prospects_analysis",
    "PositionSynthesis": ".prospects_analysis",
    "ProspectsAnalyzer": ".prospects_analysis",
    # Vector Search
    "VectorSearchConfig": ".vector_search_service",
    "VectorSearchService": ".vector_search_service",
    # Collections
    "Card": ".collection_service",
    "Collection": ".collection_service",
    "CollectionConfig": ".collection_service",
    "CollectionError": ".collection_service",
    "CollectionService": ".collection_service",
    "Source": ".collection_service",
}

__all__ = sorted(_ATTR_SOURCE)


def __getattr__(name: str):
    """PEP 562 lazy attribute resolution — imports the backing module on demand."""
    source = _ATTR_SOURCE.get(name)
    if source is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(source, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return list(__all__)


if TYPE_CHECKING:  # static analysers see the real symbols; nothing runs at import
    from .clt_service import AgentCLTState, CLTProjectionBridge, CLTService, SwarmCLTResult
    from .cognition_service import CognitionConfig, CognitionService
    from .collection_service import Card, Collection, CollectionConfig, CollectionError, CollectionService, Source
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
    from .evolution_service import CycleStatus, EvolutionConfig, EvolutionCycle, EvolutionService, EvolutionStrategy
    from .fmp_client import CompanyProfile, FMPClient, FMPClientConfig, FMPClientError, InstitutionalHolder, SECFiling
    from .health_observer_service import HealthIncident, HealthObserverService, ObserverConfig
    from .health_service import EndpointHealth, GPUHealth, HealthService, SystemHealth
    from .ngrc import NGRCConfig, NGRCPrediction, NGRCPredictor, NGRCState, predict_future_state, train_ngrc_for_domain
    from .orchestrator_service import CleanupResult, EndpointStatus, OrchestratorService
    from .prospects_analysis import AnalysisError, FilingAnalysis, PositionSynthesis, ProspectsAnalyzer
    from .prospects_service import CandidateInfo, ProspectsConfig, ProspectsError, ProspectsService, StrategyInfo
    from .scheduler_service import AgentMetrics, InferenceJob, JobPriority, SchedulerService, XAIBudget
    from .topology_service import AgentPosition, DriftMetrics, SemanticAttractor, SwarmSnapshot, TopologyService
    from .vector_search_service import VectorSearchConfig, VectorSearchService
    from .x_bookmarks_service import XBookmark, XBookmarksConfig, XBookmarksService, XSyncRun
