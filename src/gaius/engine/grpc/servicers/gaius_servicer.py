"""Gaius custom service extensions servicer.

This module implements the GaiusService, which provides Gaius-specific
functionality beyond the standard KServe OIP:

- Orchestrator: GPU allocation, endpoint management
- Scheduler: Job submission, completion
- Evolution: Agent optimization daemon
- Grid: Embedding projection to 19x19 grid
- TDA: Topological data analysis
- Streaming: Health metrics and event streams
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, Optional

import grpc
from grpc import aio
from google.protobuf import empty_pb2

from ...generated import (
    # Process Status Enum
    ProcessStatus,
    PROCESS_STATUS_UNSPECIFIED,
    PROCESS_STATUS_STOPPED,
    PROCESS_STATUS_STARTING,
    PROCESS_STATUS_HEALTHY,
    PROCESS_STATUS_UNHEALTHY,
    PROCESS_STATUS_STOPPING,
    PROCESS_STATUS_FAILED,
    PROCESS_STATUS_PENDING,
    # Orchestrator
    OrchestratorStatusResponse,
    GPUAllocation,
    EndpointInfo,
    StartEndpointRequest,
    StopEndpointRequest,
    RestartEndpointRequest,
    CleanStartRequest,
    CleanStartResponse,
    EndpointResponse,
    # Phase Change Pattern
    PhaseChangeRequest,
    PhaseChangeResponse,
    PhaseChangeProfile,
    PhaseChangeProfilesResponse,
    ActivePhaseChange,
    ActivePhaseChangesResponse,
    # Scheduler
    CompleteRequest,
    CompleteResponse,
    SubmitJobRequest,
    SubmitJobResponse,
    GetJobResultRequest,
    GetJobResultResponse,
    SchedulerStatusResponse,
    XAIBudgetResponse,
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
    SwarmResult,
    # Workload Management
    BeginWorkloadRequest,
    BeginWorkloadResponse,
    CompleteWorkloadRequest,
    EndpointAllocationInfo,
    ActiveWorkloadInfo,
    GetActiveWorkloadsResponse,
    WorkloadType as ProtoWorkloadType,
    # Embeddings
    EmbedTextsRequest,
    EmbedTextsResponse,
    EmbeddingVector,
    # Semantic Search
    SemanticSearchRequest,
    SearchResult,
    SemanticSearchResponse,
    SemanticSearchEvent,
    # Evolution
    EvolutionStatusResponse,
    TriggerEvolutionRequest,
    EvolutionCycleResponse,
    # Cognition
    CognitionStatusResponse,
    ThoughtMessage,
    GetRecentThoughtsRequest,
    GetRecentThoughtsResponse,
    TriggerCognitionRequest,
    TriggerCognitionResponse,
    CognitionActivityResponse,
    CognitionSurfaceRequest,
    CognitionSurfaceResponse,
    CognitionWaterfallRequest,
    CognitionWaterfallResponse,
    CognitionDayBucket,
    CognitionHourCell,
    CognitionStreamCount,
    SelfObservationRequest,
    SelfObservationResponse,
    EngineAuditRequest,
    EngineAuditResponse,
    # State Service (Thin Client Architecture)
    GetStateRequest,
    GridState,
    TDAFeatures as ProtoTDAFeatures,
    BoundingBox as ProtoBoundingBox,
    GeometryFeatures,
    GradientVector,
    SubscribeStateRequest,
    StateUpdate,
    GetPreferencesRequest,
    UIPreferences,
    SavePreferencesRequest,
    PruneSnapshotsRequest,
    PruneSnapshotsResponse,
    # Health
    HealthStreamRequest,
    HealthMetrics,
    GPUMetrics,
    EndpointHealth,
    # Events
    EventStreamRequest,
    Event,
    # Grid
    ProjectEmbeddingsRequest,
    GridPosition,
    ProjectEmbeddingsResponse,
    ProjectQueryRequest,
    ProjectQueryResponse,
    # TDA
    ComputeTDARequest,
    PersistenceInterval,
    TDAResponse,
    # Explain (Grid Position Interpretation)
    ExplainRequest,
    ExplainResponse,
    # Init streaming
    InitCommand,
    InitEvent,
    # Command Service (Unified Entry Point)
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    # Init/Reindex (Heavy Compute)
    InitRequest,
    InitResponse,
    InitProgress,
    ReindexRequest,
    ReindexResponse,
    ReindexProgress,
    # Dataset Generation
    DatasetGenerationRequest,
    DatasetJobStatus,
    DatasetProgressEvent,
    GetDatasetJobRequest,
    CancelDatasetJobRequest,
    DatasetLineageRequest,
    DatasetLineageResponse,
    LineageNode,
    LineageEdge,
    # MetaAgent (Analytics Query)
    MetaAgentQueryRequest,
    MetaAgentQueryResponse,
    MetaAgentEvent,
    # MetaAgent Service (Sync, Audit, Budget)
    MetaAgentStatusRequest,
    MetaAgentStatusResponse,
    MetabaseSyncRequest,
    MetabaseSyncResponse,
    MetaAgentAuditRequest,
    MetaAgentAuditResponse,
    AuditFinding,
    AuditRecommendation,
    PooledBudgetStatus,
    GetPooledBudgetRequest,
    GetPooledBudgetResponse,
    QualityAssessment,
    GetQualitySummaryRequest,
    GetQualitySummaryResponse,
    ListRecommendationsRequest,
    ListRecommendationsResponse,
    UpdateRecommendationRequest,
    UpdateRecommendationResponse,
    # ThetaAgent
    ThetaSitrepRequest,
    ThetaSitrepResponse,
    ThetaConsolidateRequest,
    ThetaConsolidateResponse,
    ThetaConsolidationStatsRequest,
    ThetaConsolidationStatsResponse,
    ThetaAgendaRequest,
    ThetaAgendaResponse,
    ThetaAgendaItem,
    AgendaCheck,
    AgendaCard,
    AgendaListRequest,
    AgendaListResponse,
    AgendaGetRequest,
    AgendaGetResponse,
    AgendaCreateRequest,
    AgendaCreateResponse,
    AgendaUpdateRequest,
    AgendaUpdateResponse,
    WeeklySignalsRemote,
    WeeklySignalsSummaryRequest,
    WeeklySignalsSummaryResponse,
    WeeklySignalsSummaryListRequest,
    WeeklySignalsSummaryListResponse,
    WeeklySignalsSummaryGetRequest,
    WeeklySignalsSummaryGetResponse,
    KnowledgeSummaryRequest,
    KnowledgeSummaryResponse,
    KnowledgeSummaryWritten,
    FederationSurfacesRequest,
    FederationSurfacesResponse,
    FederationSurface,
    AskPresentRequest,
    AskPresentResponse,
    SummaryNote as ProtoSummaryNote,
    SummaryIndexRequest,
    SummaryIndexResponse,
    SummaryGetRequest,
    SummaryGetResponse,
    SummaryHopRequest,
    SummaryHopResponse,
    SummaryForkRequest,
    SummaryForkResponse,
    SummarySchedule as ProtoSummarySchedule,
    SummarySchedulesRequest,
    SummarySchedulesResponse,
    SummaryScheduleTriggerRequest,
    SummaryScheduleTriggerResponse,
    DiscoverSurfaceRequest,
    DiscoverSurfaceResponse,
    DiscoverBucket as ProtoDiscoverBucket,
    DiscoverDoc as ProtoDiscoverDoc,
    DiscoverFacet as ProtoDiscoverFacet,
    DiscoverEpisode as ProtoDiscoverEpisode,
    DiscoverStatus as ProtoDiscoverStatus,
    RefreshDiscoverLandingRequest,
    RefreshDiscoverLandingResponse,
    # CLT (Cross-Layer Transcoders)
    CLTExtractRequest,
    CLTExtractResponse,
    SparseFeature as ProtoSparseFeature,
    CLTAttributeRequest,
    CLTAttributeResponse,
    CLTAttributionEdge as ProtoAttributionEdge,
    CLTStatusRequest,
    CLTStatusResponse,
    # HealthObserver
    HealthObserverStatusRequest,
    HealthObserverStatusResponse,
    HealthIncident as ProtoHealthIncident,
    HealthObserverMetrics as ProtoHealthObserverMetrics,
    HealthObserverConfig as ProtoHealthObserverConfig,
    ForceHealthCheckRequest,
    ForceHealthCheckResponse,
    HealthCheckResult,
    GetIncidentDetailRequest,
    GetIncidentDetailResponse,
    ListIncidentsRequest,
    ListIncidentsResponse,
    ResolveIncidentRequest,
    ResolveIncidentResponse,
    GetOrphanedIssuesRequest,
    GetOrphanedIssuesResponse,
    OrphanedGitHubIssue,
    # Observability Dashboard
    ObserveStatusRequest,
    ObserveStatusResponse,
    MetricSnapshot,
    EndpointSnapshot,
    SignalsTelemetryRequest,
    SignalsTelemetryResponse,
    GpuWatt,
    # X Bookmarks
    XBookmarksAuthRequest,
    XBookmarksAuthResponse,
    XBookmarksCompleteAuthByStateRequest,
    XBookmarksCompleteAuthRequest,
    XBookmarksCompleteAuthResponse,
    XBookmarksAuthStatusRequest,
    XBookmarksAuthStatusResponse,
    XBookmarksSyncRequest,
    XBookmarksSyncResponse,
    XBookmarksSyncStatusRequest,
    XBookmarksSyncStatusResponse,
    XBookmarksServiceStatusRequest,
    XBookmarksServiceStatusResponse,
    XBookmarksListFoldersRequest,
    XBookmarksListFoldersResponse,
    XBookmarkFolder,
    XBookmarksQueueStatusRequest,
    XBookmarksQueueStatusResponse,
    XBookmarksEmitTestEventRequest,
    XBookmarksEmitTestEventResponse,
    # Ambient Computing Workload
    AmbientCycleRequest,
    AmbientPhaseEvent,
    AmbientStatusResponse,
    AmbientCycleResponse,
    AmbientStartRequest,
    AmbientStartResponse,
    AmbientStopRequest,
    AmbientStopResponse,
    AmbientSubscribeRequest,
    AmbientBufferExportRequest,
    AmbientBufferExportResponse,
    AMBIENT_PHASE_UNSPECIFIED,
    # HuggingFace Dataset Discovery
    ListHFDatasetsRequest,
    ListHFDatasetsResponse,
    HFDatasetInfo,
    AddExternalDatasetRequest,
    AddExternalDatasetResponse,
    GetHFDatasetInfoRequest,
    GetHFDatasetInfoResponse,
    ListKBDatasetsRequest,
    ListKBDatasetsResponse,
    KBDatasetEntry,
    # HuggingFace Model Discovery
    ListHFModelsRequest,
    ListHFModelsResponse,
    HFModelInfo,
    AddExternalModelRequest,
    AddExternalModelResponse,
    GetHFModelInfoRequest,
    GetHFModelInfoResponse,
    ListKBModelsRequest,
    ListKBModelsResponse,
    KBModelEntry,
    AMBIENT_PHASE_BASELINE_HEALTH,
    AMBIENT_PHASE_BASELINE_WORKLOAD,
    AMBIENT_PHASE_REASONING_EVICTION,
    AMBIENT_PHASE_REASONING_WORKLOAD,
    AMBIENT_PHASE_BASELINE_RESTORATION,
    AMBIENT_PHASE_COMPLETE,
    AMBIENT_PHASE_ERROR,
    # Prospects/Stewardship
    CandidateSummary,
    StrategySummary,
    ProspectsStatusRequest,
    ProspectsStatusResponse,
    ProspectsCheckRequest,
    ProspectsCheckResponse,
    ProspectsUpdateRequest,
    ProspectsUpdateEvent,
    # Collections (Public Content Landing Page)
    CollectionInfo,
    CardInfo,
    CollectionStatusRequest,
    CollectionStatusResponse,
    CollectionListRequest,
    CollectionListResponse,
    CollectionCreateRequest,
    CollectionCreateResponse,
    CollectionSetFeaturedRequest,
    CollectionSetFeaturedResponse,
    CollectionAddCardRequest,
    CollectionAddCardResponse,
    CollectionListCardsRequest,
    CollectionListCardsResponse,
    CollectionPublishCardsRequest,
    CollectionPublishCardsResponse,
    CollectionPublishVizRequest,
    CollectionPublishVizResponse,
    CollectionSyncThemeRequest,
    CollectionSyncThemeResponse,
    # Article Curation (gRPC-First)
    ArticleInfo,
    CurationRunInfo,
    ArticleStatusRequest,
    ArticleStatusResponse,
    ArticleNewRequest,
    ArticleNewResponse,
    ArticleCurationEvent,
    ArticleCurateRequest,
    # Rendering (Blender Card Visualization)
    RenderCardsRequest,
    RenderCardEvent,
    RENDER_PHASE_FAILED,
    # Multi-Phase Search Flow
    SearchFlowRequest,
    WebSearchResult,
    SearchFlowResult,
    SearchFlowEvent,
    # Deep Research Flow (MemRL)
    ResearchFlowRequest,
    ResearchFlowResult,
    ResearchFlowEvent,
    ResearchFlowStatusResponse,
    ResearchFlowStopResponse,
    # Servicer base
    GaiusServiceServicer,
)

from ...metrics import record_exception_caught

if TYPE_CHECKING:
    from ..server import ServiceRegistry
    from ...services.research_workload_service import ResearchWorkloadService

logger = logging.getLogger(__name__)


# Map string status values to ProcessStatus enum
_STATUS_MAP = {
    "stopped": PROCESS_STATUS_STOPPED,
    "starting": PROCESS_STATUS_STARTING,
    "healthy": PROCESS_STATUS_HEALTHY,
    "running": PROCESS_STATUS_HEALTHY,  # alias for healthy
    "ready": PROCESS_STATUS_HEALTHY,  # alias for healthy (used by InitController)
    "unhealthy": PROCESS_STATUS_UNHEALTHY,
    "stopping": PROCESS_STATUS_STOPPING,
    "failed": PROCESS_STATUS_FAILED,
    "error": PROCESS_STATUS_FAILED,  # alias for failed
    "pending": PROCESS_STATUS_PENDING,  # queued for startup
}


def _status_to_enum(status_str: str) -> ProcessStatus:
    """Convert string status to ProcessStatus enum value."""
    return _STATUS_MAP.get(status_str.lower(), PROCESS_STATUS_UNSPECIFIED)


def _summary_db(services: object) -> object | None:
    pool = getattr(services, "db_pool", None) or getattr(services, "_db_pool", None)
    if pool is not None:
        return pool
    cog = getattr(services, "cognition_service", None)
    if cog is not None:
        return getattr(cog, "_db_pool", None)
    return None


class GaiusServicer(GaiusServiceServicer):
    """Gaius custom extensions servicer.

    Implements the GaiusService gRPC interface for Gaius-specific operations
    like orchestrator management, evolution control, and streaming.
    """

    def __init__(self, services: "ServiceRegistry"):
        self._services = services
        self._event_subscribers: list[asyncio.Queue] = []
        # Cached research service for status/stop operations
        self._research_service: "ResearchWorkloadService | None" = None

    def _get_free_gpu(self) -> int:
        """Get a free GPU from ResourceManager.

        Uses the orchestrator's ResourceManager to find unallocated GPUs,
        which is more reliable than parsing nvidia-smi output.

        Returns:
            GPU index that is free, or highest-numbered GPU as fallback.
        """
        orchestrator = self._services.orchestrator_service
        if orchestrator and hasattr(orchestrator, "resource_manager"):
            free_gpus = orchestrator.resource_manager.get_free_gpus()
            if free_gpus:
                # Prefer highest-numbered GPU (vLLM endpoints use lower ones)
                gpu = max(free_gpus)
                logger.debug(f"ResourceManager selected GPU {gpu} from free: {free_gpus}")
                return gpu

        # Fallback: use highest GPU (likely free since vLLM uses 0,1,2,3)
        config = self._services.config
        if config and hasattr(config, "gpus"):
            fallback = config.gpus.total - 1
            logger.debug(f"No ResourceManager, falling back to GPU {fallback}")
            return fallback

        logger.debug("No config available, falling back to GPU 0")
        return 0

    # =========================================================================
    # Orchestrator
    # =========================================================================

    async def OrchestratorStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> OrchestratorStatusResponse:
        """Get orchestrator status including GPU allocations."""
        config = self._services.config
        orchestrator = self._services.orchestrator_service
        init_controller = self._services.init_controller

        response = OrchestratorStatusResponse(
            total_gpus=0,
            available_gpus=0,
        )

        if config:
            response.total_gpus = config.gpus.total
            response.available_gpus = config.gpus.total - len(config.gpus.reserved)

        # Track which endpoints we've already added
        seen_endpoints = set()

        # Use OrchestratorService if available (preferred)
        if orchestrator:
            status = orchestrator.get_status()
            for alias, ep in status.get("endpoints", {}).items():
                endpoint = EndpointInfo(
                    name=alias,
                    model=ep.get("model", ""),
                    status=_status_to_enum(ep.get("status", "stopped")),
                    port=ep.get("port", 0),
                )
                response.endpoints.append(endpoint)
                seen_endpoints.add(alias)

        # Add pending endpoints from InitController that haven't been started yet
        # This surfaces endpoints that are queued for startup during initialization
        if init_controller:
            for ep_name, ep_progress in init_controller.state.endpoints.items():
                if ep_name not in seen_endpoints:
                    # Map init_controller status to proto status
                    # "pending" -> PENDING, "starting" -> STARTING, "ready" -> HEALTHY
                    init_status = ep_progress.status
                    endpoint = EndpointInfo(
                        name=ep_name,
                        model="",  # Not available until started
                        status=_status_to_enum(init_status),
                        port=0,  # Not allocated until started
                    )
                    response.endpoints.append(endpoint)
                    seen_endpoints.add(ep_name)

        if seen_endpoints:
            return response

        # Fallback to backend router (no endpoints from orchestrator or init_controller)
        router = self._services.backend_router
        if router:
            status = router.get_status()
            for name, backend in status.get("backends", {}).items():
                if backend.get("healthy", False):
                    endpoint = EndpointInfo(
                        name=name,
                        model=backend.get("model", ""),
                        status=_status_to_enum("healthy" if backend.get("healthy") else "stopped"),
                        port=backend.get("port", 0),
                    )
                    response.endpoints.append(endpoint)

        return response

    async def EnsureEndpoint(
        self,
        request: StartEndpointRequest,
        context: aio.ServicerContext,
    ):
        """Ensure endpoint is running (agent-first architecture).

        This is the primary method for agents to request endpoints.
        It checks resource availability and starts the endpoint if needed.
        """
        from ...generated import EnsureEndpointResponse

        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EnsureEndpointResponse(
                healthy=False,
                status="error",
                message="OrchestratorService not initialized",
            )

        try:
            status = await orchestrator.ensure_endpoint(endpoint_name)
            return EnsureEndpointResponse(
                healthy=status.status in ("healthy", "optillm"),
                status=status.status,
                port=status.port or 0,
                gpu_ids=list(status.gpu_ids) if status.gpu_ids else [],
                message=status.startup_message or "",
            )
        except ValueError as e:
            return EnsureEndpointResponse(
                healthy=False,
                status="error",
                message=str(e),
            )
        except Exception as e:
            logger.error(f"Failed to ensure endpoint {endpoint_name}: {e}")
            return EnsureEndpointResponse(
                healthy=False,
                status="error",
                message=str(e),
            )

    async def StartEndpoint(
        self,
        request: StartEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Start an inference endpoint."""
        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EndpointResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            status = await orchestrator.start_endpoint(endpoint_name)
            return EndpointResponse(
                success=status.status in ("healthy", "starting", "optillm"),
                message=f"Endpoint '{endpoint_name}' started (status: {status.status}, port: {status.port or 0})",
            )
        except ValueError as e:
            return EndpointResponse(success=False, message=str(e))
        except Exception as e:
            logger.error(f"Failed to start endpoint {endpoint_name}: {e}")
            return EndpointResponse(success=False, message=str(e))

    async def StopEndpoint(
        self,
        request: StopEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Stop an inference endpoint."""
        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EndpointResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            success = await orchestrator.stop_endpoint(endpoint_name)
            return EndpointResponse(
                success=success,
                message=f"Endpoint '{endpoint_name}' stopped" if success else f"Failed to stop '{endpoint_name}'",
            )
        except Exception as e:
            logger.error(f"Failed to stop endpoint {endpoint_name}: {e}")
            return EndpointResponse(success=False, message=str(e))

    async def RestartEndpoint(
        self,
        request: RestartEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Restart an inference endpoint."""
        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EndpointResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            status = await orchestrator.restart_endpoint(endpoint_name)
            return EndpointResponse(
                success=status.status in ("healthy", "starting"),
                message=f"Endpoint '{endpoint_name}' restarted (status: {status.status}, port: {status.port or 0})",
            )
        except Exception as e:
            logger.error(f"Failed to restart endpoint {endpoint_name}: {e}")
            return EndpointResponse(success=False, message=str(e))

    async def CleanStart(
        self,
        request: CleanStartRequest,
        context: aio.ServicerContext,
    ) -> CleanStartResponse:
        """Kill stale processes and optionally start endpoints."""
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return CleanStartResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            endpoints = list(request.endpoints) if request.endpoints else []
            result = await orchestrator.clean_start(endpoints)

            # Extract counts from result
            processes_killed = 0
            endpoints_started = 0
            if isinstance(result, dict):
                cleanup = result.get("cleanup", {})
                processes_killed = cleanup.get("processes_killed", 0)
                endpoints_started = len(result.get("started", []))

            return CleanStartResponse(
                success=True,
                message=f"Clean start completed: killed {processes_killed} processes, started {endpoints_started} endpoints",
                processes_killed=processes_killed,
                endpoints_started=endpoints_started,
            )
        except Exception as e:
            logger.error(f"Failed to clean start: {e}")
            return CleanStartResponse(success=False, message=str(e))

    # =========================================================================
    # Phase Change Pattern - Resilient Dynamic Workload Coordination
    # =========================================================================

    async def PhaseChange(
        self,
        request: PhaseChangeRequest,
        context: aio.ServicerContext,
    ) -> PhaseChangeResponse:
        """Execute a phase change with convergence waiting.

        Waits for the target endpoint to reach HEALTHY status before returning.
        Accumulates timing statistics for future decision support.
        """
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return PhaseChangeResponse(
                converged=False,
                status="failed",
                error_message="OrchestratorService not initialized",
            )

        try:
            result = await orchestrator.phase_change(
                change_type=request.change_type,
                target_endpoint=request.target_endpoint,
                await_healthy=request.await_healthy,
                timeout_s=request.timeout_s if request.timeout_s > 0 else 120.0,
            )

            return PhaseChangeResponse(
                converged=result.get("converged", False),
                status=result.get("endpoint_status", "unknown"),  # orchestrator returns endpoint_status
                duration_ms=result.get("duration_ms", 0),
                change_type=request.change_type,
                target_endpoint=request.target_endpoint,
                error_message=result.get("error", ""),  # orchestrator returns error, not error_message
                otel_trace_id=result.get("otel_trace_id", ""),
            )
        except Exception as e:
            logger.error(f"Phase change failed: {e}")
            return PhaseChangeResponse(
                converged=False,
                status="failed",
                error_message=str(e),
            )

    async def GetPhaseChangeProfiles(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> PhaseChangeProfilesResponse:
        """Get phase change timing statistics."""
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return PhaseChangeProfilesResponse()

        try:
            profiles_dict = orchestrator.get_phase_change_profiles()
            profiles = []

            for change_type, data in profiles_dict.items():
                profile = PhaseChangeProfile(
                    change_type=change_type,
                    sample_count=data.get("sample_count", 0),
                    total_duration_ms=data.get("total_duration_ms", 0),
                    min_duration_ms=data.get("min_duration_ms") or 0,
                    max_duration_ms=data.get("max_duration_ms") or 0,
                    avg_duration_ms=data.get("avg_duration_ms") or 0.0,
                    failures=data.get("failures", 0),
                    failure_rate=data.get("failure_rate", 0.0),
                    has_statistical_power=data.get("has_statistical_power", False),
                )
                profiles.append(profile)

            return PhaseChangeProfilesResponse(profiles=profiles)
        except Exception as e:
            logger.error(f"Failed to get phase change profiles: {e}")
            return PhaseChangeProfilesResponse()

    async def GetActivePhaseChanges(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> ActivePhaseChangesResponse:
        """Get currently active phase changes."""
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return ActivePhaseChangesResponse()

        try:
            changes_list = orchestrator.get_active_phase_changes()
            changes = []

            for data in changes_list:
                change = ActivePhaseChange(
                    change_type=data.get("change_type", ""),
                    status=data.get("status", ""),
                    target_endpoint=data.get("target_endpoint", ""),
                    progress_pct=data.get("progress_pct", 0),
                    started_at=data.get("started_at", ""),
                    otel_trace_id=data.get("otel_trace_id", ""),
                )
                changes.append(change)

            return ActivePhaseChangesResponse(changes=changes)
        except Exception as e:
            logger.error(f"Failed to get active phase changes: {e}")
            return ActivePhaseChangesResponse()

    # =========================================================================
    # Scheduler
    # =========================================================================

    async def SchedulerStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> SchedulerStatusResponse:
        """Get scheduler status (engine scheduler queue + backend router)."""
        import json as _json

        response = SchedulerStatusResponse(
            queue_depth=0,
            active_jobs=0,
            avg_latency_ms=0.0,
        )

        metrics: dict = {}
        sched = getattr(self._services, "scheduler_service", None)
        if sched:
            status = sched.get_status()
            response.queue_depth = int(status.get("queue_depth", 0) or 0)
            response.active_jobs = int(status.get("active_jobs", 0) or 0)
            totals = status.get("metrics") or {}
            response.avg_latency_ms = float(totals.get("avg_latency_ms", 0.0) or 0.0)
            metrics["engine_scheduler"] = status

        if self._services.backend_router:
            br_status = self._services.backend_router.get_status()
            metrics["backend_router"] = br_status
            if not sched:
                response.queue_depth = br_status.get("queue_depth", 0)
                response.active_jobs = br_status.get("active_jobs", 0)
                response.avg_latency_ms = br_status.get("avg_latency_ms", 0.0)

        if metrics:
            response.metrics_json = _json.dumps(metrics, default=str)

        return response

    async def Complete(
        self,
        request: CompleteRequest,
        context: aio.ServicerContext,
    ) -> CompleteResponse:
        """Synchronous completion request."""
        if not self._services.backend_router:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Backend router not initialized")
            return CompleteResponse()

        start_time = time.time()

        try:
            result = await self._services.backend_router.complete(
                prompt=request.prompt,
                agent_alias=request.agent_alias or "thinking",
                system_prompt=request.system_prompt,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens or 2048,
                technique=request.technique or None,
                task_type="scheduler_complete",
            )

            latency_ms = (time.time() - start_time) * 1000

            # Fail fast if backend returned an error
            if result.error:
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(result.error)
                return CompleteResponse(model=result.model, latency_ms=latency_ms)

            return CompleteResponse(
                text=result.content,
                tokens_used=result.output_tokens,
                latency_ms=latency_ms,
                model=result.model,
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return CompleteResponse()

    async def SubmitJob(
        self,
        request: SubmitJobRequest,
        context: aio.ServicerContext,
    ) -> SubmitJobResponse:
        """Submit an async job to the engine scheduler queue.

        Engine-First: the job queue lives in the engine (SchedulerService),
        never client-side. Poll GetJobResult with the returned job_id.
        """
        sched = getattr(self._services, "scheduler_service", None)
        if not sched:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(
                "#EN.00000021.NOSCHED: engine SchedulerService not initialized.\n"
                "  Try: /health fix engine"
            )
            return SubmitJobResponse()

        from ...backends import InferenceRequest
        from ...services.scheduler_service import JobPriority

        priority_map = {
            "critical": JobPriority.CRITICAL,
            "high": JobPriority.HIGH,
            "normal": JobPriority.NORMAL,
            "low": JobPriority.LOW,
            "batch": JobPriority.BATCH,
        }

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        inference_request = InferenceRequest(
            messages=messages,
            agent_alias=request.agent_alias or "thinking",
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens or 2048,
        )

        job_id = await sched.submit_async(
            inference_request,
            priority_map.get((request.priority or "normal").lower(), JobPriority.NORMAL),
        )
        return SubmitJobResponse(job_id=job_id, status="queued")

    async def GetJobResult(
        self,
        request: GetJobResultRequest,
        context: aio.ServicerContext,
    ) -> GetJobResultResponse:
        """Get the result of a submitted job from the engine scheduler."""
        sched = getattr(self._services, "scheduler_service", None)
        if not sched:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(
                "#EN.00000021.NOSCHED: engine SchedulerService not initialized.\n"
                "  Try: /health fix engine"
            )
            return GetJobResultResponse(job_id=request.job_id)

        record = sched.get_job_result(request.job_id)
        if record is None:
            return GetJobResultResponse(
                job_id=request.job_id,
                status="not_found",
                error="unknown job id (completed-job ring may have recycled it)",
            )

        return GetJobResultResponse(
            job_id=request.job_id,
            status=record.get("status", "unknown"),
            text=record.get("content", "") or "",
            tokens_used=int(record.get("output_tokens", 0) or 0),
            latency_ms=float(record.get("latency_ms", 0) or 0),
            error=record.get("error") or "",
        )

    async def XAIBudget(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> XAIBudgetResponse:
        """Get XAI API budget status.

        Returns daily and weekly request usage against configured limits
        from the engine SchedulerService's XAIBudget tracker.
        """
        from datetime import datetime, timezone, timedelta

        # Calculate reset time (next midnight UTC)
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        sched = getattr(self._services, "scheduler_service", None)
        if sched:
            budget = sched.get_xai_budget()
            return XAIBudgetResponse(
                daily_used=int(budget.get("daily_used", 0)),
                daily_limit=int(budget.get("daily_limit", 0)),
                weekly_used=int(budget.get("weekly_used", 0)),
                weekly_limit=int(budget.get("weekly_limit", 0)),
                reset_at=tomorrow.isoformat(),
            )

        # Scheduler not yet initialized: report configured limits, zero usage
        return XAIBudgetResponse(
            daily_used=0,
            daily_limit=50,
            weekly_used=0,
            weekly_limit=200,
            reset_at=tomorrow.isoformat(),
        )

    # =========================================================================
    # Workload Management (Yunikorn-Style)
    # =========================================================================

    async def BeginWorkload(
        self,
        request: BeginWorkloadRequest,
        context: aio.ServicerContext,
    ) -> BeginWorkloadResponse:
        """Begin a workload and allocate resources.

        Yunikorn-style workload management: the request declares what
        capabilities are needed and the orchestrator allocates endpoints,
        potentially evicting idle ones.
        """
        from ...workloads import WorkloadRequest, WorkloadType
        from ...services.scheduler_service import JobPriority
        from gaius.models.registry import TaskType

        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return BeginWorkloadResponse(
                success=False,
                workload_id=request.workload_id,
                error="OrchestratorService not initialized",
            )

        from gaius.engine.sentinel_claim import GURU_NOAPP, gpu_start_allowed

        if not gpu_start_allowed(request.workload_id):
            return BeginWorkloadResponse(
                success=False,
                workload_id=request.workload_id,
                error=(
                    f"{GURU_NOAPP} exclusive GPU start requires an admitted "
                    "YK Application (federation.zndx.org/gpu claim). "
                    "Leases in /tmp/zndx-gpu-leases are intra-node refuse only."
                ),
            )

        try:
            # Map proto workload type to Python enum
            workload_type_map = {
                ProtoWorkloadType.WORKLOAD_INIT: WorkloadType.INIT,
                ProtoWorkloadType.WORKLOAD_SWARM: WorkloadType.SWARM,
                ProtoWorkloadType.WORKLOAD_INFERENCE: WorkloadType.INFERENCE,
                ProtoWorkloadType.WORKLOAD_EMBEDDING: WorkloadType.EMBEDDING,
                ProtoWorkloadType.WORKLOAD_EVOLUTION: WorkloadType.EVOLUTION,
                ProtoWorkloadType.WORKLOAD_RENDERING: WorkloadType.RENDERING,
            }
            workload_type = workload_type_map.get(
                request.workload_type, WorkloadType.INFERENCE
            )

            # Map priority string to enum
            priority_map = {
                "critical": JobPriority.CRITICAL,
                "high": JobPriority.HIGH,
                "normal": JobPriority.NORMAL,
                "low": JobPriority.LOW,
            }
            priority = priority_map.get(
                request.priority.lower(), JobPriority.NORMAL
            )

            # Parse capabilities
            capabilities = []
            for cap_str in request.required_capabilities:
                try:
                    capabilities.append(TaskType(cap_str))
                except ValueError:
                    logger.warning(f"Unknown capability: {cap_str}")

            # Create workload request
            workload_req = WorkloadRequest(
                workload_id=request.workload_id,
                workload_type=workload_type,
                required_capabilities=capabilities,
                priority=priority,
                estimated_duration_s=request.estimated_duration_s or 300,
                estimated_memory_mb=request.estimated_memory_mb or 0,
                preemptible=request.preemptible,
            )

            # Begin workload
            result = await orchestrator.begin_workload(workload_req)

            # Build response
            response = BeginWorkloadResponse(
                success=result.success,
                workload_id=result.workload_id,
                error=result.error or "",
                wait_time_ms=result.wait_time_ms,
            )

            # Add allocated endpoints
            for task_type, alloc in result.allocated_endpoints.items():
                response.allocated_endpoints.append(
                    EndpointAllocationInfo(
                        endpoint_name=alloc.endpoint_name,
                        capability=task_type.value,
                        port=alloc.port,
                        healthy=alloc.healthy,
                        model_id=alloc.model_id,
                    )
                )

            # Add evicted and restore lists
            response.evicted_endpoints.extend(result.evicted_endpoints)
            response.restore_plan.extend(result.restore_plan)

            return response

        except Exception as e:
            logger.error(f"BeginWorkload failed: {e}")
            return BeginWorkloadResponse(
                success=False,
                workload_id=request.workload_id,
                error=str(e),
            )

    async def CompleteWorkload(
        self,
        request: CompleteWorkloadRequest,
        context: aio.ServicerContext,
    ) -> empty_pb2.Empty:
        """Mark a workload as complete and restore evicted endpoints."""
        orchestrator = self._services.orchestrator_service

        if orchestrator:
            try:
                await orchestrator.complete_workload(request.workload_id)
            except Exception as e:
                logger.error(f"CompleteWorkload failed: {e}")

        return empty_pb2.Empty()

    async def GetActiveWorkloads(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> GetActiveWorkloadsResponse:
        """Get information about all active workloads."""
        orchestrator = self._services.orchestrator_service

        response = GetActiveWorkloadsResponse()

        if orchestrator:
            try:
                workloads = orchestrator.get_active_workloads()
                for wid, info in workloads.items():
                    response.workloads.append(
                        ActiveWorkloadInfo(
                            workload_id=wid,
                            workload_type=info.get("type", ""),
                            priority=info.get("priority", ""),
                            capabilities=info.get("capabilities", []),
                            elapsed_s=info.get("elapsed_s", 0.0),
                            estimated_duration_s=info.get("estimated_duration_s", 0),
                            is_overdue=info.get("is_overdue", False),
                            endpoints=info.get("endpoints", []),
                        )
                    )
            except Exception as e:
                logger.error(f"GetActiveWorkloads failed: {e}")

        return response

    # =========================================================================
    # Embeddings (Engine-Managed)
    # =========================================================================

    async def EmbedTexts(
        self,
        request: EmbedTextsRequest,
        context: aio.ServicerContext,
    ) -> EmbedTextsResponse:
        """Generate embeddings for texts using vLLM embedding endpoint.

        Routes embedding requests through the vLLM endpoint running with
        --task embed, using the OpenAI-compatible embeddings API.
        """
        import time
        import httpx

        texts = list(request.texts)
        start_time = time.time()

        try:
            # Get embedding endpoint from vLLM controller
            orchestrator = self._services.orchestrator_service
            if not orchestrator:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("OrchestratorService not initialized")
                return EmbedTextsResponse()

            proc = orchestrator._vllm.get_process("embedding")

            if not proc:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("Embedding endpoint not running. Start it with: /gpu start embedding")
                return EmbedTextsResponse()

            if proc.status.value != "healthy":
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(f"Embedding endpoint not healthy: {proc.status.value}")
                return EmbedTextsResponse()

            # Call vLLM OpenAI-compatible embedding API
            base_url = f"http://localhost:{proc.port}/v1"
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base_url}/embeddings",
                    json={
                        "input": texts,
                        "model": proc.model,
                    },
                )
                response.raise_for_status()
                data = response.json()

            # Extract embeddings from OpenAI format
            embeddings = []
            for item in data.get("data", []):
                embeddings.append(item.get("embedding", []))

            latency_ms = int((time.time() - start_time) * 1000)

            grpc_response = EmbedTextsResponse(
                model_used=proc.model,
                latency_ms=latency_ms,
            )

            for embedding in embeddings:
                grpc_response.embeddings.append(
                    EmbeddingVector(values=embedding)
                )

            return grpc_response

        except httpx.HTTPStatusError as e:
            logger.error(f"EmbedTexts HTTP error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Embedding API error: {e.response.text}")
            return EmbedTextsResponse()
        except Exception as e:
            logger.error(f"EmbedTexts failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return EmbedTextsResponse()

    # =========================================================================
    # Semantic Search
    # =========================================================================

    async def SemanticSearch(
        self,
        request: SemanticSearchRequest,
        context: aio.ServicerContext,
    ) -> SemanticSearchResponse:
        """Perform semantic search using orchestrator-managed ColNomic.

        Uses VectorSearchService for GPU-coordinated MaxSim search over
        the KB Qdrant collection. GPU allocation is managed through the
        orchestrator's workload system for proper resource accounting.

        The VectorSearchService implements LRU-style caching:
        - First request loads ColNomic (~10-20s cold start)
        - Subsequent requests use cached model (fast)
        - After idle timeout (default 300s), model is unloaded

        Follows Yunikorn-style dynamic scheduling where ColNomic and
        reasoning endpoints can evict each other based on demand.
        """
        import time

        start_time = time.time()

        try:
            vector_search = self._services.vector_search_service
            if vector_search is None:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(
                    "VectorSearchService not available.\n"
                    "  Guru Meditation: #VS.00000001.SVCNOTINIT\n"
                    "  Fix: just restart-clean"
                )
                return SemanticSearchResponse()

            # Execute search (GPU allocation is handled by the service)
            results = await vector_search.search(
                query=request.query,
                top_k=request.limit if request.limit > 0 else 10,
                min_score=request.min_score,
                use_maxsim=request.use_maxsim if request.use_maxsim else True,
                content_type=request.content_type or None,
            )

            # Convert to proto results
            proto_results = [
                SearchResult(
                    path=r.path,
                    title=r.title,
                    score=r.score,
                    snippet=r.snippet[:500] if r.snippet else "",
                    chunk_id=r.chunk_id,
                    content_type=r.content_type,
                )
                for r in results
            ]

            latency_ms = int((time.time() - start_time) * 1000)

            return SemanticSearchResponse(
                results=proto_results,
                total=len(proto_results),
                collection=vector_search.collection_name,
                embedding_model="colnomic",
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
            context.set_details(
                "GPU allocation timeout for vector search.\n"
                "  Guru Meditation: #VS.00000003.TIMEOUT\n"
                "  Check: /gpu status"
            )
            return SemanticSearchResponse()

        except RuntimeError as e:
            # VectorSearchService raises RuntimeError with Guru codes for GPU failures
            logger.error(f"SemanticSearch failed: {e}")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(str(e))
            return SemanticSearchResponse()

        except Exception as e:
            logger.error(f"SemanticSearch failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return SemanticSearchResponse()

    async def SemanticSearchStream(
        self,
        request: SemanticSearchRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[SemanticSearchEvent]:
        """Streaming semantic search with progress events.

        Yields SemanticSearchEvent messages showing GPU allocation,
        model loading, and search progress. This is preferred for TUI
        clients that want to display progress during the 10-20s ColNomic
        cold start instead of blocking on a long timeout.

        Phases:
        1. REQUESTING_GPU - Requesting GPU via orchestrator workload system
        2. EVICTING_ENDPOINTS - Evicting vLLM endpoints to free GPU
        3. LOADING_MODEL - Loading ColNomic model onto GPU
        4. SEARCHING - Executing MaxSim search on Qdrant
        5. COMPLETE - Search complete with results
        6. ERROR - Error occurred
        """
        from ...services.vector_search_service import SearchPhase

        # Map internal SearchPhase to proto Phase
        PHASE_MAP = {
            SearchPhase.REQUESTING_GPU: SemanticSearchEvent.Phase.REQUESTING_GPU,
            SearchPhase.EVICTING_ENDPOINTS: SemanticSearchEvent.Phase.EVICTING_ENDPOINTS,
            SearchPhase.LOADING_MODEL: SemanticSearchEvent.Phase.LOADING_MODEL,
            SearchPhase.SEARCHING: SemanticSearchEvent.Phase.SEARCHING,
            SearchPhase.COMPLETE: SemanticSearchEvent.Phase.COMPLETE,
            SearchPhase.ERROR: SemanticSearchEvent.Phase.ERROR,
        }

        vector_search = self._services.vector_search_service
        if vector_search is None:
            yield SemanticSearchEvent(
                phase=SemanticSearchEvent.Phase.ERROR,
                message="VectorSearchService not available",
                progress_pct=0,
                timestamp_ms=int(time.time() * 1000),
                error="VectorSearchService not available.\n  Guru Meditation: #VS.00000001.SVCNOTINIT\n  Fix: just restart-clean",
                guru_code="#VS.00000001.SVCNOTINIT",
            )
            return

        try:
            async for event in vector_search.search_stream(
                query=request.query,
                top_k=request.limit if request.limit > 0 else 10,
                min_score=request.min_score,
                use_maxsim=request.use_maxsim if request.use_maxsim else True,
                content_type=request.content_type or None,
            ):
                proto_phase = PHASE_MAP.get(
                    event.phase, SemanticSearchEvent.Phase.PHASE_UNSPECIFIED
                )

                # Build base event
                proto_event = SemanticSearchEvent(
                    phase=proto_phase,
                    message=event.message,
                    progress_pct=event.progress_pct,
                    timestamp_ms=event.timestamp_ms,
                )

                # Add error info if present
                if event.error:
                    proto_event.error = event.error
                if event.guru_code:
                    proto_event.guru_code = event.guru_code

                # Add results on COMPLETE
                if event.phase == SearchPhase.COMPLETE and event.results:
                    proto_results = [
                        SearchResult(
                            path=r.path,
                            title=r.title,
                            score=r.score,
                            snippet=r.snippet[:500] if r.snippet else "",
                            chunk_id=r.chunk_id,
                            content_type=r.content_type,
                        )
                        for r in event.results
                    ]
                    proto_event.response.CopyFrom(
                        SemanticSearchResponse(
                            results=proto_results,
                            total=len(proto_results),
                            collection=vector_search.collection_name,
                            embedding_model="colnomic",
                        )
                    )

                yield proto_event

        except Exception as e:
            logger.error(f"SemanticSearchStream failed: {e}")
            yield SemanticSearchEvent(
                phase=SemanticSearchEvent.Phase.ERROR,
                message=str(e),
                progress_pct=0,
                timestamp_ms=int(time.time() * 1000),
                error=str(e),
                guru_code="#VS.00000099.UNKNOWN",
            )

    # =========================================================================
    # Swarm Streaming
    # =========================================================================

    async def SwarmStream(
        self,
        request: SwarmStreamRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[SwarmEvent]:
        """Streaming swarm analysis with real-time progress updates.

        Handles backend wait internally, streaming QUEUED/WAITING_FOR_BACKENDS
        status while endpoints initialize. This prevents client timeouts during
        the ~240s engine startup phase.

        Yields:
            SwarmEvent messages in order:
            1. QUEUED - Request received, waiting for backends
            2. WAITING_FOR_BACKENDS - Actively waiting (periodic updates)
            3. STARTED - Backends ready, swarm analysis beginning
            4. AGENT_STARTED/COMPLETED/FAILED - Per-agent progress
            5. COMPLETED - All agents done, includes final results
        """
        start_time = time.time()
        domain = request.domain or "general"
        context_str = request.context or ""
        roles = list(request.roles) if request.roles else None

        # Default swarm roles
        if roles is None:
            roles = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]

        total_agents = len(roles)

        def make_event(
            event_type: SwarmEvent.Type,
            agent: str = "",
            progress: float = 0.0,
            message: str = "",
            data: bytes = b"",
        ) -> SwarmEvent:
            return SwarmEvent(
                type=event_type,
                timestamp_ms=int(time.time() * 1000),
                agent=agent,
                progress=progress,
                message=message,
                data=data,
            )

        # Phase 1: QUEUED
        yield make_event(
            SwarmEvent.Type.QUEUED,
            message=f"Swarm request queued for domain: {domain}",
            progress=0.0,
        )

        # Phase 2: Wait for backends with streaming updates
        backends_ready = False
        wait_start = time.time()
        wait_interval = 2.0  # Update every 2 seconds

        while not backends_ready:
            # Check if any backends are available
            if self._services.backend_router:
                try:
                    status = self._services.backend_router.get_status()
                    vllm_status = status.get("vllm", {})
                    vllm_running = vllm_status.get("total_running", 0)
                    optillm_status = status.get("optillm", {})
                    optillm_healthy = optillm_status.get("healthy", False)
                    backends_ready = vllm_running > 0 or optillm_healthy
                except Exception:
                    pass

            if not backends_ready:
                elapsed = int(time.time() - wait_start)
                yield make_event(
                    SwarmEvent.Type.WAITING_FOR_BACKENDS,
                    message=f"Waiting for inference endpoints ({elapsed}s)...",
                    progress=0.05,  # Small progress to show activity
                )
                await asyncio.sleep(wait_interval)

                # Timeout after 5 minutes
                if elapsed > 300:
                    yield make_event(
                        SwarmEvent.Type.FAILED,
                        message="Timeout waiting for backends",
                        progress=0.0,
                    )
                    return

        # Phase 3: STARTED
        yield make_event(
            SwarmEvent.Type.STARTED,
            message=f"Swarm analysis starting with {total_agents} agents",
            progress=0.1,
        )

        # Phase 4: Run each agent
        results: dict[str, dict] = {}
        completed = 0
        failed = 0

        try:
            from ....agents.roles import AgentRole, get_role
        except ImportError:
            yield make_event(
                SwarmEvent.Type.FAILED,
                message="Agent roles not available",
            )
            return

        # Map role capabilities to endpoints
        ROLE_TO_ENDPOINT = {
            "Leader": "orchestrator",
            "Risk": "thinking",
            "Optimizer": "thinking",
            "Planner": "orchestrator",
            "Critic": "thinking",
            "Executor": "thinking",
            "Adversary": "thinking",
        }

        for i, role_name in enumerate(roles):
            base_progress = 0.1 + (0.8 * i / total_agents)

            # AGENT_STARTED
            yield make_event(
                SwarmEvent.Type.AGENT_STARTED,
                agent=role_name,
                message=f"Running {role_name}...",
                progress=base_progress,
            )

            try:
                role_enum = AgentRole(role_name)
                role_def = get_role(role_enum)
                prompt = role_def.get_prompt(domain, context_str)
                endpoint = ROLE_TO_ENDPOINT.get(role_name, "thinking")

                # Run the agent
                if self._services.backend_router:
                    result = await self._services.backend_router.complete(
                        prompt=prompt,
                        agent_alias=endpoint,
                        system_prompt=role_def.system_prompt or "",
                        temperature=role_def.temperature,
                        max_tokens=role_def.max_tokens,
                        source_context={
                            "agent_alias": f"swarm_{role_name}",
                            "task_type": "swarm_analysis",
                            "role_name": role_name,
                            "domain": domain,
                        },
                    )

                    agent_result = {
                        "status": "completed" if not result.error else "failed",
                        "content": result.content,
                        "model": result.model,
                        "endpoint": endpoint,
                        "latency_ms": result.latency_ms,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "error": result.error,
                    }
                else:
                    agent_result = {
                        "status": "failed",
                        "error": "Backend router not available",
                    }

                results[role_name] = agent_result

                if agent_result["status"] == "completed":
                    completed += 1
                    yield make_event(
                        SwarmEvent.Type.AGENT_COMPLETED,
                        agent=role_name,
                        message=f"{role_name} completed",
                        progress=base_progress + (0.8 / total_agents),
                        data=json.dumps(agent_result).encode(),
                    )
                else:
                    failed += 1
                    yield make_event(
                        SwarmEvent.Type.AGENT_FAILED,
                        agent=role_name,
                        message=f"{role_name} failed: {agent_result.get('error', 'unknown')}",
                        progress=base_progress + (0.8 / total_agents),
                    )

            except Exception as e:
                failed += 1
                results[role_name] = {"status": "failed", "error": str(e)}
                yield make_event(
                    SwarmEvent.Type.AGENT_FAILED,
                    agent=role_name,
                    message=f"{role_name} failed: {e}",
                    progress=base_progress + (0.8 / total_agents),
                )

        # Phase 5: CLT processing (if enabled)
        # Uses Yunikorn-style workload system for GPU allocation
        clt_data = {}
        workload_id = None
        if request.clt:
            try:
                from ...workloads import WorkloadRequest, WorkloadType
                from ...services.scheduler_service import JobPriority
                from gaius.models.registry import TaskType
                import uuid

                orchestrator = self._services.orchestrator_service
                if not orchestrator:
                    raise RuntimeError("Orchestrator service not available for CLT workload")

                # Request CLT capability via workload system
                workload_id = f"clt-swarm-{uuid.uuid4().hex[:8]}"
                workload_request = WorkloadRequest(
                    workload_id=workload_id,
                    workload_type=WorkloadType.SWARM,
                    required_capabilities=[TaskType.CLT_TRACING],
                    priority=JobPriority.NORMAL,
                    estimated_duration_s=60,  # CLT processing estimate
                    estimated_memory_mb=6000,  # CLT model ~6GB
                )

                # Begin workload - allocates GPU, starts CLT subprocess
                workload_result = await orchestrator.begin_workload(workload_request)
                if not workload_result.success:
                    raise RuntimeError(f"CLT workload allocation failed: {workload_result.error}")

                # Get CLT service from orchestrator (now has allocated GPU)
                clt = orchestrator.get_clt_service()
                if not clt:
                    raise RuntimeError("CLT service not available after workload allocation")

                clt.clear_states()

                # Extract CLT features from each completed agent response
                for role_name, result in results.items():
                    if result.get("status") == "completed" and result.get("content"):
                        try:
                            clt.extract_features(result["content"], role_name)
                        except Exception as e:
                            logger.warning(f"CLT extraction failed for {role_name}: {e}")

                # Update grid positions
                try:
                    from ....core.projection import get_grid_manager
                    projector = get_grid_manager()
                    clt.update_grid_positions(projector)
                except Exception:
                    clt.update_grid_positions(None)

                # Build CLT response
                clt_data = {
                    "positions": [
                        {"name": name, "x": x, "y": y, "color": color}
                        for name, x, y, color in clt.get_agent_positions()
                    ],
                    "traces": {
                        name: [{"x": x, "y": y} for x, y in positions]
                        for name, positions in clt.get_agent_traces().items()
                    },
                    "consensus_features": {
                        str(k): v for k, v in clt.compute_consensus().items()
                    },
                    "feature_overlap": {
                        f"{a1}↔{a2}": sim
                        for (a1, a2), sim in clt.compute_overlap().items()
                    },
                    "agent_features": {
                        role: [
                            {"idx": idx, "activation": act}
                            for idx, act in sorted(
                                state.sparse_features.items(),
                                key=lambda x: x[1],
                                reverse=True
                            )[:10]
                        ]
                        for role, state in clt._agent_states.items()
                    },
                }

                # Persist snapshot for temporal topology tracking
                try:
                    from ...services.topology_service import TopologyService
                    topology_service = self._services.topology_service
                    if topology_service:
                        # Compute consensus embedding from agent states
                        consensus_embedding = None
                        embeddings = [
                            s.embedding for s in clt._agent_states.values()
                            if s.embedding is not None
                        ]
                        if embeddings:
                            import numpy as np
                            consensus_embedding = np.mean(embeddings, axis=0)

                        await topology_service.save_snapshot(
                            domain=domain,
                            run_id=uuid.UUID(workload_id.split("-")[-1].ljust(32, "0")),
                            agent_states=clt._agent_states,
                            consensus_embedding=consensus_embedding,
                            query_text=domain,  # TODO: Get actual query
                        )
                        logger.info(f"Saved swarm topology snapshot for domain '{domain}'")
                except Exception as snapshot_err:
                    logger.warning(f"Failed to save topology snapshot: {snapshot_err}")
            except Exception as e:
                logger.warning(f"CLT processing failed: {e}")
            finally:
                # Complete workload to release GPU and restore baseline
                if workload_id and orchestrator:
                    try:
                        await orchestrator.complete_workload(workload_id)
                    except Exception as e:
                        logger.warning(f"Failed to complete CLT workload: {e}")

        # Phase 6: Save results and send COMPLETED
        total_duration_ms = int((time.time() - start_time) * 1000)

        # Save results to KB
        saved_path = ""
        try:
            from ....storage.kb_ops import save_swarm_results
            saved_path = save_swarm_results(results, domain)
        except Exception as e:
            logger.warning(f"Failed to save swarm results: {e}")

        # Send final COMPLETED event with all results
        final_data = {
            "results": results,
            "saved_path": saved_path,
            "total_agents": total_agents,
            "completed_agents": completed,
            "failed_agents": failed,
            "total_duration_ms": total_duration_ms,
        }

        # Include CLT data if available
        if clt_data:
            final_data["_clt"] = clt_data

        yield make_event(
            SwarmEvent.Type.COMPLETED,
            message=f"Swarm completed: {completed}/{total_agents} agents succeeded",
            progress=1.0,
            data=json.dumps(final_data).encode(),
        )

    # =========================================================================
    # Evolution
    # =========================================================================

    async def EvolutionStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> EvolutionStatusResponse:
        """Get evolution daemon status."""
        if self._services.get_evolution_status:
            try:
                status = await self._services.get_evolution_status()
                return EvolutionStatusResponse(
                    running=status.get("running", False),
                    cycles_completed=status.get("cycles_completed", 0),
                    total_improvement_pct=status.get("total_improvement_pct", 0.0),
                    current_agent=status.get("current_agent", ""),
                    next_agent=status.get("next_agent", ""),
                    mode=status.get("mode", "idle"),
                )
            except Exception as e:
                logger.warning(f"Failed to get evolution status: {e}")

        # Default response when evolution not available
        return EvolutionStatusResponse(
            running=False,
            mode="unavailable",
        )

    async def TriggerEvolution(
        self,
        request: TriggerEvolutionRequest,
        context: aio.ServicerContext,
    ) -> EvolutionCycleResponse:
        """Trigger an evolution cycle for an agent."""
        agent_id = request.agent_id

        if self._services.trigger_evolution:
            try:
                result = await self._services.trigger_evolution(agent_id)
                return EvolutionCycleResponse(
                    success=result.get("success", False),
                    improvement_pct=result.get("improvement_pct", 0.0),
                    duration_ms=result.get("duration_ms", 0),
                    agent_id=result.get("agent_id", agent_id),
                    version_id=result.get("version_id", ""),
                )
            except Exception as e:
                return EvolutionCycleResponse(
                    success=False,
                    agent_id=agent_id,
                )

        context.set_code(grpc.StatusCode.UNAVAILABLE)
        context.set_details("Evolution service not available")
        return EvolutionCycleResponse(success=False)

    async def StartEvolution(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> EvolutionStatusResponse:
        """Start the evolution daemon."""
        if self._services.start_evolution:
            try:
                status = await self._services.start_evolution()
                return EvolutionStatusResponse(
                    running=True,
                    mode="running",
                    next_agent=status.get("next_agent", ""),
                )
            except Exception as e:
                logger.warning(f"Failed to start evolution: {e}")

        context.set_code(grpc.StatusCode.UNAVAILABLE)
        context.set_details("Evolution service not available")
        return EvolutionStatusResponse(running=False)

    async def StopEvolution(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> EvolutionStatusResponse:
        """Stop the evolution daemon."""
        if self._services.stop_evolution:
            try:
                await self._services.stop_evolution()
                return EvolutionStatusResponse(
                    running=False,
                    mode="stopped",
                )
            except Exception as e:
                logger.warning(f"Failed to stop evolution: {e}")

        return EvolutionStatusResponse(running=False, mode="stopped")

    # =========================================================================
    # Cognition
    # =========================================================================

    async def CognitionStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> CognitionStatusResponse:
        """Get cognition daemon status."""
        # Try to get daemon status from service if available
        cognition = getattr(self._services, "cognition_service", None)

        if cognition:
            try:
                status = cognition.get_status()
                last_cycle_ms = 0
                if status.get("last_cycle_at"):
                    last_cycle_ms = int(status["last_cycle_at"].timestamp() * 1000)
                return CognitionStatusResponse(
                    running=status.get("running", False),
                    cycles_completed=status.get("cycles_completed", 0),
                    last_cycle_timestamp_ms=last_cycle_ms,
                    current_task=status.get("current_task") or "",
                )
            except Exception as e:
                logger.warning(f"Failed to get cognition status: {e}")

        # Fallback: check if we have thoughts (indicates cognition is working)
        return CognitionStatusResponse(running=False)

    async def GetRecentThoughts(
        self,
        request: GetRecentThoughtsRequest,
        context: aio.ServicerContext,
    ) -> GetRecentThoughtsResponse:
        """Get recent thoughts from the cognition agent."""
        from ....agents.cognition import get_cognition_agent

        limit = request.limit or 10
        response = GetRecentThoughtsResponse()

        try:
            agent = get_cognition_agent()
            thoughts = await agent.get_active_thoughts(limit=limit)

            for t in thoughts:
                timestamp_ms = 0
                if t.created_at:
                    timestamp_ms = int(t.created_at.timestamp() * 1000)

                thought = ThoughtMessage(
                    id=t.id or "",
                    thought_type=t.thought_type.value if hasattr(t.thought_type, "value") else str(t.thought_type),
                    title=t.title or "",
                    summary=t.summary or (t.content[:100] if t.content else ""),
                    salience=t.salience or 0.0,
                    generation=t.generation or 0,
                    timestamp_ms=timestamp_ms,
                    note_path=t.note_path or "",
                )
                response.thoughts.append(thought)

        except Exception as e:
            logger.debug(f"Failed to get recent thoughts: {e}")

        return response

    async def TriggerCognition(
        self,
        request: TriggerCognitionRequest,
        context: aio.ServicerContext,
    ) -> TriggerCognitionResponse:
        """Trigger a cognition cycle via Engine-native L3 logic.

        Uses cognition_service.trigger() which routes to cognition_logic.py,
        NOT the L5 agent (which would bypass gRPC and call inference directly).
        """
        max_thoughts = request.max_thoughts or 5
        trigger_reason = request.trigger_reason or "manual"

        logger.info(f"TriggerCognition gRPC called: max_thoughts={max_thoughts}, trigger={trigger_reason}")

        # Get cognition service from the Engine's services container
        cognition = getattr(self._services, "cognition_service", None)
        logger.info(f"Cognition service available: {cognition is not None}")
        if not cognition:
            return TriggerCognitionResponse(
                success=False,
                error="Cognition service not available.\n"
                      "Guru Meditation: #COG.00000018.NOSVC\n"
                      "Check: Engine startup logs",
            )

        try:
            # Call L3 cognition_logic via cognition_service.trigger()
            logger.info("Calling cognition.trigger(cognition_cycle)...")
            result = await cognition.trigger(
                task_type="cognition_cycle",
                payload={
                    "max_thoughts": max_thoughts,
                    "trigger": trigger_reason,
                },
            )
            logger.info(f"Cognition trigger result: success={result.get('success')}, thoughts={result.get('thoughts_generated')}, error={result.get('error')}")

            return TriggerCognitionResponse(
                success=result.get("success", False),
                thoughts_generated=result.get("thoughts_generated", 0),
                patterns_detected=result.get("patterns_detected", 0),
                connections_found=result.get("connections_found", 0),
                curiosities_generated=result.get("curiosities_generated", 0),
                duration_ms=result.get("duration_ms", 0),
                kb_path=result.get("kb_path") or "",
                tokens_out=result.get("tokens_out", 0),
                error=result.get("error"),
            )
        except Exception as e:
            logger.error(f"Cognition trigger failed: {e}")
            return TriggerCognitionResponse(
                success=False,
                error=str(e),
            )

    async def CognitionActivity(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> CognitionActivityResponse:
        """Get comprehensive cognition activity summary."""
        from ....agents.cognition import get_cognition_agent

        response = CognitionActivityResponse(
            cognition_running=False,
            cycles_completed=0,
        )

        # Get daemon status if available (may be None during startup)
        cognition = getattr(self._services, "cognition_service", None)
        if cognition:
            try:
                status = cognition.get_status()
                response.cognition_running = status.get("running", False)
                response.cycles_completed = status.get("cycles_completed", 0)
                if status.get("last_cycle_at"):
                    response.last_cycle_timestamp_ms = int(status["last_cycle_at"].timestamp() * 1000)
                response.current_task = status.get("current_task") or ""
            except Exception as e:
                logger.debug(f"Failed to get cognition status: {e}")

        # Get active thoughts count from agent
        try:
            agent = get_cognition_agent()
            thoughts = await agent.get_active_thoughts(limit=100)
            response.active_thoughts = len(thoughts)
        except Exception as e:
            logger.debug(f"Failed to get active thoughts: {e}")

        return response

    async def DiscoverSurface(
        self,
        request: DiscoverSurfaceRequest,
        context: aio.ServicerContext,
    ) -> DiscoverSurfaceResponse:
        from ...services.discover_landing import peek_landing, uses_landing_mv
        from ...services.discover_surface import (
            DiscoverError,
            load_discover,
            parse_query,
        )

        parsed = parse_query(
            request.query or "", list(request.feature_pins or [])
        )
        if uses_landing_mv(
            request.window or "36h",
            parsed,
            request.from_ts or "",
            request.to_ts or "",
        ):
            cached = peek_landing()
            if cached is not None:
                return self._discover_proto(cached)

        pool = _summary_db(self._services)
        try:
            snap = await asyncio.wait_for(
                load_discover(
                    pool,
                    window=request.window or "36h",
                    query=request.query or "",
                    breakdown=request.breakdown or "source",
                    limit=request.limit or 50,
                    feature_pins=list(request.feature_pins or []),
                    from_ts=request.from_ts or "",
                    to_ts=request.to_ts or "",
                ),
                timeout=2.5,
            )
        except TimeoutError:
            cached = peek_landing()
            if cached is not None:
                return self._discover_proto(cached)
            return DiscoverSurfaceResponse(
                error=(
                    "Discover surface timed out.\n"
                    "Guru Meditation: #DI.00000009.SLOWPOOL\n"
                    "  Try: /discover refresh"
                )
            )
        except DiscoverError as e:
            cached = peek_landing()
            if cached is not None:
                return self._discover_proto(cached)
            return DiscoverSurfaceResponse(error=str(e))
        except Exception as e:
            return DiscoverSurfaceResponse(
                error=(
                    f"Discover surface failed: {e}\n"
                    "Guru Meditation: #DI.00000006.SURFACE\n"
                    "  Try: /health fix postgres"
                ),
            )
        return self._discover_proto(snap)

    def _discover_proto(self, snap: object) -> DiscoverSurfaceResponse:
        return DiscoverSurfaceResponse(
            buckets=[
                ProtoDiscoverBucket(
                    t=b.t,
                    n=b.n,
                    breakdown_key=b.breakdown_key,
                    salience=b.salience,
                    watts=b.watts,
                    util=b.util,
                    salience_ma=b.salience_ma,
                    watts_ma=b.watts_ma,
                    util_ma=b.util_ma,
                )
                for b in snap.buckets
            ],
            docs=[
                ProtoDiscoverDoc(
                    id=d.id,
                    stream=d.stream,
                    source=d.source,
                    ts=d.ts,
                    title=d.title,
                    body=d.body,
                    source_id=d.source_id,
                    url=d.url,
                )
                for d in snap.docs
            ],
            facets=[
                ProtoDiscoverFacet(
                    key=f.key,
                    kind=f.kind,
                    count=f.count,
                    salience=f.salience,
                    label=f.label,
                )
                for f in snap.facets
            ],
            total=snap.total,
            window=snap.window,
            query=snap.query,
            scraped_at=snap.scraped_at,
            interval=snap.interval,
            last_salience_at=snap.last_salience_at,
            clock=snap.clock,
            next_episode=(
                ProtoDiscoverEpisode(
                    kind=snap.next_episode.kind,
                    at=snap.next_episode.at,
                    eta_s=snap.next_episode.eta_s,
                    label=snap.next_episode.label,
                )
                if snap.next_episode
                else None
            ),
            status=self._discover_status(),
        )

    def _discover_status(self) -> ProtoDiscoverStatus:
        from ...services.discover_landing import landing_strip

        extra = 0
        sched = getattr(self._services, "flow_scheduler_service", None)
        if sched is None:
            sched = getattr(self._services, "_flow_scheduler_service", None)
        if sched is not None:
            extra = len(getattr(sched, "_active_runs", {}) or {})
        s = landing_strip(extra_workflows=extra, services=self._services)
        return ProtoDiscoverStatus(
            updating=s.updating,
            workflows=s.workflows,
            waiting_at=s.waiting_at,
            watts=s.watts,
            articles=s.articles,
            projects=s.projects,
            thoughts=s.thoughts,
            watts_live=s.watts_live,
            terms_skos=s.terms_skos,
            terms_cites=s.terms_cites,
            agenda_min=s.agenda_min,
            agenda_max=s.agenda_max,
            agenda_std=s.agenda_std,
            salience_peak=s.salience_peak,
            cognition_tokens=s.cognition_tokens,
        )

    async def RefreshDiscoverLanding(
        self,
        request: RefreshDiscoverLandingRequest,
        context: aio.ServicerContext,
    ) -> RefreshDiscoverLandingResponse:
        from ...services.discover_landing import request_discover_landing_refresh
        from ...services.discover_surface import DiscoverError

        pool = _summary_db(self._services)
        try:
            accepted = await request_discover_landing_refresh(
                pool, reason=request.reason or ""
            )
        except DiscoverError as e:
            return RefreshDiscoverLandingResponse(error=str(e), accepted=False)
        except Exception as e:
            return RefreshDiscoverLandingResponse(
                accepted=False,
                error=(
                    f"Discover landing refresh failed: {e}\n"
                    "Guru Meditation: #DI.00000008.REFRESH\n"
                    "  Try: /health fix discover"
                ),
            )
        return RefreshDiscoverLandingResponse(
            accepted=True,
            started=accepted.started,
            refreshed_at=accepted.refreshed_at,
        )

    async def CognitionSurface(
        self,
        request: CognitionSurfaceRequest,
        context: aio.ServicerContext,
    ) -> CognitionSurfaceResponse:
        """Federation cognition dashboard snapshot (thoughts + cycles)."""
        cognition = getattr(self._services, "cognition_service", None)
        if not cognition:
            return CognitionSurfaceResponse(
                error=(
                    "Cognition service not available.\n"
                    "Guru Meditation: #COG.00000024.NOSVC\n"
                    "  Try: /health fix engine"
                ),
            )
        try:
            snap = await cognition.surface(
                window_days=request.window_days or 365,
                thought_limit=request.thought_limit or 80,
                stream=request.stream or "",
            )
        except ValueError as e:
            return CognitionSurfaceResponse(error=str(e))
        except Exception as e:
            return CognitionSurfaceResponse(
                error=(
                    f"Cognition surface failed: {e}\n"
                    "Guru Meditation: #COG.00000028.SURFACE\n"
                    "  Try: /health fix postgres"
                ),
            )

        def _thought(t: Any) -> ThoughtMessage:
            return ThoughtMessage(
                id=t.id,
                thought_type=t.thought_type,
                title=t.title,
                summary=t.summary,
                salience=t.salience,
                generation=t.generation,
                timestamp_ms=t.timestamp_ms,
                note_path=t.note_path,
            )

        return CognitionSurfaceResponse(
            running=snap.running,
            cycles_completed=snap.cycles_completed,
            cycles_in_window=snap.cycles_in_window,
            last_cycle_timestamp_ms=snap.last_cycle_timestamp_ms,
            current_task=snap.current_task,
            thoughts=snap.thoughts,
            streams=snap.streams,
            active_days=snap.active_days,
            thoughts_per_cycle=snap.thoughts_per_cycle,
            concentration_stream=snap.concentration_stream,
            concentration_pct=snap.concentration_pct,
            reserve_tokens=snap.reserve_tokens,
            project=snap.project,
            unit=snap.unit,
            recent=[_thought(t) for t in snap.recent],
            top=[_thought(t) for t in snap.top],
            days=[
                CognitionDayBucket(date=d.date, thoughts=d.thoughts, cycles=d.cycles)
                for d in snap.days
            ],
            hours=[
                CognitionHourCell(weekday=h.weekday, hour=h.hour, thoughts=h.thoughts)
                for h in snap.hours
            ],
            stream_counts=[
                CognitionStreamCount(id=s.id, thoughts=s.thoughts)
                for s in snap.stream_counts
            ],
        )

    async def CognitionWaterfall(
        self,
        request: CognitionWaterfallRequest,
        context: aio.ServicerContext,
    ) -> CognitionWaterfallResponse:
        from gaius.engine.services.cognition_waterfall import (
            fetch_cognition_metrics,
            fetch_gpu_metrics,
            recent_tape_energy,
            tick,
        )

        window = request.window_s or 60
        tape_n, tape_peak = 0, 0.0
        pool = _summary_db(self._services)
        if pool is not None:
            try:
                tape_n, tape_peak = await recent_tape_energy(pool)
            except Exception as e:
                logger.debug("waterfall tape energy skipped: %s", e)
        ctx: dict = {
            "tape_n": tape_n,
            "tape_peak": tape_peak,
            "clt_loaded": False,
            "sae_loaded": False,
        }
        try:
            from gaius.engine.services import clt_service as clt_mod

            svc = clt_mod._clt_service
            if svc is not None:
                ctx["clt_loaded"] = bool(svc.is_loaded)
                vecs = [
                    st.embedding
                    for st in getattr(svc, "_agent_states", {}).values()
                    if getattr(st, "embedding", None) is not None
                ]
                if vecs:
                    ctx["embeddings"] = vecs
        except Exception:
            pass
        try:
            warehouse_rows = await fetch_gpu_metrics(window)
        except Exception as e:
            return CognitionWaterfallResponse(error=str(e))
        # Cognition rides the same warehouse transport. A quiet cognition
        # surface must not blank the GPU strip, so its absence is logged and
        # the turn continues with an empty set.
        try:
            cognition_rows = await fetch_cognition_metrics(window)
        except Exception as e:
            logger.warning("waterfall cognition read failed: %s", e)
            cognition_rows = []
        try:
            state = tick(
                window,
                self._services,
                ctx=ctx,
                warehouse_rows=warehouse_rows,
                cognition_rows=cognition_rows,
            )
        except ValueError as e:
            return CognitionWaterfallResponse(error=str(e))
        flat: list[float] = [v for row in state.matrix for v in row]
        return CognitionWaterfallResponse(
            epoch_unix_ms=state.epoch_unix_ms,
            n_channels=len(state.channel_names),
            n_times=len(state.matrix[0]) if state.matrix else 0,
            channel_names=list(state.channel_names),
            matrix=flat,
            driver=state.driver,
            hn_tokens=state.hn_tokens,
            fmp_tokens=state.fmp_tokens,
        )

    async def SelfObservation(
        self,
        request: SelfObservationRequest,
        context: aio.ServicerContext,
    ) -> SelfObservationResponse:
        """Trigger self-observation - meta-cognition on recent thoughts.

        Uses L3 cognition_logic.process_self_observation() for Engine-native
        implementation that properly manages inference.
        """
        from ...services import cognition_logic

        cognition = getattr(self._services, "cognition_service", None)
        if not cognition:
            return SelfObservationResponse(
                success=False,
                error="Cognition service not available.\n"
                      "Guru Meditation: #COG.00000019.NOSVC\n"
                      "Check: Engine startup logs",
            )

        try:
            # Get database pool from cognition service
            db_pool = getattr(cognition, "_db_pool", None)
            if not db_pool:
                return SelfObservationResponse(
                    success=False,
                    error="Database pool not available for self-observation.\n"
                          "Guru Meditation: #COG.00000020.NODB",
                )

            # Call L3 implementation
            result = await cognition_logic.process_self_observation(
                db_pool=db_pool,
                payload={"max_observations": request.max_observations or 5},
            )

            return SelfObservationResponse(
                success=result.success,
                observations_generated=result.self_observations,
                duration_ms=result.duration_ms,
                error=result.error or "",
                observation_ids=result.thought_ids or [],
            )

        except Exception as e:
            logger.error(f"Self-observation failed: {e}")
            return SelfObservationResponse(
                success=False,
                error=f"Self-observation failed: {e}\n"
                      "Guru Meditation: #COG.00000021.SELFOBS",
            )

    async def EngineAudit(
        self,
        request: EngineAuditRequest,
        context: aio.ServicerContext,
    ) -> EngineAuditResponse:
        """Run engine health audit and record observations.

        Uses L3 cognition_logic.process_engine_audit() for Engine-native
        implementation.
        """
        from ...services import cognition_logic

        cognition = getattr(self._services, "cognition_service", None)
        if not cognition:
            return EngineAuditResponse(
                success=False,
                error="Cognition service not available.\n"
                      "Guru Meditation: #COG.00000022.NOSVC\n"
                      "Check: Engine startup logs",
            )

        try:
            # Get database pool from cognition service
            db_pool = getattr(cognition, "_db_pool", None)
            if not db_pool:
                return EngineAuditResponse(
                    success=False,
                    error="Database pool not available for engine audit.\n"
                          "Guru Meditation: #COG.00000023.NODB",
                )

            # Call L3 implementation
            result = await cognition_logic.process_engine_audit(
                db_pool=db_pool,
                payload={"include_metrics": request.include_metrics},
            )

            return EngineAuditResponse(
                success=result.success,
                observations_recorded=result.observations_recorded,
                anomalies_found=result.anomalies_found,
                duration_ms=result.duration_ms,
                error=result.error or "",
                anomaly_details=result.anomaly_details or [],
            )

        except Exception as e:
            logger.error(f"Engine audit failed: {e}")
            return EngineAuditResponse(
                success=False,
                error=f"Engine audit failed: {e}\n"
                      "Guru Meditation: #COG.00000024.AUDIT",
            )

    async def SubscribeCognition(
        self,
        request,
        context: aio.ServicerContext,
    ):
        """Stream cognition events to TUI/MCP clients.

        Replaces polling - clients receive real-time updates as thoughts
        are generated, cycles start/complete, etc.
        """
        from ...generated import gaius_service_pb2 as pb

        cognition = getattr(self._services, "cognition_service", None)
        if not cognition:
            # No service - return empty stream
            return

        buffer_size = request.buffer_size or 100

        try:
            async for event in cognition.subscribe_cognition(buffer_size=buffer_size):
                # Map event type string to proto enum
                event_type = getattr(
                    pb.CognitionEvent.Type,
                    event.get("type", "THOUGHT"),
                    pb.CognitionEvent.Type.THOUGHT,
                )

                yield pb.CognitionEvent(
                    type=event_type,
                    timestamp_ms=event.get("timestamp_ms", 0),
                    thought_id=event.get("thought_id", ""),
                    thought_type=event.get("thought_type", ""),
                    title=event.get("title", ""),
                    summary=event.get("summary", ""),
                    salience=event.get("salience", 0.0),
                    generation=event.get("generation", 0),
                    cycle_id=event.get("cycle_id", ""),
                    thoughts_in_cycle=event.get("thoughts_in_cycle", 0),
                    error=event.get("error", ""),
                )
        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as e:
            logger.error(f"Cognition stream error: {e}")

    async def SubscribeEvolution(
        self,
        request,
        context: aio.ServicerContext,
    ):
        """Stream evolution events to TUI/MCP clients.

        Replaces polling - clients receive real-time updates as agents
        are evaluated, promoted, etc.
        """
        from ...generated import gaius_service_pb2 as pb

        cognition = getattr(self._services, "cognition_service", None)
        if not cognition:
            return

        buffer_size = request.buffer_size or 100
        agent_filter = request.agent_filter or ""

        try:
            async for event in cognition.subscribe_evolution(
                buffer_size=buffer_size,
                agent_filter=agent_filter,
            ):
                # Map event type string to proto enum
                event_type = getattr(
                    pb.EvolutionEvent.Type,
                    event.get("type", "CYCLE_START"),
                    pb.EvolutionEvent.Type.CYCLE_START,
                )

                yield pb.EvolutionEvent(
                    type=event_type,
                    timestamp_ms=event.get("timestamp_ms", 0),
                    agent_id=event.get("agent_id", ""),
                    version_id=event.get("version_id", ""),
                    score=event.get("score", 0.0),
                    improvement_pct=event.get("improvement_pct", 0.0),
                    details=event.get("details", ""),
                    cycle_number=event.get("cycle_number", 0),
                    merge_id=event.get("merge_id", ""),
                    error=event.get("error", ""),
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Evolution stream error: {e}")

    async def SubscribeActivity(
        self,
        request,
        context: aio.ServicerContext,
    ):
        """Stream all activity events to TUI/MCP clients.

        Unified feed of cognition, evolution, system, and KB events.
        """
        from ...generated import gaius_service_pb2 as pb

        cognition = getattr(self._services, "cognition_service", None)
        if not cognition:
            return

        buffer_size = request.buffer_size or 100
        domains = list(request.domains) if request.domains else None

        try:
            async for event in cognition.subscribe_activity(
                buffer_size=buffer_size,
                domains=domains,
            ):
                yield pb.ActivityEvent(
                    event_type=event.get("event_type", ""),
                    timestamp_ms=event.get("timestamp_ms", 0),
                    source=event.get("source", ""),
                    domain=event.get("domain", ""),
                    title=event.get("title", ""),
                    summary=event.get("summary", ""),
                    data=event.get("data", "{}").encode("utf-8"),
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Activity stream error: {e}")

    # =========================================================================
    # State Service (Thin Client Architecture)
    # =========================================================================

    async def GetCurrentState(
        self,
        request: GetStateRequest,
        context: aio.ServicerContext,
    ) -> GridState:
        """Get current grid state for instant TUI startup.

        Loads state from Postgres current_state table, which is denormalized
        for fast reads. If since_generation > 0 and matches current generation,
        returns empty state (client is up to date).
        """
        kb_root = request.kb_root or "build/dev"
        since_generation = request.since_generation
        include_geometry = request.include_geometry

        try:
            from ....storage.grid_state import load_current_state_fast

            cached = await load_current_state_fast(kb_root)

            if cached is None:
                # No cached state - return empty
                return GridState(
                    snapshot_id="",
                    generation=0,
                    n_documents=0,
                )

            current_gen = cached.generation

            # If client is up to date, return minimal response
            if since_generation > 0 and since_generation >= current_gen:
                updated_ms = int(cached.updated_at.timestamp() * 1000) if cached.updated_at else 0
                return GridState(
                    snapshot_id=str(cached.snapshot_id) if cached.snapshot_id else "",
                    generation=current_gen,
                    updated_at_ms=updated_ms,
                    n_documents=0,  # Indicates "no new data"
                )

            # Build full response
            updated_ms = int(cached.updated_at.timestamp() * 1000) if cached.updated_at else 0
            response = GridState(
                snapshot_id=str(cached.snapshot_id) if cached.snapshot_id else "",
                generation=int(current_gen),
                updated_at_ms=int(updated_ms),
                n_documents=int(cached.n_documents),
                projection_method=cached.projection_method or "",
                embedding_model=cached.embedding_model or "",
            )

            # Add document positions (documents is list of dicts with x, y, path, title)
            for doc in cached.documents:
                response.documents.append(GridPosition(
                    id=doc.get("path", ""),
                    x=int(doc.get("x", 0)),
                    y=int(doc.get("y", 0)),
                    cluster=int(doc.get("cluster_id", -1)),
                ))

            # Add cluster centers (clusters is list of (x, y) tuples)
            for cluster in cached.clusters:
                if isinstance(cluster, (list, tuple)) and len(cluster) >= 2:
                    response.clusters.append(GridPosition(
                        x=int(float(cluster[0])),
                        y=int(float(cluster[1])),
                    ))

            # Add allocations (flattened 19x19)
            allocations = cached.allocations
            if allocations:
                # Flatten if nested, ensuring int type
                if allocations and isinstance(allocations[0], list):
                    flat = [int(v) for row in allocations for v in row]
                    response.allocations.extend(flat)
                else:
                    # allocations is flat list of ints when not nested
                    response.allocations.extend([int(v) for v in allocations])  # type: ignore[arg-type] - allocations contains ints at runtime

            # Add TDA features directly from cached dataclass
            tda_features = ProtoTDAFeatures(
                entropy=float(cached.entropy),
                h0_count=int(cached.h0_count),
                h1_count=int(cached.h1_count),
                h2_count=int(cached.h2_count),
            )
            for cycle in cached.h1_cycles:
                tda_features.h1_cycles.append(ProtoBoundingBox(
                    x_min=int(cycle.get("x_min", 0)),
                    y_min=int(cycle.get("y_min", 0)),
                    x_max=int(cycle.get("x_max", 0)),
                    y_max=int(cycle.get("y_max", 0)),
                    persistence=float(cycle.get("persistence", 0.0)),
                ))
            for void in cached.h2_voids:
                tda_features.h2_voids.append(ProtoBoundingBox(
                    x_min=int(void.get("x_min", 0)),
                    y_min=int(void.get("y_min", 0)),
                    x_max=int(void.get("x_max", 0)),
                    y_max=int(void.get("y_max", 0)),
                    persistence=float(void.get("persistence", 0.0)),
                ))
            tda_features.risk_scores.extend([int(r) for r in cached.risk_scores])
            response.tda.CopyFrom(tda_features)

            # Add geometry if requested
            if include_geometry and (cached.curvature_map or cached.gradient_field):
                geo_features = GeometryFeatures()
                # curvature_map is already 361-element flat list
                if cached.curvature_map:
                    geo_features.curvature_map.extend(cached.curvature_map)
                # divergence_map is also 361-element flat list
                if cached.divergence_map:
                    geo_features.divergence_map.extend(cached.divergence_map)
                # gradient_field is list of [x, y, gx, gy] lists
                for gv in cached.gradient_field:
                    if isinstance(gv, (list, tuple)) and len(gv) >= 4:
                        # gv is [x, y, gx, gy] - x/y are grid positions (ints), gx/gy are gradient components (floats)
                        geo_features.gradient_field.append(GradientVector(
                            x=int(float(gv[0])),  # Convert float->int safely
                            y=int(float(gv[1])),
                            gx=float(gv[2]),
                            gy=float(gv[3]),
                        ))
                    elif isinstance(gv, dict):
                        # Legacy format support
                        geo_features.gradient_field.append(GradientVector(
                            x=gv.get("x", 0),
                            y=gv.get("y", 0),
                            gx=gv.get("gx", 0.0),
                            gy=gv.get("gy", 0.0),
                        ))
                response.geometry.CopyFrom(geo_features)

            return response

        except Exception as e:
            logger.error(f"GetCurrentState failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return GridState()

    async def SubscribeState(
        self,
        request: SubscribeStateRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[StateUpdate]:
        """Subscribe to state updates (generation-based).

        Only pushes updates when generation increments (meaningful changes).
        Clients receive FULL_REFRESH on connect, then GENERATION_CHANGED
        when state updates.
        """
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or context.peer() or "unknown"

        logger.debug(f"StateSubscription started: {client_id} -> {kb_root}")

        # Track current generation
        current_gen = 0

        try:
            from ....storage.grid_state import load_current_state_fast

            # Initial state
            cached = await load_current_state_fast(kb_root)
            if cached:
                current_gen = cached.generation

                # Send FULL_REFRESH on connect
                yield StateUpdate(
                    type=StateUpdate.Type.FULL_REFRESH,
                    generation=current_gen,
                    timestamp_ms=int(time.time() * 1000),
                    message="Connected, initial state loaded",
                )

            # Poll for changes (generation-based)
            poll_interval = 2.0  # Check every 2 seconds

            while not context.cancelled():
                await asyncio.sleep(poll_interval)

                # Check for new generation
                cached = await load_current_state_fast(kb_root)
                if cached:
                    new_gen = cached.generation
                    if new_gen > current_gen:
                        current_gen = new_gen
                        yield StateUpdate(
                            type=StateUpdate.Type.GENERATION_CHANGED,
                            generation=new_gen,
                            timestamp_ms=int(time.time() * 1000),
                            message=f"State updated to generation {new_gen}",
                        )

        except asyncio.CancelledError:
            logger.debug(f"StateSubscription cancelled: {client_id}")
        except Exception as e:
            logger.error(f"StateSubscription error: {e}")
            yield StateUpdate(
                type=StateUpdate.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message=str(e),
            )

    async def GetPreferences(
        self,
        request: GetPreferencesRequest,
        context: aio.ServicerContext,
    ) -> UIPreferences:
        """Get UI preferences for a client."""
        client_id = request.client_id

        try:
            from ....storage.grid_state import load_ui_preferences

            prefs = await load_ui_preferences(client_id)

            if prefs is None:
                # Return defaults
                return UIPreferences(
                    client_id=client_id,
                    cursor_x=9,
                    cursor_y=9,
                    view_mode="go",
                    overlay_mode="none",
                    iso_mode="curvature",
                    center_panel_mode="graph",
                    left_panel_visible=True,
                    right_panel_visible=True,
                )

            # prefs is a StorageUIPreferences dataclass, access attributes directly
            return UIPreferences(
                client_id=client_id,
                cursor_x=prefs.cursor_x,
                cursor_y=prefs.cursor_y,
                view_mode=prefs.view_mode,
                overlay_mode=prefs.overlay_mode,
                iso_mode=prefs.iso_mode,
                center_panel_mode=prefs.center_panel_mode,
                left_panel_visible=prefs.left_panel_visible,
                right_panel_visible=prefs.right_panel_visible,
                domain=prefs.domain or "",
                preferences_json=json.dumps(prefs.preferences_json).encode(),
            )

        except Exception as e:
            logger.error(f"GetPreferences failed: {e}")
            return UIPreferences(client_id=client_id)

    async def SavePreferences(
        self,
        request: SavePreferencesRequest,
        context: aio.ServicerContext,
    ) -> empty_pb2.Empty:
        """Save UI preferences for a client."""
        prefs = request.preferences

        try:
            from ....storage.grid_state import save_ui_preferences, UIPreferences as StorageUIPreferences

            # Convert proto UIPreferences to storage UIPreferences
            storage_prefs = StorageUIPreferences(
                client_id=prefs.client_id,
                cursor_x=prefs.cursor_x,
                cursor_y=prefs.cursor_y,
                view_mode=prefs.view_mode,
                overlay_mode=prefs.overlay_mode,
                iso_mode=prefs.iso_mode,
                center_panel_mode=prefs.center_panel_mode,
                left_panel_visible=prefs.left_panel_visible,
                right_panel_visible=prefs.right_panel_visible,
                domain=prefs.domain if prefs.domain else None,
                preferences_json=json.loads(prefs.preferences_json) if prefs.preferences_json else {},
            )
            await save_ui_preferences(storage_prefs)

        except Exception as e:
            logger.error(f"SavePreferences failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

        return empty_pb2.Empty()

    async def PruneSnapshots(
        self,
        request: PruneSnapshotsRequest,
        context: aio.ServicerContext,
    ) -> PruneSnapshotsResponse:
        """Prune old grid snapshots."""
        kb_root = request.kb_root or "build/dev"
        keep_count = request.keep_count
        older_than_days = request.older_than_days
        dry_run = request.dry_run

        try:
            from ....storage.grid_state import prune_snapshots

            deleted_count, deleted_ids = await prune_snapshots(
                kb_root=kb_root,
                keep_count=keep_count if keep_count > 0 else None,
                older_than_days=older_than_days if older_than_days > 0 else None,
                dry_run=dry_run,
            )

            return PruneSnapshotsResponse(
                deleted_count=deleted_count,
                remaining_count=0,  # Not tracked by prune_snapshots
                dry_run=dry_run,
            )

        except Exception as e:
            logger.error(f"PruneSnapshots failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return PruneSnapshotsResponse(dry_run=dry_run)

    # =========================================================================
    # Grid (Embedding Projection)
    # =========================================================================

    async def ProjectEmbeddings(
        self,
        request: ProjectEmbeddingsRequest,
        context: aio.ServicerContext,
    ) -> ProjectEmbeddingsResponse:
        """Project embeddings to a 19x19 grid."""
        # TODO: Implement via grid service
        return ProjectEmbeddingsResponse(
            num_clusters=0,
            grid_size=request.grid_size or 19,
        )

    async def ProjectQuery(
        self,
        request: ProjectQueryRequest,
        context: aio.ServicerContext,
    ) -> ProjectQueryResponse:
        """Project a query embedding to grid position."""
        # TODO: Implement via grid service
        return ProjectQueryResponse(x=9, y=9)

    # =========================================================================
    # TDA (Topological Data Analysis)
    # =========================================================================

    async def ComputeTDA(
        self,
        request: ComputeTDARequest,
        context: aio.ServicerContext,
    ) -> TDAResponse:
        """Compute topological features of embeddings."""
        # TODO: Implement via TDA service
        return TDAResponse(betti_numbers=[0, 0, 0])

    # =========================================================================
    # Explain (Grid Position Interpretation)
    # =========================================================================

    async def Explain(
        self,
        request: ExplainRequest,
        context: aio.ServicerContext,
    ) -> ExplainResponse:
        """Explain a grid position using differential geometry and LLM.

        All heavy computation (TDA, geometry, minigrid) happens on the Engine.
        No fallbacks - Engine must be functional.

        Args:
            request: ExplainRequest with position and options

        Returns:
            ExplainResponse with geometry context and LLM interpretation
        """
        import numpy as np
        start_time = time.time()
        kb_root = request.kb_root or "build/dev"
        cx, cy = request.x, request.y
        max_tokens = request.max_tokens or 800

        # Convert to Go notation
        col = chr(ord("A") + cx + (1 if cx >= 8 else 0))  # Skip 'I'
        position = f"{col}{19 - cy}"

        logger.info(f"Explain: position={position} ({cx},{cy}) kb_root={kb_root}")

        try:
            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager
            from ....core.geometry import GeometryComputer
            from ....core.minigrids import get_embed_view, get_iso_view
            from ....inference.llm import ExplanationContext
            from ....storage.grid_state import load_full_grid_data_for_minigrids

            # Get grid manager to check cache first
            grid_manager = get_grid_manager(kb_root=kb_root)

            # Check if cache is already populated
            grid_data = None
            if grid_manager._cached_data is not None and grid_manager._cached_data.n_documents > 0:
                grid_data = grid_manager._cached_data
                logger.info(f"Using cached grid data: {grid_data.n_documents} documents")
            else:
                # Try loading from Postgres (fast) before triggering slow UMAP
                logger.info("Grid cache empty, trying Postgres...")
                pg_grid_data = await load_full_grid_data_for_minigrids(kb_root)
                if pg_grid_data is not None and pg_grid_data.n_documents > 0:
                    grid_manager.set_cached_data(pg_grid_data)
                    grid_data = pg_grid_data
                    logger.info(f"Loaded {grid_data.n_documents} documents from Postgres")
                else:
                    # Last resort: compute fresh (slow UMAP projection)
                    logger.info("No Postgres cache, computing fresh projection...")
                    grid_data = grid_manager.get_grid_data()

            if grid_data is None or grid_data.n_documents == 0:
                return ExplainResponse(
                    success=False,
                    error="No documents indexed. Run /init first.",
                    position=position,
                    x=cx, y=cy,
                )

            # Get document at position
            document_title = ""
            document_path = ""
            point_idx = grid_data.grid_to_embedding.get((cx, cy))
            if point_idx is not None and point_idx < len(grid_data.points):
                point = grid_data.points[point_idx]
                document_title = point.title
                document_path = point.path

            # Get nearby documents
            nearby_documents = []
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < 19 and 0 <= ny < 19:
                        neighbor_idx = grid_data.grid_to_embedding.get((nx, ny))
                        if neighbor_idx is not None and neighbor_idx < len(grid_data.points):
                            nearby_documents.append(grid_data.points[neighbor_idx].title)

            # Compute geometry features (Ricci curvatures, gradients)
            curvature = 0.0
            gradient_x, gradient_y = 0.0, 0.0
            curvatures_list = None

            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
                gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))
                grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                geom_features = await gc.compute_features(grid_data.raw_embeddings, grid_coords)

                if geom_features is not None:
                    curvatures_list = [float(k) for k in geom_features.curvatures]
                    # Build curvature map
                    curvature_map = {}
                    for i, (px, py) in enumerate(grid_coords):
                        if i < len(curvatures_list):
                            curvature_map[(int(px), int(py))] = curvatures_list[i]
                    curvature = curvature_map.get((cx, cy), 0.0)

                    # Build gradient field
                    gradient_field = getattr(geom_features, 'gradient_field', None)
                    if gradient_field is not None:
                        for i, (px, py) in enumerate(grid_coords):
                            if i < len(gradient_field):
                                if (int(px), int(py)) == (cx, cy):
                                    gradient_x, gradient_y = gradient_field[i]
                                    break

            # Get TDA features
            tda_entropy = 0.0
            h0_count, h1_count, h2_count = 0, 0, 0
            risk_score = 0.0

            tda_manager = get_tda_manager()
            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 3:
                grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                tda_features = tda_manager.compute_features(
                    grid_data.raw_embeddings, grid_coords
                )
                if tda_features:
                    tda_entropy = tda_features.entropy
                    # Use pre-computed counts from persistence intervals, not bounding box lists
                    h0_count = tda_features.h0_count
                    h1_count = tda_features.h1_count
                    h2_count = tda_features.h2_count
                    # risk_scores is a list indexed by point index, not grid coordinates
                    if hasattr(tda_features, 'risk_scores') and tda_features.risk_scores:
                        point_idx = grid_data.grid_to_embedding.get((cx, cy))
                        if point_idx is not None and point_idx < len(tda_features.risk_scores):
                            risk_score = tda_features.risk_scores[point_idx]

            # Compute mini-grid data
            embed_grid_flat = []
            iso_grid_flat = []

            embed_data = get_embed_view(grid_data, cx, cy)
            if embed_data and embed_data.grid:
                embed_grid_flat = [v for row in embed_data.grid for v in row]

            iso_data = get_iso_view(
                grid_data, curvatures_list, cx, cy,
                iso_features=grid_data.iso_features
            )
            if iso_data and iso_data.grid:
                iso_grid_flat = [v for row in iso_data.grid for v in row]

            # Build explanation context
            ctx = ExplanationContext(
                cursor_x=cx,
                cursor_y=cy,
                document_title=document_title,
                document_path=document_path,
                curvature=curvature,
                gradient_x=gradient_x,
                gradient_y=gradient_y,
                divergence=None,
                tda_entropy=tda_entropy,
                h0_count=h0_count,
                h1_count=h1_count,
                h2_count=h2_count,
                risk_score=risk_score,
                grid_coverage=len(grid_data.points) / 361,
                total_documents=len(grid_data.points),
                nearby_documents=nearby_documents[:5],
                embed_grid=embed_data.grid if embed_data else None,
                iso_grid=iso_data.grid if iso_data else None,
            )

            # Generate LLM explanation via Engine's BackendRouter
            # FAIL-FAST: no fallbacks, no empty content
            if not self._services.backend_router:
                return ExplainResponse(
                    success=False,
                    error=(
                        "Backend router not available.\n"
                        "Guru Meditation: #EXP.00000001.NOROUTER\n"
                        "Check: /health endpoints"
                    ),
                    position=position,
                    x=cx, y=cy,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            try:
                from ....inference.llm import _build_explanation_prompt
                prompt = _build_explanation_prompt(ctx)

                result = await self._services.backend_router.complete(
                    prompt=prompt,
                    agent_alias="thinking",
                    temperature=0.7,
                    max_tokens=max_tokens,
                    task_type="grid_explain",
                )

                if result.error:
                    raise RuntimeError(result.error)

                explanation = result.content
                model_name = result.model or "unknown"

            except Exception as llm_error:
                # Fail-fast: LLM failure is an error, not a fallback condition
                logger.error(f"LLM explanation failed: {llm_error}")
                return ExplainResponse(
                    success=False,
                    error=(
                        f"LLM explanation failed: {llm_error}\n"
                        "Guru Meditation: #EXP.00000002.LLMFAIL\n"
                        "Check: /health endpoints\n"
                        "Or: just restart-clean"
                    ),
                    position=position,
                    x=cx, y=cy,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # Fail-fast: Empty explanation is an error
            if not explanation or not explanation.strip():
                logger.error("LLM returned empty explanation")
                return ExplainResponse(
                    success=False,
                    error=(
                        "LLM returned empty explanation.\n"
                        "Guru Meditation: #EXP.00000003.EMPTYRESP\n"
                        "Check: /health endpoints\n"
                        "Inference endpoint may be overloaded or unhealthy."
                    ),
                    position=position,
                    x=cx, y=cy,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # Strip thinking tags if present
            if '<think>' in explanation and '</think>' in explanation:
                explanation = explanation.split('</think>')[-1].strip()

            # Save to KB if requested
            saved_path = ""
            if request.save_to_kb:
                from ....core.kb_capture import ExplainCapture
                from pathlib import Path

                capture = ExplainCapture(
                    position=position,
                    x=cx,
                    y=cy,
                    document_title=document_title,
                    document_path=document_path,
                    nearby_documents=nearby_documents[:5],
                    curvature=curvature,
                    gradient=(gradient_x, gradient_y),
                    risk_score=risk_score,
                    h0_count=h0_count,
                    h1_count=h1_count,
                    h2_count=h2_count,
                    tda_entropy=tda_entropy,
                    embed_grid=embed_data.grid if embed_data else None,
                    iso_grid=iso_data.grid if iso_data else None,
                    grid_coverage=len(grid_data.points) / 361,
                    total_documents=len(grid_data.points),
                    explanation=explanation,
                    model=model_name,
                    elapsed_ms=int((time.time() - start_time) * 1000),
                )
                try:
                    saved_path = str(capture.save_to_kb(Path(kb_root) / "scratch"))
                except Exception as e:
                    logger.warning(f"Failed to save explanation: {e}")

            duration_ms = int((time.time() - start_time) * 1000)

            # Convert to native Python types for protobuf (numpy types not supported)
            return ExplainResponse(
                success=True,
                position=position,
                x=cx,
                y=cy,
                document_title=document_title,
                document_path=document_path,
                curvature=float(curvature),
                gradient_x=float(gradient_x),
                gradient_y=float(gradient_y),
                divergence=0.0,
                tda_entropy=float(tda_entropy),
                h0_count=int(h0_count),
                h1_count=int(h1_count),
                h2_count=int(h2_count),
                risk_score=float(risk_score),
                grid_coverage=float(len(grid_data.points) / 361),
                total_documents=int(len(grid_data.points)),
                nearby_documents=nearby_documents[:5],
                embed_grid=[float(v) for v in embed_grid_flat],
                iso_grid=[float(v) for v in iso_grid_flat],
                explanation=explanation,
                model=model_name,
                duration_ms=duration_ms,
                saved_path=saved_path,
            )

        except Exception as e:
            logger.error(f"Explain failed: {e}", exc_info=True)
            return ExplainResponse(
                success=False,
                error=str(e),
                position=position,
                x=cx, y=cy,
                duration_ms=int((time.time() - start_time) * 1000),
            )

    # =========================================================================
    # Dataset Generation
    # =========================================================================

    async def SubmitDatasetJob(
        self,
        request: DatasetGenerationRequest,
        context: aio.ServicerContext,
    ) -> DatasetJobStatus:
        """Submit a dataset generation job.

        Performs fail-fast checks before queueing. Errors include
        actionable /health fix suggestions.
        """
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetJobStatus(status="failed", error=error_msg)

        try:
            from ...services.dataset_service import DatasetJobConfig

            config = DatasetJobConfig(
                flow_name=request.flow_name or "TestFlow",
                steps=list(request.steps) if request.steps else ["start", "process", "end"],
                mode=request.mode or "som",
                dataset_id=request.dataset_id or "nifi-som-v1",
                variants_per_action=request.variants_per_action or 5,
                min_quality_score=request.min_quality_score or 0.6,
                enable_calibration=request.enable_calibration,  # Default False
                calibration_sample_rate=request.calibration_sample_rate or 0.1,
                export_calibration=request.export_calibration,
                storage_backend=request.storage_backend or "minio",
            )

            job = await dataset_service.submit_job(config)
            return self._job_to_status(job)

        except Exception as e:
            # Fail-fast: no fallbacks - include error message with hints
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(e))
            return DatasetJobStatus(status="failed", error=str(e))

    async def GetDatasetJobStatus(
        self,
        request: GetDatasetJobRequest,
        context: aio.ServicerContext,
    ) -> DatasetJobStatus:
        """Get status of a dataset generation job."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetJobStatus()

        job = await dataset_service.get_job_status(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Job not found: {request.job_id}")
            return DatasetJobStatus()

        return self._job_to_status(job)

    async def CancelDatasetJob(
        self,
        request: CancelDatasetJobRequest,
        context: aio.ServicerContext,
    ) -> DatasetJobStatus:
        """Cancel a dataset generation job."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetJobStatus()

        job = await dataset_service.cancel_job(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Job not found: {request.job_id}")
            return DatasetJobStatus()

        return self._job_to_status(job)

    async def DatasetProgressStream(
        self,
        request: GetDatasetJobRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[DatasetProgressEvent]:
        """Stream dataset generation progress."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            return

        try:
            async for event in dataset_service.subscribe_progress(request.job_id):
                yield DatasetProgressEvent(
                    type=event.type.value,
                    timestamp_ms=event.timestamp_ms,
                    job_id=event.job_id,
                    progress=event.progress,
                    message=event.message,
                    phase=event.phase,
                    example_id=event.example_id,
                    data=event.data,
                )
        except asyncio.CancelledError:
            logger.debug(f"Dataset progress stream cancelled for {request.job_id}")

    async def GetDatasetLineage(
        self,
        request: DatasetLineageRequest,
        context: aio.ServicerContext,
    ) -> DatasetLineageResponse:
        """Get lineage information for a dataset."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetLineageResponse()

        lineage = await dataset_service.get_lineage(request.dataset_id)

        return DatasetLineageResponse(
            dataset_id=lineage["dataset_id"],
            total_examples=lineage["total_examples"],
            nodes=[
                LineageNode(
                    id=n["id"],
                    type=n["type"],
                    namespace=n["namespace"],
                    name=n["name"],
                    properties=n.get("properties", b"{}"),
                )
                for n in lineage.get("nodes", [])
            ],
            edges=[
                LineageEdge(
                    type=e["type"],
                    from_id=e["from_id"],
                    to_id=e["to_id"],
                )
                for e in lineage.get("edges", [])
            ],
        )

    def _job_to_status(self, job) -> DatasetJobStatus:
        """Convert DatasetJob to proto DatasetJobStatus."""
        return DatasetJobStatus(
            job_id=job.id,
            status=job.status.value,
            total_examples=job.examples_total,
            completed_examples=job.examples_completed,
            accepted_examples=job.examples_accepted,
            rejected_examples=job.examples_rejected,
            progress=job.progress,
            current_phase=job.current_phase.value,
            error=job.error or "",
        )

    # =========================================================================
    # Streaming
    # =========================================================================

    async def HealthStream(
        self,
        request: HealthStreamRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[HealthMetrics]:
        """Stream health metrics at regular intervals.

        Args:
            request: Contains interval_ms for update frequency

        Yields:
            HealthMetrics messages at the specified interval
        """
        interval_ms = request.interval_ms or 1000
        interval_sec = interval_ms / 1000.0

        logger.debug(f"Starting health stream with interval {interval_ms}ms")

        try:
            while not context.cancelled():
                metrics = await self._collect_health_metrics()
                yield metrics
                await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            logger.debug("Health stream cancelled")
        except Exception as e:
            logger.error(f"Health stream error: {e}")

    async def EventStream(
        self,
        request: EventStreamRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[Event]:
        """Stream events to subscribers.

        Args:
            request: Contains optional event_types filter

        Yields:
            Event messages as they occur
        """
        event_types = set(request.event_types) if request.event_types else None

        # Create queue for this subscriber
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._event_subscribers.append(queue)

        logger.debug(f"Event stream started (filter: {event_types})")

        try:
            while not context.cancelled():
                try:
                    # Wait for events with timeout to check cancellation
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)

                    # Apply filter if specified
                    if event_types is None or event.event_type in event_types:
                        yield event
                except asyncio.TimeoutError:
                    # Check if still active
                    continue
        except asyncio.CancelledError:
            logger.debug("Event stream cancelled")
        finally:
            # Remove subscriber
            if queue in self._event_subscribers:
                self._event_subscribers.remove(queue)

    async def broadcast_event(self, event: Event) -> None:
        """Broadcast an event to all subscribers.

        Args:
            event: Event to broadcast
        """
        for queue in self._event_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping event")

    async def _collect_health_metrics(self) -> HealthMetrics:
        """Collect current health metrics."""
        timestamp_ms = int(time.time() * 1000)

        metrics = HealthMetrics(
            timestamp_ms=timestamp_ms,
            queue_depth=0,
            evolution_running=False,
        )

        # Try to get metrics from callback
        if self._services.get_health_metrics:
            try:
                raw_metrics = await self._services.get_health_metrics()

                # GPU metrics
                for gpu in raw_metrics.get("gpus", []):
                    gpu_metric = GPUMetrics(
                        gpu_id=gpu.get("id", 0),
                        utilization=gpu.get("utilization", 0.0),
                        memory_used_gb=gpu.get("memory_used_gb", 0.0),
                        memory_total_gb=gpu.get("memory_total_gb", 0.0),
                        temperature_c=gpu.get("temperature_c", 0),
                        power_watts=gpu.get("power_watts", 0),
                    )
                    metrics.gpus.append(gpu_metric)

                # Endpoint health
                for ep in raw_metrics.get("endpoints", []):
                    endpoint = EndpointHealth(
                        name=ep.get("name", ""),
                        model=ep.get("model", ""),
                        healthy=ep.get("healthy", False),
                        requests_served=ep.get("requests_served", 0),
                        avg_latency_ms=ep.get("avg_latency_ms", 0.0),
                    )
                    metrics.endpoints.append(endpoint)

                metrics.queue_depth = raw_metrics.get("queue_depth", 0)
                metrics.evolution_running = raw_metrics.get("evolution_running", False)

            except Exception as e:
                logger.debug(f"Failed to collect health metrics: {e}")

        return metrics

    # ─────────────────────────────────────────────────────────────────────────
    # Init Stream (Bidirectional)
    # ─────────────────────────────────────────────────────────────────────────

    async def InitStream(
        self,
        request_iterator: AsyncIterator[InitCommand],
        context: aio.ServicerContext,
    ) -> AsyncIterator[InitEvent]:
        """Bidirectional initialization stream.

        Allows TUI/MCP clients to connect immediately during engine startup
        and receive real-time progress updates while also sending control
        commands (pause, cancel, health checks).

        This method is available as soon as gRPC starts, BEFORE backends
        and orchestrator are initialized, enabling progress monitoring
        during the ~240s vLLM preload phase.

        Args:
            request_iterator: Stream of InitCommand messages from client
            context: gRPC context

        Yields:
            InitEvent messages (progress, status, command responses)
        """
        # Get init controller from services
        init_controller = self._services.init_controller

        if not init_controller:
            # If init_controller is not set, return an error event and close
            yield InitEvent(
                type=InitEvent.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message="InitController not available",
            )
            return

        # Subscribe to init events
        event_queue = init_controller.subscribe()
        client_id = context.peer() or "unknown"

        logger.debug(f"InitStream started for client: {client_id}")

        # Create task to process incoming commands
        async def handle_commands():
            """Process incoming commands from client."""
            try:
                async for cmd in request_iterator:
                    logger.debug(f"InitStream command: {cmd.type} from {client_id}")
                    response = await init_controller.handle_command(cmd)
                    # Put response in queue so it gets yielded
                    try:
                        event_queue.put_nowait(response)
                    except asyncio.QueueFull:
                        logger.warning("Init event queue full, dropping command response")
            except asyncio.CancelledError:
                logger.debug(f"InitStream command handler cancelled for {client_id}")
            except Exception as e:
                logger.debug(f"InitStream command handler error: {e}")

        # Start command handler task
        command_task = asyncio.create_task(handle_commands())

        try:
            # Send initial status
            yield InitEvent(
                type=InitEvent.Type.PROGRESS,
                timestamp_ms=int(time.time() * 1000),
                phase=init_controller.state.phase.name.lower(),
                progress=init_controller.state.overall_progress,
                message=f"Connected. Phase: {init_controller.state.phase.name}",
            )

            # Stream events to client
            while not context.cancelled():
                try:
                    # Wait for events with timeout to check cancellation
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield event

                    # If we received READY event, client can decide to close
                    if event.type == InitEvent.Type.READY:
                        logger.debug(f"InitStream: READY event sent to {client_id}")

                except asyncio.TimeoutError:
                    # No events, check if still connected
                    continue

        except asyncio.CancelledError:
            logger.debug(f"InitStream cancelled for {client_id}")
        except Exception as e:
            logger.error(f"InitStream error for {client_id}: {e}")
            yield InitEvent(
                type=InitEvent.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message=str(e),
            )
        finally:
            # Cleanup
            command_task.cancel()
            try:
                await command_task
            except asyncio.CancelledError:
                pass
            init_controller.unsubscribe(event_queue)
            logger.debug(f"InitStream closed for {client_id}")

    # =========================================================================
    # Command Service (Unified Entry Point)
    # =========================================================================

    async def ExecuteCommand(
        self, request: ExecuteCommandRequest, context: grpc.aio.ServicerContext
    ) -> ExecuteCommandResponse:
        """Execute a command and return the result.

        Routes commands to appropriate handlers. For heavy compute commands,
        runs them through the Engine. For state-only commands, accesses Postgres.
        """
        start_time = time.time()
        command = request.command
        args = request.args
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"

        logger.info(f"ExecuteCommand: {command} args={args} from {client_id}")

        try:
            result = {}
            message = ""
            generation = 0

            # Route to appropriate handler
            if command == "reindex":
                # Delegate to Reindex RPC
                reindex_req = ReindexRequest(
                    kb_root=kb_root,
                    client_id=client_id,
                    force="force" in args.lower() if args else False,
                )
                reindex_resp = await self.Reindex(reindex_req, context)
                result = {
                    "documents_indexed": reindex_resp.documents_indexed,
                    "documents_skipped": reindex_resp.documents_skipped,
                    "duration_ms": reindex_resp.duration_ms,
                }
                message = reindex_resp.message
                generation = reindex_resp.generation

            elif command == "state":
                # Get current state
                from ....storage.grid_state import load_current_state_fast, get_current_generation
                state = await load_current_state_fast(kb_root)
                generation = await get_current_generation(kb_root)
                if state:
                    result = {
                        "snapshot_id": state.snapshot_id,
                        "n_documents": state.n_documents,
                        "h0_count": state.h0_count,
                        "h1_count": state.h1_count,
                        "entropy": state.entropy,
                    }
                    message = f"State loaded (gen {generation})"
                else:
                    message = "No state available"

            elif command == "generation":
                # Get current generation
                from ....storage.grid_state import get_current_generation
                generation = await get_current_generation(kb_root)
                result = {"generation": generation}
                message = f"Generation: {generation}"

            elif command == "prefs":
                # Get/save preferences
                from ....storage.grid_state import load_ui_preferences, save_ui_preferences, UIPreferences
                if "save" in args.lower() if args else False:
                    # Parse context for preferences
                    ctx = dict(request.context)
                    prefs = UIPreferences(
                        client_id=client_id,
                        cursor_x=int(ctx.get("cursor_x", 9)),
                        cursor_y=int(ctx.get("cursor_y", 9)),
                        view_mode=ctx.get("view_mode", "go"),
                        overlay_mode=ctx.get("overlay_mode", "none"),
                    )
                    await save_ui_preferences(prefs)
                    result = {"action": "saved"}
                    message = "Preferences saved"
                else:
                    prefs = await load_ui_preferences(client_id)
                    if prefs:
                        result = {
                            "cursor_x": prefs.cursor_x,
                            "cursor_y": prefs.cursor_y,
                            "view_mode": prefs.view_mode,
                            "overlay_mode": prefs.overlay_mode,
                        }
                        message = "Preferences loaded"
                    else:
                        message = "No preferences found"

            else:
                # Unknown command
                return ExecuteCommandResponse(
                    success=False,
                    command=command,
                    message=f"Unknown command: {command}",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            duration_ms = int((time.time() - start_time) * 1000)
            return ExecuteCommandResponse(
                success=True,
                command=command,
                message=message,
                result_json=json.dumps(result).encode("utf-8"),
                generation=generation,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"ExecuteCommand failed: {e}")
            return ExecuteCommandResponse(
                success=False,
                command=command,
                message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def Reindex(
        self, request: ReindexRequest, context: grpc.aio.ServicerContext
    ) -> ReindexResponse:
        """Reindex KB documents to Qdrant and compute grid projection.

        GPU-coordinated: Embedding is delegated to VectorSearchService
        which handles GPU allocation/eviction via the orchestrator.
        Projection, TDA, and geometry are CPU-only operations.
        """
        start_time = time.time()
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"

        logger.info(f"Reindex: kb_root={kb_root} force={request.force} from {client_id}")

        try:
            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import save_grid_state, get_current_generation
            import numpy as np

            # 1. Index KB via VectorSearchService (GPU-coordinated)
            vector_search = self._services.vector_search_service
            if vector_search is None:
                return ReindexResponse(
                    success=False,
                    message=(
                        "VectorSearchService not available.\n"
                        "  Guru Meditation: #VS.00000001.SVCNOTINIT\n"
                        "  Fix: just restart-clean"
                    ),
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            await vector_search.index_kb(kb_root=kb_root)

            # 2. Project to grid (CPU-only: reads from Qdrant + UMAP)
            grid_manager = get_grid_manager(kb_root=kb_root)
            tda_manager = get_tda_manager()
            grid_manager.invalidate_cache()

            grid_data = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: grid_manager.get_grid_data(force_refresh=True)
            )

            if not grid_data or grid_data.n_documents == 0:
                return ReindexResponse(
                    success=False,
                    message="Reindex failed: no documents found",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 3. Compute TDA features from raw embeddings
            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            raw_embeddings = grid_data.raw_embeddings
            if raw_embeddings is not None and len(raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(raw_embeddings))
                ])
                tda_features = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )

                # 4. Compute geometry features (curvature, gradients, divergence)
                try:
                    k_neighbors = min(15, len(raw_embeddings) - 1)
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geometry_features = await gc.compute_features(
                            raw_embeddings, grid_coords
                        )
                        logger.info(f"Computed geometry features for {len(raw_embeddings)} points")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    geometry_features = None

            # 5. Save to Postgres (updates current_state table)
            embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
            snapshot_id = await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=grid_data.method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            generation = await get_current_generation(kb_root)

            duration_ms = int((time.time() - start_time) * 1000)
            return ReindexResponse(
                success=True,
                message=f"Indexed {grid_data.n_documents} documents",
                documents_indexed=grid_data.n_documents,
                documents_skipped=0,
                generation=generation,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"Reindex failed: {e}")
            return ReindexResponse(
                success=False,
                message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def ReindexStream(
        self, request: ReindexRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[ReindexProgress]:
        """Streaming reindex with progress updates.

        GPU-coordinated: Embedding is delegated to VectorSearchService
        which handles GPU allocation/eviction via the orchestrator.
        Projection, TDA, and geometry are CPU-only operations.
        """
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"
        force = request.force

        logger.info(f"ReindexStream: kb_root={kb_root} from {client_id}")

        try:
            yield ReindexProgress(
                phase=ReindexProgress.Phase.STARTED,
                progress=0.0,
                message="Starting reindex...",
            )

            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import save_grid_state, get_current_generation
            from ...services.vector_search_service import SearchPhase
            import numpy as np

            # EMBEDDING — delegate to VectorSearchService for GPU coordination
            vector_search = self._services.vector_search_service
            if vector_search is None:
                yield ReindexProgress(
                    phase=ReindexProgress.Phase.ERROR,
                    progress=0.0,
                    message=(
                        "VectorSearchService not available.\n"
                        "  Guru Meditation: #VS.00000001.SVCNOTINIT\n"
                        "  Fix: just restart-clean"
                    ),
                )
                return

            yield ReindexProgress(
                phase=ReindexProgress.Phase.EMBEDDING,
                progress=0.1,
                message="Indexing KB via GPU-coordinated VectorSearchService...",
            )

            async for event in vector_search.index_kb_stream(kb_root=kb_root):
                if event.phase == SearchPhase.REQUESTING_GPU:
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.EMBEDDING,
                        progress=0.12,
                        message=event.message,
                    )
                elif event.phase == SearchPhase.EVICTING_ENDPOINTS:
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.EMBEDDING,
                        progress=0.15,
                        message=event.message,
                    )
                elif event.phase == SearchPhase.LOADING_MODEL:
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.EMBEDDING,
                        progress=0.2,
                        message=event.message,
                    )
                elif event.phase == SearchPhase.INDEXING:
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.EMBEDDING,
                        progress=0.3,
                        message=event.message,
                    )
                elif event.phase == SearchPhase.ERROR:
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.ERROR,
                        progress=0.0,
                        message=event.message,
                    )
                    return
                elif event.phase == SearchPhase.COMPLETE:
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.EMBEDDING,
                        progress=0.4,
                        message=event.message,
                    )

            # PROJECTING — CPU-only: retrieve embeddings from Qdrant + UMAP
            yield ReindexProgress(
                phase=ReindexProgress.Phase.PROJECTING,
                progress=0.45,
                message="Projecting embeddings to 19x19 grid (UMAP)...",
            )

            grid_manager = get_grid_manager(kb_root=kb_root)
            tda_manager = get_tda_manager()
            loop = asyncio.get_event_loop()

            grid_manager.invalidate_cache()
            projection_task = loop.run_in_executor(
                None,
                lambda: grid_manager.get_grid_data(force_refresh=True)
            )
            heartbeat_count = 0
            while True:
                done, _ = await asyncio.wait(
                    {projection_task}, timeout=15.0
                )
                if done:
                    break
                heartbeat_count += 1
                elapsed_min = heartbeat_count * 15 / 60
                yield ReindexProgress(
                    phase=ReindexProgress.Phase.PROJECTING,
                    progress=0.45 + min(0.09, heartbeat_count * 0.005),
                    message=f"UMAP projection running ({elapsed_min:.1f}m elapsed)...",
                )

            grid_data = projection_task.result()

            if not grid_data or grid_data.n_documents == 0:
                yield ReindexProgress(
                    phase=ReindexProgress.Phase.ERROR,
                    progress=0.0,
                    message="No documents found after projection",
                )
                return

            yield ReindexProgress(
                phase=ReindexProgress.Phase.PROJECTING,
                progress=0.55,
                message=f"Projected {grid_data.n_documents} documents to grid",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

            # TDA
            yield ReindexProgress(
                phase=ReindexProgress.Phase.TDA,
                progress=0.6,
                message="Computing TDA features...",
            )

            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            raw_embeddings = grid_data.raw_embeddings
            if raw_embeddings is not None and len(raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(raw_embeddings))
                ])
                tda_task = loop.run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )
                tda_heartbeat = 0
                while True:
                    done, _ = await asyncio.wait(
                        {tda_task}, timeout=15.0
                    )
                    if done:
                        break
                    tda_heartbeat += 1
                    elapsed_min = tda_heartbeat * 15 / 60
                    yield ReindexProgress(
                        phase=ReindexProgress.Phase.TDA,
                        progress=0.6 + min(0.15, tda_heartbeat * 0.01),
                        message=f"TDA computation running ({elapsed_min:.1f}m elapsed)...",
                    )
                tda_features = tda_task.result()

                # Compute geometry features
                try:
                    k_neighbors = min(15, len(raw_embeddings) - 1)
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geom_task = loop.run_in_executor(
                            None, lambda: asyncio.run(gc.compute_features(raw_embeddings, grid_coords))
                        )
                        geom_heartbeat = 0
                        while True:
                            done, _ = await asyncio.wait(
                                {geom_task}, timeout=15.0
                            )
                            if done:
                                break
                            geom_heartbeat += 1
                            elapsed_min = geom_heartbeat * 15 / 60
                            yield ReindexProgress(
                                phase=ReindexProgress.Phase.TDA,
                                progress=0.75 + min(0.1, geom_heartbeat * 0.005),
                                message=f"Geometry computation running ({elapsed_min:.1f}m elapsed)...",
                            )
                        geometry_features = geom_task.result()
                        logger.info(f"Computed geometry features for {len(raw_embeddings)} points")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    geometry_features = None

            # Saving
            yield ReindexProgress(
                phase=ReindexProgress.Phase.SAVING,
                progress=0.9,
                message="Saving state...",
            )

            embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
            await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=grid_data.method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            generation = await get_current_generation(kb_root)

            # Complete
            yield ReindexProgress(
                phase=ReindexProgress.Phase.COMPLETE,
                progress=1.0,
                message=f"Indexed {grid_data.n_documents} documents (gen {generation})",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

        except Exception as e:
            logger.exception(f"ReindexStream failed: {e}")
            yield ReindexProgress(
                phase=ReindexProgress.Phase.ERROR,
                progress=0.0,
                message=str(e),
            )

    # =========================================================================
    # Init (Full Initialization Pipeline)
    # =========================================================================

    async def Init(
        self, request: InitRequest, context: grpc.aio.ServicerContext
    ) -> InitResponse:
        """Full initialization pipeline: index KB, project to grid, compute TDA.

        GPU-coordinated: Embedding is delegated to VectorSearchService
        which handles GPU allocation/eviction via the orchestrator.
        Projection, TDA, and geometry are CPU-only operations.

        Pipeline:
        1. Check Qdrant for existing data (skip embedding if present)
        2. Compute ColNomic embeddings via VectorSearchService (GPU-coordinated)
        3. Project to 19x19 grid via UMAP (CPU)
        4. Compute TDA features (H0/H1/H2) (CPU)
        5. Save to Postgres (grid_snapshots + current_state)
        """
        start_time = time.time()
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"
        force = request.force
        embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
        projection_method: Literal["umap", "pca"] = "umap"
        if request.projection_method in ("umap", "pca"):
            projection_method = request.projection_method  # type: ignore[assignment] - runtime check guarantees valid Literal value

        logger.info(f"Init: kb_root={kb_root} force={force} from {client_id}")

        try:
            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import (
                save_grid_state,
                get_current_generation,
                check_state_exists,
            )
            import numpy as np

            # Check if state already exists (skip if not forcing)
            if not force:
                state_exists = await check_state_exists(
                    kb_root, embedding_model, projection_method
                )
                if state_exists:
                    generation = await get_current_generation(kb_root)
                    return InitResponse(
                        success=True,
                        message="State already exists (use force=true to rebuild)",
                        generation=generation,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )

            # 1. Check Qdrant for existing data
            qdrant_has_data = False
            try:
                from qdrant_client import QdrantClient
                qdrant_port = int(os.getenv("QDRANT_PORT", "6339"))
                qc = QdrantClient(host="localhost", port=qdrant_port)
                collection_name = "gaius_kb_colnomic"
                info = qc.get_collection(collection_name)
                qdrant_has_data = info.points_count > 0
                logger.info(f"Qdrant has {info.points_count} points in {collection_name}")
            except Exception as e:
                logger.info(f"Qdrant check failed (will index): {e}")

            # 2. Embed via VectorSearchService if needed
            need_embedding = force or not qdrant_has_data
            if need_embedding:
                vector_search = self._services.vector_search_service
                if vector_search is None:
                    return InitResponse(
                        success=False,
                        message=(
                            "VectorSearchService not available.\n"
                            "  Guru Meditation: #VS.00000001.SVCNOTINIT\n"
                            "  Fix: just restart-clean"
                        ),
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                await vector_search.index_kb(kb_root=kb_root)

            # 3. Project to grid (CPU-only: reads from Qdrant + UMAP)
            grid_manager = get_grid_manager(method=projection_method, kb_root=kb_root)
            tda_manager = get_tda_manager()
            grid_manager.invalidate_cache()

            grid_data = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: grid_manager.get_grid_data(force_refresh=True)
            )

            if not grid_data or grid_data.n_documents == 0:
                return InitResponse(
                    success=False,
                    message="No documents found in KB",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 4. Compute TDA features from raw embeddings
            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            raw_embeddings = grid_data.raw_embeddings
            if raw_embeddings is not None and len(raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(raw_embeddings))
                ])
                tda_features = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )

                # 5. Compute geometry features (curvature, gradients, divergence)
                try:
                    k_neighbors = min(15, len(raw_embeddings) - 1)
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geometry_features = await gc.compute_features(
                            raw_embeddings, grid_coords
                        )
                        logger.info(f"Computed geometry features for {len(raw_embeddings)} points")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    geometry_features = None

            # 6. Save to Postgres
            snapshot_id = await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=projection_method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            generation = await get_current_generation(kb_root)

            duration_ms = int((time.time() - start_time) * 1000)
            return InitResponse(
                success=True,
                message=f"Initialized {grid_data.n_documents} documents",
                documents_indexed=grid_data.n_documents,
                h0_count=tda_features.h0_count,
                h1_count=tda_features.h1_count,
                h2_count=tda_features.h2_count,
                entropy=tda_features.entropy,
                generation=generation,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"Init failed: {e}")
            return InitResponse(
                success=False,
                message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def InitProgressStream(
        self, request: InitRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[InitProgress]:
        """Streaming init with detailed progress updates.

        Yields progress events for each phase of the init pipeline,
        allowing TUI/CLI to show real-time progress during long operations.

        GPU-coordinated: Embedding is delegated to VectorSearchService
        which handles GPU allocation/eviction via the orchestrator.
        Projection, TDA, and geometry are CPU-only operations.
        """
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"
        force = request.force
        embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
        projection_method: Literal["umap", "pca"] = "umap"
        if request.projection_method in ("umap", "pca"):
            projection_method = request.projection_method  # type: ignore[assignment] - runtime check guarantees valid Literal value

        logger.info(f"InitProgressStream: kb_root={kb_root} from {client_id}")

        try:
            # STARTED
            yield InitProgress(
                phase=InitProgress.Phase.STARTED,
                progress=0.0,
                message="Starting initialization...",
            )

            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import (
                save_grid_state,
                get_current_generation,
                check_state_exists,
            )
            from ...services.vector_search_service import SearchPhase
            import numpy as np

            # Check if state already exists (skip if not forcing)
            if not force:
                state_exists = await check_state_exists(
                    kb_root, embedding_model, projection_method
                )
                if state_exists:
                    generation = await get_current_generation(kb_root)
                    yield InitProgress(
                        phase=InitProgress.Phase.COMPLETE,
                        progress=1.0,
                        message=f"State already exists (gen {generation})",
                    )
                    return

            # SCANNING — check Qdrant for existing embeddings
            yield InitProgress(
                phase=InitProgress.Phase.SCANNING,
                progress=0.05,
                message="Checking Qdrant for existing embeddings...",
            )

            qdrant_has_data = False
            try:
                from qdrant_client import QdrantClient
                qdrant_port = int(os.getenv("QDRANT_PORT", "6339"))
                qc = QdrantClient(host="localhost", port=qdrant_port)
                collection_name = "gaius_kb_colnomic"
                info = qc.get_collection(collection_name)
                qdrant_has_data = info.points_count > 0
                if qdrant_has_data:
                    logger.info(f"Qdrant has {info.points_count} points in {collection_name}")
            except Exception as e:
                logger.info(f"Qdrant check failed (will index): {e}")

            # EMBEDDING — delegate to VectorSearchService for GPU coordination
            need_embedding = force or not qdrant_has_data
            if need_embedding:
                vector_search = self._services.vector_search_service
                if vector_search is None:
                    yield InitProgress(
                        phase=InitProgress.Phase.ERROR,
                        progress=0.0,
                        message=(
                            "VectorSearchService not available.\n"
                            "  Guru Meditation: #VS.00000001.SVCNOTINIT\n"
                            "  Fix: just restart-clean"
                        ),
                    )
                    return

                yield InitProgress(
                    phase=InitProgress.Phase.EMBEDDING,
                    progress=0.1,
                    message="Indexing KB via GPU-coordinated VectorSearchService...",
                )

                async for event in vector_search.index_kb_stream(kb_root=kb_root):
                    # Map VectorSearchService progress events to InitProgress
                    if event.phase == SearchPhase.REQUESTING_GPU:
                        yield InitProgress(
                            phase=InitProgress.Phase.EMBEDDING,
                            progress=0.12,
                            message=event.message,
                        )
                    elif event.phase == SearchPhase.EVICTING_ENDPOINTS:
                        yield InitProgress(
                            phase=InitProgress.Phase.EMBEDDING,
                            progress=0.15,
                            message=event.message,
                        )
                    elif event.phase == SearchPhase.LOADING_MODEL:
                        yield InitProgress(
                            phase=InitProgress.Phase.EMBEDDING,
                            progress=0.2,
                            message=event.message,
                        )
                    elif event.phase == SearchPhase.INDEXING:
                        yield InitProgress(
                            phase=InitProgress.Phase.EMBEDDING,
                            progress=0.3,
                            message=event.message,
                        )
                    elif event.phase == SearchPhase.ERROR:
                        yield InitProgress(
                            phase=InitProgress.Phase.ERROR,
                            progress=0.0,
                            message=event.message,
                        )
                        return
                    elif event.phase == SearchPhase.COMPLETE:
                        yield InitProgress(
                            phase=InitProgress.Phase.EMBEDDING,
                            progress=0.4,
                            message=event.message,
                        )
            else:
                yield InitProgress(
                    phase=InitProgress.Phase.EMBEDDING,
                    progress=0.4,
                    message=f"Qdrant already has embeddings, skipping indexing",
                )

            # PROJECTING — CPU-only: retrieve embeddings from Qdrant + UMAP
            yield InitProgress(
                phase=InitProgress.Phase.PROJECTING,
                progress=0.45,
                message="Projecting embeddings to 19x19 grid (UMAP)...",
            )

            grid_manager = get_grid_manager(method=projection_method, kb_root=kb_root)
            tda_manager = get_tda_manager()

            # project_kb() reads from Qdrant (CPU) + runs UMAP (CPU)
            # It never touches the GPU embedder.
            # UMAP on 98K+ points can take 30+ minutes — send heartbeats.
            grid_manager.invalidate_cache()
            loop = asyncio.get_event_loop()
            projection_task = loop.run_in_executor(
                None,
                lambda: grid_manager.get_grid_data(force_refresh=True)
            )
            # Send heartbeat every 15s while projection runs
            heartbeat_count = 0
            while True:
                done, _ = await asyncio.wait(
                    {projection_task}, timeout=15.0
                )
                if done:
                    break
                heartbeat_count += 1
                elapsed_min = heartbeat_count * 15 / 60
                yield InitProgress(
                    phase=InitProgress.Phase.PROJECTING,
                    progress=0.45 + min(0.09, heartbeat_count * 0.005),
                    message=f"UMAP projection running ({elapsed_min:.1f}m elapsed)...",
                )

            grid_data = projection_task.result()

            if not grid_data or grid_data.n_documents == 0:
                yield InitProgress(
                    phase=InitProgress.Phase.ERROR,
                    progress=0.0,
                    message="No documents found after projection",
                )
                return

            yield InitProgress(
                phase=InitProgress.Phase.PROJECTING,
                progress=0.55,
                message=f"Projected {grid_data.n_documents} documents to grid",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

            # TDA — also CPU-heavy, send heartbeats
            yield InitProgress(
                phase=InitProgress.Phase.TDA,
                progress=0.6,
                message="Computing TDA features (H0/H1/H2)...",
            )

            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            raw_embeddings = grid_data.raw_embeddings
            if raw_embeddings is not None and len(raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(raw_embeddings))
                ])
                tda_task = loop.run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )
                tda_heartbeat = 0
                while True:
                    done, _ = await asyncio.wait(
                        {tda_task}, timeout=15.0
                    )
                    if done:
                        break
                    tda_heartbeat += 1
                    elapsed_min = tda_heartbeat * 15 / 60
                    yield InitProgress(
                        phase=InitProgress.Phase.TDA,
                        progress=0.6 + min(0.15, tda_heartbeat * 0.01),
                        message=f"TDA computation running ({elapsed_min:.1f}m elapsed)...",
                    )
                tda_features = tda_task.result()

            # GEOMETRY (compute curvature, gradients, divergence)
            yield InitProgress(
                phase=InitProgress.Phase.GEOMETRY,
                progress=0.8,
                message="Computing geometry features (curvature, gradients)...",
            )

            logger.info(f"Geometry check: raw_embeddings={raw_embeddings is not None}, grid_coords={grid_coords is not None}")
            if raw_embeddings is not None and grid_coords is not None:
                try:
                    k_neighbors = min(15, len(raw_embeddings) - 1)
                    logger.info(f"Geometry: k_neighbors={k_neighbors}, len(raw_embeddings)={len(raw_embeddings)}")
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geom_task = loop.run_in_executor(
                            None, lambda: asyncio.run(gc.compute_features(raw_embeddings, grid_coords))
                        )
                        geom_heartbeat = 0
                        while True:
                            done, _ = await asyncio.wait(
                                {geom_task}, timeout=15.0
                            )
                            if done:
                                break
                            geom_heartbeat += 1
                            elapsed_min = geom_heartbeat * 15 / 60
                            yield InitProgress(
                                phase=InitProgress.Phase.GEOMETRY,
                                progress=0.8 + min(0.08, geom_heartbeat * 0.005),
                                message=f"Geometry computation running ({elapsed_min:.1f}m elapsed)...",
                            )
                        geometry_features = geom_task.result()
                        logger.info(f"Computed geometry features: curvatures={len(geometry_features.curvatures)}, gradients={len(geometry_features.gradients)}")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    import traceback
                    traceback.print_exc()
                    geometry_features = None
            else:
                logger.warning(f"Skipping geometry: no raw embeddings or grid coords")

            # SAVING
            yield InitProgress(
                phase=InitProgress.Phase.SAVING,
                progress=0.9,
                message="Saving to Postgres cache...",
            )

            await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=projection_method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            generation = await get_current_generation(kb_root)

            # COMPLETE
            yield InitProgress(
                phase=InitProgress.Phase.COMPLETE,
                progress=1.0,
                message=f"Initialized {grid_data.n_documents} documents (gen {generation})",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

        except Exception as e:
            logger.exception(f"InitProgressStream failed: {e}")
            yield InitProgress(
                phase=InitProgress.Phase.ERROR,
                progress=0.0,
                message=str(e),
            )

    # ==============================================================
    # MetaAgent (Multi-Agent Analytics)
    # ==============================================================

    async def MetaAgentQuery(
        self,
        request: MetaAgentQueryRequest,
        context: grpc.aio.ServicerContext,
    ) -> MetaAgentQueryResponse:
        """Run multi-agent analytics query.

        Coordinates multiple analyst agents to answer natural language
        questions by correlating AGE lineage, meta schema operations,
        resources, and topology data.

        Uses KB semantic search for entity resolution, allowing natural
        language references like "CSA docs" to resolve to actual KB paths.
        """
        start_time = time.time()
        try:
            from ....agents.metaagent_swarm import MetaAgentManager

            # Create inference function using backend router
            async def inference_fn(system: str, user: str, temperature: float = 0.7) -> str:
                if self._services.backend_router:
                    result = await self._services.backend_router.complete(
                        prompt=user,
                        agent_alias="orchestrator",  # Use orchestrator for multi-agent reasoning
                        system_prompt=system,
                        temperature=temperature,
                        max_tokens=4096,
                        task_type="metaagent_query",
                    )
                    return result.content or ""
                return ""

            # Create search function for entity resolution
            async def search_fn(query: str, limit: int = 10) -> list[dict]:
                if self._services.embedding_service:
                    try:
                        results = await self._services.embedding_service.semantic_search(
                            query=query,
                            collection="kb",
                            limit=limit,
                        )
                        return [
                            {"path": r.path, "title": r.title, "score": r.score}
                            for r in results
                        ]
                    except Exception as e:
                        logger.warning(f"Search failed: {e}")
                return []

            metaagent = MetaAgentManager(
                inference_fn=inference_fn,
                search_fn=search_fn,
            )

            # Run analysis
            domains = list(request.domains) if request.domains else None
            result = await metaagent.analyze(
                question=request.query,
                domains=domains,
                include_dot=request.include_dot,
                include_markdown=request.include_markdown,
            )

            # Convert agent insights to bytes for transport
            agent_insights_bytes: dict[str, bytes] = {}
            for role_name, insight in result.agent_insights.items():
                insight_data = {
                    "role": insight.role.value,
                    "reasoning": insight.reasoning,
                    "query": insight.query,
                    "query_type": insight.query_type,
                    "results": insight.results,
                    "insight": insight.insight,
                    "error": insight.error,
                    "duration_ms": insight.duration_ms,
                }
                agent_insights_bytes[role_name] = json.dumps(insight_data).encode()

            duration_ms = int((time.time() - start_time) * 1000)

            return MetaAgentQueryResponse(
                success=result.succeeded,
                answer=result.answer,
                dot_graph=result.dot_graph,
                markdown_tables=result.markdown_tables,
                agent_insights=agent_insights_bytes,
                queries_executed=result.queries_executed,
                agents_used=len(result.agent_insights),
                duration_ms=duration_ms,
                error=result.error or "",
            )

        except Exception as e:
            logger.exception(f"MetaAgentQuery failed: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            return MetaAgentQueryResponse(
                success=False,
                error=f"MetaAgent query failed: {e}",
                duration_ms=duration_ms,
            )

    async def MetaAgentQueryStream(
        self,
        request: MetaAgentQueryRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[MetaAgentEvent]:
        """Stream multi-agent analytics query with real-time progress.

        Yields MetaAgentEvent messages as each analyst runs and the
        Correlator synthesizes results.
        """
        try:
            from ....agents.metaagent_swarm import (
                MetaAgentManager,
                MetaAgentEventType as LocalEventType,
            )

            # Create inference function using backend router
            async def inference_fn(system: str, user: str, temperature: float = 0.7) -> str:
                if self._services.backend_router:
                    result = await self._services.backend_router.complete(
                        prompt=user,
                        agent_alias="orchestrator",  # Use orchestrator for multi-agent reasoning
                        system_prompt=system,
                        temperature=temperature,
                        max_tokens=4096,
                        task_type="metaagent_query_stream",
                    )
                    return result.content or ""
                return ""

            # Create search function for entity resolution
            async def search_fn(query: str, limit: int = 10) -> list[dict]:
                if self._services.embedding_service:
                    try:
                        results = await self._services.embedding_service.semantic_search(
                            query=query,
                            collection="kb",
                            limit=limit,
                        )
                        return [
                            {"path": r.path, "title": r.title, "score": r.score}
                            for r in results
                        ]
                    except Exception as e:
                        logger.warning(f"Search failed: {e}")
                return []

            metaagent = MetaAgentManager(
                inference_fn=inference_fn,
                search_fn=search_fn,
            )

            # Map local event type to proto event type
            type_map = {
                LocalEventType.AGENT_STARTED: MetaAgentEvent.Type.AGENT_STARTED,
                LocalEventType.AGENT_QUERY: MetaAgentEvent.Type.AGENT_QUERY,
                LocalEventType.AGENT_RESULT: MetaAgentEvent.Type.AGENT_RESULT,
                LocalEventType.AGENT_COMPLETED: MetaAgentEvent.Type.AGENT_COMPLETED,
                LocalEventType.CORRELATION: MetaAgentEvent.Type.CORRELATION,
                LocalEventType.COMPLETE: MetaAgentEvent.Type.COMPLETE,
                LocalEventType.ERROR: MetaAgentEvent.Type.ERROR,
            }

            # Stream analysis events
            domains = list(request.domains) if request.domains else None
            async for event in metaagent.analyze_streaming(
                question=request.query,
                domains=domains,
                include_dot=request.include_dot,
                include_markdown=request.include_markdown,
            ):
                proto_event = MetaAgentEvent(
                    type=type_map.get(event.type, MetaAgentEvent.Type.ERROR),
                    timestamp_ms=int(event.timestamp.timestamp() * 1000),
                    agent=event.agent,
                    domain=event.domain,
                    message=event.message,
                    data=json.dumps(event.data).encode() if event.data else b"",
                )
                yield proto_event

        except Exception as e:
            logger.exception(f"MetaAgentQueryStream failed: {e}")
            yield MetaAgentEvent(
                type=MetaAgentEvent.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message=f"MetaAgent stream failed: {e}",
            )

    # =========================================================================
    # ThetaAgent (Neuromorphic Consolidation)
    # =========================================================================

    async def ThetaSitrep(
        self,
        request: ThetaSitrepRequest,
        context: grpc.aio.ServicerContext,
    ) -> ThetaSitrepResponse:
        """Generate situational awareness report via ThetaService only."""
        theta_service = getattr(self._services, "theta_service", None)
        if theta_service is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "ThetaService is not registered on the engine.\n"
                "  Guru: #THETA.00000007.NOSVC\n"
                "  Try: /health fix engine",
            )

        try:
            horizon = request.horizon or "day"
            result = await theta_service.sitrep(horizon=horizon)

            if not result.get("success"):
                return ThetaSitrepResponse(
                    success=False,
                    error=result.get("error", "Unknown error"),
                )

            report = result.get("report", {})
            return ThetaSitrepResponse(
                success=True,
                horizon=horizon,
                generated_at_ms=int(
                    report.get("generated_at_ms", 0)
                    or (report.get("generated_at", 0) * 1000 if isinstance(report.get("generated_at"), float) else 0)
                ),
                healthy=report.get("system_status", {}).get("healthy", False),
                status_text=report.get("system_status", {}).get("status_text", ""),
                gpu_count=report.get("system_status", {}).get("gpu_count", 0),
                endpoint_count=report.get("system_status", {}).get("endpoint_count", 0),
                priority_count=len(report.get("priorities", [])),
                thought_count=len(report.get("thoughts", [])),
                objective_count=len(report.get("objectives", [])),
                project_count=report.get("project_count", 0),
                report_json=json.dumps(report).encode(),
                ascii_format=result.get("ascii_format", ""),
            )
        except Exception as e:
            logger.exception(f"ThetaSitrep failed: {e}")
            return ThetaSitrepResponse(
                success=False,
                error=str(e),
            )

    async def ThetaConsolidate(
        self,
        request: ThetaConsolidateRequest,
        context: grpc.aio.ServicerContext,
    ) -> ThetaConsolidateResponse:
        """Run NVAR-mediated consolidation via ThetaService only."""
        theta_service = getattr(self._services, "theta_service", None)
        if theta_service is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "ThetaService is not registered on the engine.\n"
                "  Guru: #THETA.00000007.NOSVC\n"
                "  Try: /health fix engine",
            )

        try:
            temporal_slice = request.temporal_slice or None
            max_candidates = request.max_candidates or 10
            result = await theta_service.run_consolidation(
                temporal_slice=temporal_slice,
                max_candidates=max_candidates,
            )

            signal = result.get("signal", {}) or {}
            return ThetaConsolidateResponse(
                success=result.get("success", False),
                slice_id=result.get("slice_id", ""),
                urgency=signal.get("urgency", 0.0),
                drift=signal.get("drift", 0.0),
                candidates_evaluated=result.get("candidates_evaluated", 0),
                candidates_selected=result.get("candidates_selected", 0),
                documents_augmented=result.get("documents_augmented", 0),
                error=result.get("error", ""),
                guru_meditation=result.get("guru_code", ""),
            )
        except Exception as e:
            error_msg = str(e)
            guru = ""
            if "DEEPONTO_UNAVAILABLE" in error_msg:
                guru = "#THETA.00000001.DEEPONTO"

            logger.exception(f"ThetaConsolidate failed: {e}")
            return ThetaConsolidateResponse(
                success=False,
                error=error_msg,
                guru_meditation=guru,
            )

    async def ThetaConsolidationStats(
        self,
        request: ThetaConsolidationStatsRequest,
        context: grpc.aio.ServicerContext,
    ) -> ThetaConsolidationStatsResponse:
        """Get consolidation statistics via ThetaService only."""
        theta_service = getattr(self._services, "theta_service", None)
        if theta_service is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "ThetaService is not registered on the engine.\n"
                "  Guru: #THETA.00000007.NOSVC\n"
                "  Try: /health fix engine",
            )

        try:
            stats = theta_service.get_consolidation_stats()

            return ThetaConsolidationStatsResponse(
                # NVAR dynamics
                nvar_k=stats["dynamics"]["k"],
                nvar_order=stats["dynamics"]["polynomial_order"],
                slice_count=stats["dynamics"].get("slice_count", stats["dynamics"].get("history_length", 0)),
                can_predict=stats["dynamics"]["can_predict"],
                # KG policy
                research_mode=stats["kg_policy"]["research_mode"],
                measurement_cost=stats["kg_policy"]["measurement_cost"],
                n_measurements=stats["kg_policy"]["belief_state"]["n_measurements"],
                current_best_value=stats["kg_policy"]["belief_state"]["current_best"],
                # Effectiveness
                effectiveness_history_length=stats["effectiveness"]["history_length"],
                effectiveness_trend=stats["effectiveness"]["trend"]["trend"],
                mean_contribution=stats["effectiveness"]["trend"]["mean_contribution"],
                # Subsumption
                confidence_threshold=stats["subsumption"]["confidence_threshold"],
                template_type=stats["subsumption"]["template_type"],
                classifier_loaded=stats["subsumption"]["classifier_loaded"],
            )
        except Exception as e:
            logger.exception(f"ThetaConsolidationStats failed: {e}")
            await context.abort(
                grpc.StatusCode.INTERNAL,
                f"ThetaConsolidationStats failed: {e}\n"
                "  Try: /health fix engine",
            )

    async def ThetaAgenda(
        self,
        request: ThetaAgendaRequest,
        context: grpc.aio.ServicerContext,
    ) -> ThetaAgendaResponse:
        """List or init the KB day agenda via ThetaService only."""
        theta_service = getattr(self._services, "theta_service", None)
        if theta_service is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "ThetaService is not registered on the engine.\n"
                "  Guru: #THETA.00000007.NOSVC\n"
                "  Try: /health fix engine",
            )

        try:
            result = theta_service.agenda(
                action=request.action or "list",
                horizon=request.horizon or "day",
            )
            if not result.get("success"):
                return ThetaAgendaResponse(
                    success=False,
                    action=request.action or "list",
                    horizon=request.horizon or "day",
                    error=result.get("error", ""),
                )
            items = [
                ThetaAgendaItem(
                    description=i.get("description", ""),
                    priority=i.get("priority", ""),
                    project=i.get("project", ""),
                    due_date=i.get("due_date", ""),
                    completed=bool(i.get("completed")),
                    source_path=i.get("source_path", ""),
                )
                for i in result.get("items", [])
            ]
            return ThetaAgendaResponse(
                success=True,
                action=result.get("action", ""),
                horizon=result.get("horizon", ""),
                path=result.get("path", ""),
                created=bool(result.get("created")),
                items=items,
                ascii_format=result.get("ascii_format", ""),
            )
        except Exception as e:
            logger.exception(f"ThetaAgenda failed: {e}")
            return ThetaAgendaResponse(
                success=False,
                action=request.action or "list",
                horizon=request.horizon or "day",
                error=str(e),
            )

    def _agenda_card(self, item: Any) -> AgendaCard:
        return AgendaCard(
            path=item.path,
            kind=item.kind,
            title=item.title,
            body=item.body,
            excerpt=item.excerpt(),
            prev=item.prev,
            next=item.next,
            starts=item.starts,
            ends=item.ends,
            tags=list(item.tags),
            pin=item.pin,
            checks=[
                AgendaCheck(done=bool(c.get("done")), text=str(c.get("text", "")))
                for c in item.checks
            ],
            created_ms=item.created_ms,
            intent=item.intent,
            with_whom=item.with_whom,
            calendar_url=item.calendar_url(),
            timezone=getattr(item, "timezone", "") or "",
        )

    async def AgendaList(
        self,
        request: AgendaListRequest,
        context: aio.ServicerContext,
    ) -> AgendaListResponse:
        from ...services.agenda_notes import (
            AgendaError,
            kb_root_from_env,
            list_items,
        )

        try:
            items = list_items(
                kb_root_from_env(),
                window_days=request.window_days or 14,
                kind=request.kind or "",
                tag=request.tag or "",
                origin=request.origin or "",
                tz_name=request.timezone or "",
            )
            return AgendaListResponse(items=[self._agenda_card(i) for i in items])
        except AgendaError as e:
            return AgendaListResponse(error=str(e))
        except Exception as e:
            logger.exception("AgendaList failed")
            return AgendaListResponse(error=str(e))

    async def AgendaGet(
        self,
        request: AgendaGetRequest,
        context: aio.ServicerContext,
    ) -> AgendaGetResponse:
        from ...services.agenda_notes import (
            AgendaError,
            get_item,
            kb_root_from_env,
        )

        try:
            item = get_item(kb_root_from_env(), request.path)
            return AgendaGetResponse(item=self._agenda_card(item))
        except AgendaError as e:
            return AgendaGetResponse(error=str(e))
        except Exception as e:
            logger.exception("AgendaGet failed")
            return AgendaGetResponse(error=str(e))

    async def AgendaCreate(
        self,
        request: AgendaCreateRequest,
        context: aio.ServicerContext,
    ) -> AgendaCreateResponse:
        from ...services.agenda_notes import (
            AgendaError,
            create_item,
            kb_root_from_env,
        )

        try:
            item = create_item(
                kb_root_from_env(),
                kind=request.kind,
                title=request.title,
                body=request.body,
                starts=request.starts,
                ends=request.ends,
                tags=list(request.tags),
                pin=request.pin,
                intent=request.intent,
                with_whom=request.with_whom,
                tz_name=request.timezone or "",
            )
            return AgendaCreateResponse(item=self._agenda_card(item))
        except AgendaError as e:
            return AgendaCreateResponse(error=str(e))
        except Exception as e:
            logger.exception("AgendaCreate failed")
            return AgendaCreateResponse(error=str(e))

    async def AgendaUpdate(
        self,
        request: AgendaUpdateRequest,
        context: aio.ServicerContext,
    ) -> AgendaUpdateResponse:
        from ...services.agenda_notes import (
            AgendaError,
            kb_root_from_env,
            update_item,
        )

        try:
            kwargs: dict[str, Any] = {}
            if request.title:
                kwargs["title"] = request.title
            if request.body:
                kwargs["body"] = request.body
            if request.starts:
                kwargs["starts"] = request.starts
            if request.ends:
                kwargs["ends"] = request.ends
            if request.tags:
                kwargs["tags"] = list(request.tags)
            if request.has_pin:
                kwargs["pin"] = request.pin
            if request.has_checks:
                kwargs["checks"] = [
                    {"done": c.done, "text": c.text} for c in request.checks
                ]
            if request.has_intent:
                kwargs["intent"] = request.intent
            if request.has_with:
                kwargs["with_whom"] = request.with_whom
            if request.has_timezone:
                kwargs["tz_name"] = request.timezone
            item = update_item(kb_root_from_env(), request.path, **kwargs)
            return AgendaUpdateResponse(item=self._agenda_card(item))
        except AgendaError as e:
            return AgendaUpdateResponse(error=str(e))
        except Exception as e:
            logger.exception("AgendaUpdate failed")
            return AgendaUpdateResponse(error=str(e))

    async def WeeklySignalsSummary(
        self,
        request: WeeklySignalsSummaryRequest,
        context: aio.ServicerContext,
    ) -> WeeklySignalsSummaryResponse:
        from ...services.weekly_signals_summary import (
            WeeklySummaryError,
            run_weekly_summary,
        )

        try:
            result = await run_weekly_summary(
                week=request.week or "",
                previous=bool(request.previous),
                services=self._services,
            )
            remotes = [
                WeeklySignalsRemote(project=p.project, name=r.name, url=r.url)
                for p in result.participants
                for r in p.remotes
            ]
            return WeeklySignalsSummaryResponse(
                path=result.path,
                week=result.week.label,
                body=result.body,
                projects=[p.project for p in result.participants],
                remotes=remotes,
                acp_used=result.acp_used,
            )
        except WeeklySummaryError as e:
            return WeeklySignalsSummaryResponse(error=str(e))
        except Exception as e:
            logger.exception("WeeklySignalsSummary failed")
            return WeeklySignalsSummaryResponse(error=str(e))

    async def WeeklySignalsSummaryList(
        self,
        request: WeeklySignalsSummaryListRequest,
        context: aio.ServicerContext,
    ) -> WeeklySignalsSummaryListResponse:
        from ...services.agenda_notes import kb_root_from_env
        from ...services.weekly_signals_summary import (
            WeeklySummaryError,
            list_summaries,
        )

        try:
            items = list_summaries(kb_root_from_env(), limit=request.limit or 12)
            return WeeklySignalsSummaryListResponse(items=items)
        except WeeklySummaryError as e:
            return WeeklySignalsSummaryListResponse(error=str(e))
        except Exception as e:
            logger.exception("WeeklySignalsSummaryList failed")
            return WeeklySignalsSummaryListResponse(error=str(e))

    async def WeeklySignalsSummaryGet(
        self,
        request: WeeklySignalsSummaryGetRequest,
        context: aio.ServicerContext,
    ) -> WeeklySignalsSummaryGetResponse:
        from ...services.agenda_notes import kb_root_from_env
        from ...services.weekly_signals_summary import (
            WeeklySummaryError,
            read_summary,
        )

        try:
            body = read_summary(kb_root_from_env(), request.path)
            return WeeklySignalsSummaryGetResponse(path=request.path, body=body)
        except WeeklySummaryError as e:
            return WeeklySignalsSummaryGetResponse(error=str(e))
        except Exception as e:
            logger.exception("WeeklySignalsSummaryGet failed")
            return WeeklySignalsSummaryGetResponse(error=str(e))

    async def KnowledgeSummary(
        self,
        request: KnowledgeSummaryRequest,
        context: aio.ServicerContext,
    ) -> KnowledgeSummaryResponse:
        from ...services.knowledge_summary import (
            KnowledgeSummaryError,
            run_knowledge_summaries,
        )
        from ...services.weekly_signals_summary import (
            WeeklySummaryError,
            parse_iso_week,
        )

        try:
            written = run_knowledge_summaries(
                week=request.week or "",
                section=request.section or "",
            )
            week = parse_iso_week(request.week or "").label
            return KnowledgeSummaryResponse(
                week=week,
                items=[
                    KnowledgeSummaryWritten(
                        section=w.section, path=w.path, notes=w.notes
                    )
                    for w in written
                ],
            )
        except (KnowledgeSummaryError, WeeklySummaryError) as e:
            return KnowledgeSummaryResponse(error=str(e))
        except Exception as e:
            logger.exception("KnowledgeSummary failed")
            return KnowledgeSummaryResponse(error=str(e))

    async def FederationSurfaces(
        self,
        request: FederationSurfacesRequest,
        context: aio.ServicerContext,
    ) -> FederationSurfacesResponse:
        from ...s2s import collect_peer_surfaces

        try:
            rows = await collect_peer_surfaces(self._services)
            return FederationSurfacesResponse(
                items=[
                    FederationSurface(
                        project=r["project"],
                        engine_target=r["engine_target"],
                        primary_ui=r["primary_ui"],
                    )
                    for r in rows
                ]
            )
        except Exception as e:
            logger.exception("FederationSurfaces failed")
            return FederationSurfacesResponse(error=str(e))

    async def AskPresent(
        self,
        request: AskPresentRequest,
        context: aio.ServicerContext,
    ) -> AskPresentResponse:
        from ...services.ask_present import AskPresentError, build_artifact

        try:
            art = await build_artifact(
                kind=request.kind or "ohlc",
                symbol=request.symbol or "",
                title=request.title or "",
                from_date=request.from_date or "",
                to_date=request.to_date or "",
                payload_json=request.payload_json or "",
            )
            n = len(art.get("bars") or art.get("rows") or art.get("links") or [])
            return AskPresentResponse(
                artifact_json=json.dumps(art),
                n_items=n,
            )
        except AskPresentError as e:
            return AskPresentResponse(error=str(e))
        except Exception as e:
            logger.exception("AskPresent failed")
            return AskPresentResponse(error=str(e))

    async def FmpNews(
        self,
        request: object,
        context: aio.ServicerContext,
    ) -> object:
        from ...generated import FmpNewsResponse
        from ...services.fmp_client import FMPClientError, get_fmp_client

        kind = (getattr(request, "kind", None) or "stock").strip().lower()
        limit = int(getattr(request, "limit", 0) or 15)
        limit = max(1, min(limit, 40))
        symbol = (getattr(request, "symbol", None) or "").strip().upper()
        client = await get_fmp_client()
        try:
            if kind == "general":
                items = await client.get_latest_general_news(limit=limit)
            else:
                items = await client.get_latest_stock_news(limit=limit)
            if symbol:
                items = [
                    i
                    for i in items
                    if str(i.get("symbol") or "").upper() == symbol
                ]
            return FmpNewsResponse(items_json=json.dumps(items[:limit]))
        except FMPClientError as e:
            return FmpNewsResponse(error=str(e))
        except Exception as e:
            logger.exception("FmpNews failed")
            return FmpNewsResponse(error=str(e))
        finally:
            await client.__aexit__(None, None, None)

    async def FmpSearch(
        self,
        request: object,
        context: aio.ServicerContext,
    ) -> object:
        from ...generated import FmpSearchResponse
        from ...services.fmp_client import FMPClientError, get_fmp_client

        query = (getattr(request, "query", None) or "").strip()
        if not query:
            return FmpSearchResponse(
                error="query is required.\n  Guru: #FMP.00000006.NOQUERY"
            )
        limit = int(getattr(request, "limit", 0) or 8)
        limit = max(1, min(limit, 20))
        client = await get_fmp_client()
        try:
            hits = await client.search_ticker(query, limit=limit)
            return FmpSearchResponse(items_json=json.dumps(hits))
        except FMPClientError as e:
            return FmpSearchResponse(error=str(e))
        except Exception as e:
            logger.exception("FmpSearch failed")
            return FmpSearchResponse(error=str(e))
        finally:
            await client.__aexit__(None, None, None)

    async def FmpEmployees(
        self,
        request: object,
        context: aio.ServicerContext,
    ) -> object:
        from ...generated import FmpEmployeesResponse
        from ...services.fmp_client import FMPClientError, get_fmp_client

        symbol = (getattr(request, "symbol", None) or "").strip().upper()
        if not symbol:
            return FmpEmployeesResponse(
                error="symbol is required.\n  Guru: #FMP.00000007.NOSYMBOL"
            )
        limit = int(getattr(request, "limit", 0) or 16)
        client = await get_fmp_client()
        try:
            rows = await client.get_employee_counts(symbol, limit=limit)
            return FmpEmployeesResponse(items_json=json.dumps(rows))
        except FMPClientError as e:
            return FmpEmployeesResponse(error=str(e))
        except Exception as e:
            logger.exception("FmpEmployees failed")
            return FmpEmployeesResponse(error=str(e))
        finally:
            await client.__aexit__(None, None, None)

    def _summary_note(self, note: object) -> ProtoSummaryNote:
        return ProtoSummaryNote(
            id=getattr(note, "id", ""),
            title=getattr(note, "title", ""),
            body=getattr(note, "body", ""),
            section=getattr(note, "section", ""),
            lens=getattr(note, "lens", ""),
            week=getattr(note, "week", ""),
            mtime_ms=int(getattr(note, "mtime_ms", 0) or 0),
            links=list(getattr(note, "links", []) or []),
            origin_project=getattr(note, "origin_project", "") or "gaius",
            origin_id=getattr(note, "origin_id", ""),
            excerpt=getattr(note, "excerpt", "") or "",
            virtual=bool(getattr(note, "virtual", False)),
        )

    async def SummaryIndex(
        self,
        request: SummaryIndexRequest,
        context: aio.ServicerContext,
    ) -> SummaryIndexResponse:
        from ...services.agenda_notes import kb_root_from_env
        from ...services.summary_lineup import SummaryLineupError, build_index
        from ...services.weekly_signals_summary import WeeklySummaryError

        try:
            db = _summary_db(self._services)
            idx = await build_index(
                kb_root_from_env(),
                section=request.section or "",
                lens=request.lens or "",
                week=request.week or "",
                limit=request.limit or 48,
                db_pool=db,
            )
            seed = idx["seed"]
            return SummaryIndexResponse(
                week=str(idx["week"]),
                landing_id=str(idx["landing_id"] or ""),
                seed=self._summary_note(seed),
                items=[self._summary_note(n) for n in idx["items"]],
            )
        except (SummaryLineupError, WeeklySummaryError) as e:
            return SummaryIndexResponse(error=str(e))
        except Exception as e:
            logger.exception("SummaryIndex failed")
            return SummaryIndexResponse(error=str(e))

    async def SummaryGet(
        self,
        request: SummaryGetRequest,
        context: aio.ServicerContext,
    ) -> SummaryGetResponse:
        from ...services.agenda_notes import kb_root_from_env
        from ...services.summary_lineup import SummaryLineupError, build_index, get_note
        from ...services.weekly_signals_summary import WeeklySummaryError

        try:
            kb = kb_root_from_env()
            nid = request.id or ""
            if nid.startswith("lens/"):
                db = _summary_db(self._services)
                idx = await build_index(
                    kb,
                    section=request.section or "",
                    lens=request.lens or "",
                    week=request.week or "",
                    db_pool=db,
                )
                return SummaryGetResponse(note=self._summary_note(idx["seed"]))
            from ...services.summary_corpus import load_corpus_note, parse_corpus_id
            from ...services.summary_lineup import load_db_thought, parse_thought_id

            if parse_corpus_id(nid)[0]:
                note = await load_corpus_note(
                    _summary_db(self._services),
                    nid,
                    week=request.week or "",
                )
                return SummaryGetResponse(note=self._summary_note(note))
            if parse_thought_id(nid):
                note = await load_db_thought(
                    _summary_db(self._services),
                    nid,
                    week=request.week or "",
                )
                return SummaryGetResponse(note=self._summary_note(note))
            note = get_note(
                kb,
                nid,
                section=request.section or "",
                lens=request.lens or "",
                week=request.week or "",
            )
            return SummaryGetResponse(note=self._summary_note(note))
        except (SummaryLineupError, WeeklySummaryError) as e:
            return SummaryGetResponse(error=str(e))
        except Exception as e:
            logger.exception("SummaryGet failed")
            return SummaryGetResponse(error=str(e))

    async def SummaryHop(
        self,
        request: SummaryHopRequest,
        context: aio.ServicerContext,
    ) -> SummaryHopResponse:
        from ...services.agenda_notes import kb_root_from_env
        from ...services.summary_lineup import (
            SummaryLineupError,
            get_note,
            load_db_thought,
            parse_thought_id,
            resolve_hop,
        )
        from ...services.weekly_signals_summary import WeeklySummaryError

        try:
            kb = kb_root_from_env()
            target = request.target or ""
            from ...services.summary_corpus import load_corpus_note, parse_corpus_id

            if parse_corpus_id(target)[0]:
                note = await load_corpus_note(
                    _summary_db(self._services),
                    target,
                    week=request.week or "",
                )
                return SummaryHopResponse(
                    note=self._summary_note(note),
                    resolved_id=note.id,
                )
            if parse_thought_id(target):
                note = await load_db_thought(
                    _summary_db(self._services),
                    target,
                    week=request.week or "",
                )
                return SummaryHopResponse(
                    note=self._summary_note(note),
                    resolved_id=note.id,
                )
            resolved = resolve_hop(kb, request.from_id or "", target)
            note = get_note(kb, resolved, week=request.week or "")
            return SummaryHopResponse(
                note=self._summary_note(note),
                resolved_id=resolved,
            )
        except (SummaryLineupError, WeeklySummaryError) as e:
            return SummaryHopResponse(error=str(e))
        except Exception as e:
            logger.exception("SummaryHop failed")
            return SummaryHopResponse(error=str(e))

    async def SummaryFork(
        self,
        request: SummaryForkRequest,
        context: aio.ServicerContext,
    ) -> SummaryForkResponse:
        from ...services.agenda_notes import kb_root_from_env
        from ...services.summary_lineup import SummaryLineupError, fork_note
        from ...services.weekly_signals_summary import WeeklySummaryError

        try:
            note = await fork_note(
                kb_root_from_env(),
                request.id or "",
                origin_project=request.origin_project or "",
                services=self._services,
            )
            return SummaryForkResponse(note=self._summary_note(note))
        except (SummaryLineupError, WeeklySummaryError) as e:
            return SummaryForkResponse(error=str(e))
        except Exception as e:
            logger.exception("SummaryFork failed")
            return SummaryForkResponse(error=str(e))

    async def SummarySchedules(
        self,
        request: SummarySchedulesRequest,
        context: aio.ServicerContext,
    ) -> SummarySchedulesResponse:
        from ...services.summary_schedule import (
            ScheduleCatalogError,
            list_schedule_catalog,
        )

        try:
            cards = await list_schedule_catalog(_summary_db(self._services))
            return SummarySchedulesResponse(
                items=[
                    ProtoSummarySchedule(
                        id=c.id,
                        cron=c.cron,
                        task_type=c.task_type,
                        source=c.source,
                        enabled=c.enabled,
                        triggerable=c.triggerable,
                        cadence=c.cadence,
                    )
                    for c in cards
                ]
            )
        except ScheduleCatalogError as e:
            return SummarySchedulesResponse(error=str(e))
        except Exception as e:
            logger.exception("SummarySchedules failed")
            return SummarySchedulesResponse(error=str(e))

    async def SummaryScheduleTrigger(
        self,
        request: SummaryScheduleTriggerRequest,
        context: aio.ServicerContext,
    ) -> SummaryScheduleTriggerResponse:
        from ...services.summary_schedule import (
            ScheduleCatalogError,
            trigger_schedule,
        )

        try:
            task_id, task_type = await trigger_schedule(
                _summary_db(self._services), request.id or ""
            )
            return SummaryScheduleTriggerResponse(
                task_id=task_id, task_type=task_type
            )
        except ScheduleCatalogError as e:
            return SummaryScheduleTriggerResponse(error=str(e))
        except Exception as e:
            logger.exception("SummaryScheduleTrigger failed")
            return SummaryScheduleTriggerResponse(error=str(e))

    # -------------------------------------------------------------------------
    # CLT (Cross-Layer Transcoders) - Interpretable Sparse Feature Extraction
    # -------------------------------------------------------------------------

    async def CLTExtract(
        self,
        request: CLTExtractRequest,
        context: grpc.aio.ServicerContext,
    ) -> CLTExtractResponse:
        """Extract sparse features from text using Cross-Layer Transcoders.

        Uses BluelightAI's CLT for Qwen3 to extract interpretable sparse features.
        ~115 active features per layer from 20,480 feature space.

        CLT runs in a subprocess with isolated GPU (GPU 4 by default) to avoid
        memory conflicts with vLLM endpoints on GPUs 0-3.
        """
        try:
            from ....engine.services.clt_service import get_clt_service

            # Get model name (defaults to qwen3-1.7b)
            model_name = request.model_name or "qwen3-1.7b"

            # Get CLT service (spawns subprocess with isolated GPU)
            clt = get_clt_service(model_name=model_name)

            # Extract features via subprocess worker
            # Note: layer_indices filtering not yet implemented in worker
            top_k = request.top_k if request.top_k > 0 else 115

            # Use a synthetic role for direct extraction (not swarm context)
            state = clt.extract_features(request.text, role="_extract")

            # Get features from state
            features = []
            for idx, activation in state.sparse_features.items():
                features.append(
                    ProtoSparseFeature(
                        layer_idx=0,  # Aggregated across layers
                        position=0,
                        feature_idx=idx,
                        activation=activation,
                        semantic_label="",
                    )
                )

            # Sort by activation descending, limit to top_k
            features.sort(key=lambda f: f.activation, reverse=True)
            features = features[:top_k]

            return CLTExtractResponse(
                success=True,
                features=features,
                total_positions=1,  # Aggregated
                sparsity=len(features),
                model_used=model_name,
            )

        except KeyError as e:
            logger.error(f"CLTExtract model not found: {e}")
            return CLTExtractResponse(
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"CLTExtract failed: {e}")
            return CLTExtractResponse(
                success=False,
                error=str(e),
            )

    async def CLTAttribute(
        self,
        request: CLTAttributeRequest,
        context: grpc.aio.ServicerContext,
    ) -> CLTAttributeResponse:
        """Compute attribution graph showing feature influence paths.

        Traces which sparse features influence output at target positions
        using A_{s->t} = a_s * ||w_{s->t}|| attribution weights.
        """
        try:
            from ....models.clt import load_clt_model

            # Get or load CLT model
            model_name = request.model_name or "qwen3-1.7b"
            device = request.device or "cuda"

            clt_model = load_clt_model(name=model_name, device=device)

            # Parse target positions
            target_positions = list(request.target_positions) if request.target_positions else None
            threshold = request.threshold if request.threshold > 0 else 0.01

            # Compute attribution
            result = clt_model.compute_attribution(
                text=request.text,
                target_positions=target_positions,
                threshold=threshold,
            )

            # Convert to proto edges
            proto_edges = [
                ProtoAttributionEdge(
                    source_layer=e.source_layer,
                    source_feature=e.source_feature,
                    target_layer=e.target_layer,
                    target_feature=e.target_feature,
                    weight=e.weight,
                )
                for e in result.edges
            ]

            return CLTAttributeResponse(
                success=True,
                edges=proto_edges,
                dot_graph=result.dot_graph,
                edge_count=len(proto_edges),
                model_used=model_name,
            )

        except KeyError as e:
            logger.error(f"CLTAttribute model not found: {e}")
            return CLTAttributeResponse(
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"CLTAttribute failed: {e}")
            return CLTAttributeResponse(
                success=False,
                error=str(e),
            )

    async def CLTStatus(
        self,
        request: CLTStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> CLTStatusResponse:
        """Get CLT model status and availability."""
        try:
            from ....models.clt import CLT_MODELS

            # List available models
            available_models = list(CLT_MODELS.keys())

            # Check if models are loaded (would need model cache tracking)
            loaded_model = ""  # TODO: Track loaded models in engine

            # Get spec info for primary model
            features_per_layer = 0
            l0_sparsity = 0
            if available_models:
                spec = CLT_MODELS[available_models[0]]
                features_per_layer = spec.features_per_layer
                l0_sparsity = spec.l0_sparsity

            return CLTStatusResponse(
                available=True,  # Always available - circuit-tracer is required dependency
                models=available_models,
                loaded_model=loaded_model,
                features_per_layer=features_per_layer,
                l0_sparsity=l0_sparsity,
            )

        except Exception as e:
            logger.exception(f"CLTStatus failed: {e}")
            return CLTStatusResponse(
                available=False,
                error=str(e),
            )

    # ─────────────────────────────────────────────────────────────────────────
    # HealthObserver (Autonomous FMEA Monitoring + ACP Escalation)
    # ─────────────────────────────────────────────────────────────────────────

    async def HealthObserverStatus(
        self,
        request: HealthObserverStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> HealthObserverStatusResponse:
        """Get health observer daemon status."""
        try:
            observer = self._services.health_observer_service
            if not observer:
                return HealthObserverStatusResponse(
                    running=False,
                    enabled=False,
                    poll_count=0,
                )

            status = observer.get_status()

            # Convert incidents to proto
            proto_incidents = []
            for inc in status.get("incidents", []):
                proto_incidents.append(ProtoHealthIncident(
                    incident_id=inc.get("incident_id", ""),
                    fingerprint=inc.get("fingerprint", ""),
                    endpoint=inc.get("endpoint", ""),
                    failure_mode_id=inc.get("failure_mode_id", ""),
                    rpn_score=inc.get("rpn_score", 0),
                    rpn_severity=inc.get("rpn_severity", 5),
                    rpn_occurrence=inc.get("rpn_occurrence", 5),
                    rpn_detection=inc.get("rpn_detection", 5),
                    current_tier=inc.get("current_tier", 0),
                    sequence_id=inc.get("sequence_id") or "",
                    created_at=inc.get("created_at", ""),
                    last_check_at=inc.get("last_check_at", ""),
                    attempts=inc.get("attempts", 0),
                    github_issue=inc.get("github_issue") or 0,
                    status=inc.get("status", "unknown"),
                ))

            metrics = status.get("metrics", {})
            config = status.get("config", {})

            return HealthObserverStatusResponse(
                running=status.get("running", False),
                enabled=status.get("enabled", False),
                poll_count=status.get("poll_count", 0),
                last_poll_at=status.get("last_poll_at") or "",
                active_incidents=status.get("active_incidents", 0),
                incidents=proto_incidents,
                metrics=ProtoHealthObserverMetrics(
                    incidents_created=metrics.get("incidents_created", 0),
                    incidents_resolved=metrics.get("incidents_resolved", 0),
                    acp_escalations=metrics.get("acp_escalations", 0),
                ),
                config=ProtoHealthObserverConfig(
                    poll_interval=config.get("poll_interval", 30.0),
                    escalate_to_acp=config.get("escalate_to_acp", True),
                    github_repo=config.get("github_repo", ""),
                ),
            )

        except Exception as e:
            logger.exception(f"HealthObserverStatus failed: {e}")
            return HealthObserverStatusResponse(
                running=False,
                enabled=False,
            )

    async def HealthObserverStart(
        self,
        request: empty_pb2.Empty,
        context: grpc.aio.ServicerContext,
    ) -> HealthObserverStatusResponse:
        """Start the health observer daemon."""
        try:
            observer = self._services.health_observer_service
            if not observer:
                return HealthObserverStatusResponse(
                    running=False,
                    enabled=False,
                )

            await observer.start()

            # Return updated status
            return await self.HealthObserverStatus(
                HealthObserverStatusRequest(), context
            )

        except Exception as e:
            logger.exception(f"HealthObserverStart failed: {e}")
            return HealthObserverStatusResponse(
                running=False,
                enabled=False,
            )

    async def HealthObserverStop(
        self,
        request: empty_pb2.Empty,
        context: grpc.aio.ServicerContext,
    ) -> HealthObserverStatusResponse:
        """Stop the health observer daemon."""
        try:
            observer = self._services.health_observer_service
            if not observer:
                return HealthObserverStatusResponse(
                    running=False,
                    enabled=False,
                )

            await observer.stop()

            # Return updated status
            return await self.HealthObserverStatus(
                HealthObserverStatusRequest(), context
            )

        except Exception as e:
            logger.exception(f"HealthObserverStop failed: {e}")
            return HealthObserverStatusResponse(
                running=False,
                enabled=False,
            )

    async def HealthObserverForceCheck(
        self,
        request: ForceHealthCheckRequest,
        context: grpc.aio.ServicerContext,
    ) -> ForceHealthCheckResponse:
        """Force an immediate health check."""
        import json

        try:
            observer = self._services.health_observer_service
            if not observer:
                return ForceHealthCheckResponse(
                    healthy=True,
                    summary="Health observer not available",
                )

            # Get incident count before check
            incidents_before = len(observer.active_incidents)

            # Run forced check
            report = await observer.force_check()

            # Calculate new incidents
            incidents_after = len(observer.active_incidents)
            new_incidents = max(0, incidents_after - incidents_before)

            # Count check statuses and build check result messages
            checks = report.get("checks", [])
            passed = sum(1 for c in checks if c.get("status") != "FAIL")
            warnings = sum(1 for c in checks if c.get("status") == "WARN")
            failures = sum(1 for c in checks if c.get("status") == "FAIL")

            # Convert check dicts to proto messages
            check_results = []
            for check in checks:
                details = check.get("details", {})
                check_results.append(
                    HealthCheckResult(
                        name=check.get("name", "unknown"),
                        status=check.get("status", "FAIL"),
                        message=check.get("message", ""),
                        heuristic_id=check.get("heuristic_id", ""),
                        details_json=json.dumps(details) if details else "",
                    )
                )

            return ForceHealthCheckResponse(
                healthy=report.get("healthy", True),
                summary=f"{passed} passed, {warnings} warnings, {failures} failures",
                passed=passed,
                warnings=warnings,
                failures=failures,
                new_incidents=new_incidents,
                checks=check_results,
            )

        except Exception as e:
            logger.exception(f"HealthObserverForceCheck failed: {e}")
            return ForceHealthCheckResponse(
                healthy=False,
                summary=f"Error: {e}",
            )

    async def HealthObserverListIncidents(
        self,
        request: ListIncidentsRequest,
        context: grpc.aio.ServicerContext,
    ) -> ListIncidentsResponse:
        """List health incidents."""
        try:
            observer = self._services.health_observer_service
            if not observer:
                return ListIncidentsResponse()

            incidents = observer.active_incidents
            status_filter = request.status or "active"

            proto_incidents = []
            for inc in incidents:
                # Apply status filter
                if status_filter != "all" and inc.status != status_filter:
                    continue

                proto_incidents.append(ProtoHealthIncident(
                    incident_id=str(inc.incident_id),
                    fingerprint=inc.fingerprint,
                    endpoint=inc.endpoint,
                    failure_mode_id=inc.failure_mode_id,
                    rpn_score=inc.rpn_score,
                    rpn_severity=inc.rpn_severity,
                    rpn_occurrence=inc.rpn_occurrence,
                    rpn_detection=inc.rpn_detection,
                    current_tier=inc.current_tier,
                    sequence_id=str(inc.sequence_id) if inc.sequence_id else "",
                    created_at=inc.created_at.isoformat(),
                    last_check_at=inc.last_check_at.isoformat(),
                    attempts=inc.attempts,
                    github_issue=inc.github_issue or 0,
                    status=inc.status,
                ))

            return ListIncidentsResponse(incidents=proto_incidents)

        except Exception as e:
            logger.exception(f"HealthObserverListIncidents failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="HealthObserverListIncidents",
                exception_type=type(e).__name__,
                guru_code="#GR.HO.00001.LISTFAIL",
            )
            return ListIncidentsResponse()

    async def HealthObserverGetIncident(
        self,
        request: GetIncidentDetailRequest,
        context: grpc.aio.ServicerContext,
    ) -> GetIncidentDetailResponse:
        """Get details of a specific incident including ACP history."""
        try:
            observer = self._services.health_observer_service
            if not observer:
                return GetIncidentDetailResponse(found=False)

            # Use the new detailed method that includes healing events and ACP history
            detail = await observer.get_incident_detail(request.fingerprint)
            if not detail:
                return GetIncidentDetailResponse(found=False)

            # Extract RPN values from nested dict
            rpn_data = detail.get("rpn", {})

            proto_incident = ProtoHealthIncident(
                incident_id=detail.get("incident_id", ""),
                fingerprint=detail.get("fingerprint", ""),
                endpoint=detail.get("endpoint", ""),
                failure_mode_id=detail.get("failure_mode_id", ""),
                rpn_score=rpn_data.get("rpn", 0),
                rpn_severity=rpn_data.get("severity", 5),
                rpn_occurrence=rpn_data.get("occurrence", 5),
                rpn_detection=rpn_data.get("detection", 5),
                current_tier=detail.get("current_tier", 0),
                sequence_id=detail.get("sequence_id") or "",
                created_at=detail.get("created_at", ""),
                last_check_at=detail.get("last_check_at", ""),
                attempts=detail.get("attempts", 0),
                github_issue=detail.get("github_issue") or 0,
                status=detail.get("status", "unknown"),
            )

            # Include healing events and ACP history as JSON strings
            import json
            healing_events_json = json.dumps(detail.get("healing_events", []))
            acp_history_json = json.dumps(detail.get("acp_history", []))
            github_issue_detail_json = json.dumps(detail.get("github_issue_detail"))

            return GetIncidentDetailResponse(
                incident=proto_incident,
                found=True,
                healing_events_json=healing_events_json,
                acp_history_json=acp_history_json,
                github_issue_detail_json=github_issue_detail_json,
            )

        except Exception as e:
            logger.exception(f"HealthObserverGetIncident failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="HealthObserverGetIncident",
                exception_type=type(e).__name__,
                guru_code="#GR.HO.00002.GETFAIL",
            )
            return GetIncidentDetailResponse(found=False)

    async def HealthObserverResolveIncident(
        self,
        request: ResolveIncidentRequest,
        context: grpc.aio.ServicerContext,
    ) -> ResolveIncidentResponse:
        """Explicitly resolve an incident by fingerprint.

        Called by /health fix --close after successful ACP investigation.
        Removes incident from active tracking and updates GitHub issue status.
        """
        try:
            service = self._services.health_observer_service
            if not service:
                return ResolveIncidentResponse(
                    resolved=False,
                    fingerprint=request.fingerprint,
                    was_active=False,
                    note="HealthObserverService not initialized",
                )

            result = await service.resolve_incident(request.fingerprint)

            return ResolveIncidentResponse(
                resolved=result.get("resolved", False),
                fingerprint=result.get("fingerprint", request.fingerprint),
                was_active=result.get("was_active", False),
                note=result.get("note") or "",
            )

        except Exception as e:
            logger.exception(f"HealthObserverResolveIncident failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="HealthObserverResolveIncident",
                exception_type=type(e).__name__,
                guru_code="#GR.HO.00003.RESOLVEFAIL",
            )
            return ResolveIncidentResponse(
                resolved=False,
                fingerprint=request.fingerprint,
                was_active=False,
                note=f"Error: {e}",
            )

    async def HealthObserverGetOrphanedIssues(
        self,
        request: GetOrphanedIssuesRequest,
        context: grpc.aio.ServicerContext,
    ) -> GetOrphanedIssuesResponse:
        """Get orphaned GitHub issues (open issues with no active incident).

        Used by /health fix --close to handle race conditions where
        incidents were resolved but GitHub issues weren't closed.
        """
        try:
            service = self._services.health_observer_service
            if not service:
                return GetOrphanedIssuesResponse(orphans=[])

            orphans = await service.get_orphaned_github_issues()

            proto_orphans = [
                OrphanedGitHubIssue(
                    issue_number=o.get("issue_number", 0),
                    repo=o.get("repo", ""),
                    fingerprint=o.get("fingerprint", ""),
                    created_at=o.get("created_at") or "",
                    issue_url=o.get("issue_url") or "",
                )
                for o in orphans
            ]

            return GetOrphanedIssuesResponse(orphans=proto_orphans)

        except Exception as e:
            logger.exception(f"HealthObserverGetOrphanedIssues failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="HealthObserverGetOrphanedIssues",
                exception_type=type(e).__name__,
                guru_code="#GR.HO.00004.ORPHANFAIL",
            )
            return GetOrphanedIssuesResponse(orphans=[])

    # =========================================================================
    # Observability Dashboard Service Methods
    # =========================================================================

    async def SignalsTelemetry(
        self,
        request: SignalsTelemetryRequest,
        context: grpc.aio.ServicerContext,
    ) -> SignalsTelemetryResponse:
        """One Signals DCGM scrape. No store. 503/missing surface → error field."""
        from ...services.signals_telemetry import (
            SignalsTelemetryError,
            scrape_snapshot,
        )

        try:
            snap = await scrape_snapshot()
        except SignalsTelemetryError as e:
            return SignalsTelemetryResponse(error=str(e))
        return SignalsTelemetryResponse(
            source_url=snap["source_url"],
            scraped_at=snap["scraped_at"],
            total_w=snap["total_w"],
            parked_w=snap["parked_w"],
            inferring_w=snap["inferring_w"],
            gpus=[
                GpuWatt(
                    index=int(g.get("index") or 0),
                    uuid=str(g.get("uuid") or ""),
                    model=str(g.get("model") or ""),
                    power_w=float(g.get("power_w") or 0.0),
                    util=float(g.get("util") or 0.0),
                    memory_used_mib=float(g.get("memory_used_mib") or 0.0),
                    memory_free_mib=float(g.get("memory_free_mib") or 0.0),
                    energy_mj=float(g.get("energy_mj") or 0.0),
                    temp_c=float(g.get("temp_c") or 0.0),
                )
                for g in snap.get("gpus") or []
            ],
        )

    async def ObserveStatus(
        self,
        request: ObserveStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> ObserveStatusResponse:
        """Get observability dashboard data.

        Aggregates metrics from Prometheus and engine state into a single
        response for the CLI /observe command, providing TUI/CLI parity
        with ObservePanel.
        """
        from gaius.observability.metrics import OBSERVE_METRICS
        from gaius.observability.sources.prometheus import PrometheusSource

        try:
            # Initialize Prometheus source
            prometheus = PrometheusSource()
            prometheus_ok = await prometheus.health_check()
            self._signals_watts_snap = None

            # Query metrics
            metrics = []
            for metric_def in OBSERVE_METRICS:
                current_value = 0.0
                sparkline_data = []
                status = "ok"

                if metric_def.source == "prometheus" and prometheus_ok:
                    # Query current value
                    result = await prometheus.query_instant(metric_def.query)
                    if result:
                        current_value = result.value

                    # Query sparkline data if requested
                    if request.include_sparklines:
                        points = request.sparkline_points or 20
                        duration = points * 15  # 15s per point
                        series = await prometheus.query_range(
                            metric_def.query,
                            duration_seconds=duration,
                            step_seconds=15,
                        )
                        sparkline_data = [v.value for v in series.values]

                elif metric_def.source == "engine":
                    # Handle engine-sourced metrics
                    if metric_def.query == "evolution_cycles":
                        get_evo_status = self._services.get_evolution_status
                        if get_evo_status:
                            status_data = get_evo_status()
                            # Handle both sync and async callbacks
                            if hasattr(status_data, "__await__"):
                                status_data = await status_data
                            current_value = float(status_data.get("cycles_completed", 0))
                    elif metric_def.query in (
                        "signals_total_w",
                        "signals_inferring_w",
                        "signals_parked_w",
                    ):
                        from ...services.signals_telemetry import scrape_snapshot

                        if not hasattr(self, "_signals_watts_snap"):
                            try:
                                self._signals_watts_snap = await scrape_snapshot()
                            except Exception:
                                self._signals_watts_snap = None
                        snap = self._signals_watts_snap
                        if snap:
                            key = {
                                "signals_total_w": "total_w",
                                "signals_inferring_w": "inferring_w",
                                "signals_parked_w": "parked_w",
                            }[metric_def.query]
                            current_value = float(snap.get(key) or 0.0)

                # Determine status from thresholds
                status = metric_def.get_color(current_value)

                metrics.append(MetricSnapshot(
                    name=metric_def.id,
                    display_name=metric_def.name,
                    current_value=current_value,
                    unit=metric_def.unit,
                    sparkline_data=sparkline_data,
                    status=status,
                ))

            self._signals_watts_snap = None
            await prometheus.close()

            # Get endpoint status by reusing OrchestratorStatus (already has all fallback logic)
            from google.protobuf import empty_pb2 as empty_pb

            orch_response = await self.OrchestratorStatus(empty_pb.Empty(), context)

            endpoints = []
            healthy_count = 0
            unhealthy_count = 0

            for ep_info in orch_response.endpoints:
                # Convert ProcessStatus integer enum to status string
                # Use protobuf's Name() method on the descriptor
                from ...generated import ProcessStatus

                status_str = ProcessStatus.Name(ep_info.status).replace("PROCESS_STATUS_", "").lower()
                if ep_info.status == PROCESS_STATUS_HEALTHY:
                    healthy_count += 1
                elif ep_info.status in (PROCESS_STATUS_UNHEALTHY, PROCESS_STATUS_FAILED):
                    unhealthy_count += 1

                endpoints.append(EndpointSnapshot(
                    name=ep_info.name,
                    status=status_str,
                    gpus=[],  # OrchestratorStatus doesn't provide gpu_ids in EndpointInfo
                    model=ep_info.model,
                ))

            # Get active incidents count
            active_incidents = 0
            observer = self._services.health_observer_service
            if observer:
                obs_status = observer.get_status()
                incidents = obs_status.get("incidents", [])
                active_incidents = len([i for i in incidents if i.get("status") == "active"])

            # Get evolution cycles
            evolution_cycles = 0
            get_evo_status = self._services.get_evolution_status
            if get_evo_status:
                evo_status = get_evo_status()
                # Handle both sync and async callbacks
                if hasattr(evo_status, "__await__"):
                    evo_status = await evo_status
                evolution_cycles = evo_status.get("cycles_completed", 0)

            return ObserveStatusResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                prometheus_available=prometheus_ok,
                metrics=metrics,
                endpoints=endpoints,
                healthy_endpoints=healthy_count,
                unhealthy_endpoints=unhealthy_count,
                active_incidents=active_incidents,
                evolution_cycles=evolution_cycles,
            )

        except Exception as e:
            logger.exception(f"ObserveStatus failed: {e}")
            import traceback
            traceback.print_exc()  # Debug: print full traceback
            record_exception_caught(
                component="grpc",
                operation="ObserveStatus",
                exception_type=type(e).__name__,
                guru_code="#GR.OB.00001.STATUSFAIL",
            )
            return ObserveStatusResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                prometheus_available=False,
            )

    # =========================================================================
    # X Bookmarks Service Methods
    # =========================================================================

    async def XBookmarksGetAuthUrl(
        self,
        request: XBookmarksAuthRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksAuthResponse:
        """Get OAuth 2.0 authorization URL for X API access."""
        try:
            service = self._services.x_bookmarks_service
            if not service:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(
                    "XBookmarksService not initialized.\n"
                    "  Guru: #XB.00000001.SVCNOTINIT\n"
                    "  Try: /health fix x_bookmarks"
                )
                return XBookmarksAuthResponse()

            auth_url, state, verifier = await service.get_auth_url()
            return XBookmarksAuthResponse(
                auth_url=auth_url,
                state=state,
                verifier=verifier,
            )

        except Exception as e:
            logger.exception(f"XBookmarksGetAuthUrl failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksGetAuthUrl",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00001.AUTHURLFAIL",
            )
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return XBookmarksAuthResponse()

    async def XBookmarksCompleteAuth(
        self,
        request: XBookmarksCompleteAuthRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksCompleteAuthResponse:
        """Complete OAuth 2.0 flow with authorization code."""
        try:
            service = self._services.x_bookmarks_service
            if not service:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(
                    "XBookmarksService not initialized.\n"
                    "  Guru: #XB.00000001.SVCNOTINIT"
                )
                return XBookmarksCompleteAuthResponse(success=False)

            # Verifier is optional - will be looked up from database if not provided
            verifier = request.verifier if request.verifier else None
            result = await service.complete_auth(request.code, verifier)
            return XBookmarksCompleteAuthResponse(
                success=True,
                message="Authentication successful",
                user_id=result.get("user_id", ""),
                username=result.get("username", ""),
            )

        except Exception as e:
            logger.exception(f"XBookmarksCompleteAuth failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksCompleteAuth",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00002.COMPLETEFAIL",
            )
            return XBookmarksCompleteAuthResponse(
                success=False,
                error=str(e),
                message=str(e),
            )

    async def XBookmarksCompleteAuthByState(
        self,
        request: XBookmarksCompleteAuthByStateRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksCompleteAuthResponse:
        """Complete OAuth using state parameter to look up verifier.

        Used by Engine Federation and Cloudflare Worker callbacks where
        the state parameter is known but verifier needs to be looked up
        from the database.
        """
        try:
            service = self._services.x_bookmarks_service
            if not service:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(
                    "XBookmarksService not initialized.\n"
                    "  Guru: #XB.00000001.SVCNOTINIT"
                )
                return XBookmarksCompleteAuthResponse(success=False)

            result = await service.complete_auth_by_state(request.code, request.state)

            if "error" in result:
                return XBookmarksCompleteAuthResponse(
                    success=False,
                    error=result.get("error", "Unknown error"),
                    message=result.get("error", "Unknown error"),
                )

            return XBookmarksCompleteAuthResponse(
                success=True,
                message="Authentication successful",
                user_id=result.get("user_id", ""),
                username=result.get("username", ""),
            )

        except Exception as e:
            logger.exception(f"XBookmarksCompleteAuthByState failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksCompleteAuthByState",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00003.COMPLETEBYSTATEFAIL",
            )
            return XBookmarksCompleteAuthResponse(
                success=False,
                error=str(e),
                message=str(e),
            )

    async def XBookmarksAuthStatus(
        self,
        request: XBookmarksAuthStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksAuthStatusResponse:
        """Check X API authentication status."""
        try:
            service = self._services.x_bookmarks_service
            if not service:
                return XBookmarksAuthStatusResponse(
                    authenticated=False,
                    error="XBookmarksService not initialized",
                    guru_code="#XB.00000001.SVCNOTINIT",
                    action_required="NOT_INITIALIZED",
                    guidance_message=(
                        "X Bookmarks service is still initializing. "
                        "Wait for engine startup to complete."
                    ),
                )

            status = await service.get_auth_status()
            return XBookmarksAuthStatusResponse(
                authenticated=status.get("authenticated", False),
                user_id=status.get("user_id", ""),
                username=status.get("username", ""),
                expires_at=status.get("expires_at", ""),
                scopes=status.get("scopes", []),
                error=status.get("error", ""),
                guru_code=status.get("guru_code", ""),
                action_required=status.get("action_required", ""),
                guidance_message=status.get("message", ""),
            )

        except Exception as e:
            logger.exception(f"XBookmarksAuthStatus failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksAuthStatus",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00004.AUTHSTATUSFAIL",
            )
            return XBookmarksAuthStatusResponse(
                authenticated=False,
                error=str(e),
                action_required="ERROR",
                guidance_message="Check engine logs for details.",
            )

    async def XBookmarksTriggerSync(
        self,
        request: XBookmarksSyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksSyncResponse:
        """Trigger X bookmarks sync with Iceberg write and work queue population."""
        try:
            service = self._services.x_bookmarks_service
            if not service:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(
                    "XBookmarksService not initialized.\n"
                    "  Guru: #XB.00000001.SVCNOTINIT"
                )
                return XBookmarksSyncResponse(
                    started=False,
                    status="failed",
                    action_required="NOT_INITIALIZED",
                    guidance_message="Engine is starting. Wait for vLLM preload to complete.",
                )

            sync_run = await service.trigger_sync(
                user_id=request.user_id if request.user_id else None,
                full_sync=request.full_sync,  # Reset sync state and re-sync all folders
            )
            return XBookmarksSyncResponse(
                started=True,
                run_id=sync_run.run_id,
                status=sync_run.status,
                message=f"Sync {sync_run.status}: {sync_run.bookmarks_fetched} fetched, {sync_run.iceberg_written} to Iceberg, {sync_run.queue_items} queued",
                bookmarks_fetched=sync_run.bookmarks_fetched,
                iceberg_written=sync_run.iceberg_written,
                queue_items=sync_run.queue_items,
                action_required=sync_run.action_required or "",
                guidance_message=sync_run.guidance_message or "",
            )

        except Exception as e:
            logger.exception(f"XBookmarksTriggerSync failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksTriggerSync",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00005.SYNCFAIL",
            )
            # Check if it's an auth error
            error_str = str(e)
            action_required = ""
            guidance_message = ""
            if "expired" in error_str.lower() or "token" in error_str.lower():
                action_required = "TOKEN_EXPIRED"
                guidance_message = "Re-authenticate using /x-bookmarks auth to continue syncing."
            elif "authentication" in error_str.lower() or "oauth" in error_str.lower():
                action_required = "NOT_AUTHENTICATED"
                guidance_message = "Run /x-bookmarks auth to set up X API access."

            return XBookmarksSyncResponse(
                started=False,
                status="failed",
                message=str(e),
                action_required=action_required,
                guidance_message=guidance_message,
            )

    async def XBookmarksSyncStatus(
        self,
        request: XBookmarksSyncStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksSyncStatusResponse:
        """Get sync status and history."""
        try:
            service = self._services.x_bookmarks_service
            if not service:
                return XBookmarksSyncStatusResponse(
                    configured=False,
                    action_required="NOT_INITIALIZED",
                    guidance_message=(
                        "X Bookmarks service is still initializing. "
                        "Wait for engine startup to complete."
                    ),
                )

            status = await service.get_sync_status(
                user_id=request.user_id if request.user_id else None,
            )

            return XBookmarksSyncStatusResponse(
                configured=status.get("configured", False),
                user_id=status.get("user_id", ""),
                username=status.get("username", ""),
                token_status=status.get("token_status", "none"),
                folder_count=status.get("folder_count", 0),
                bookmark_count=status.get("bookmark_count", 0),
                queued_requests=status.get("queued_requests", 0),
                last_sync_at=status.get("last_sync_at", ""),
                last_run_status=status.get("last_run_status", ""),
                action_required=status.get("action_required", ""),
                guidance_message=status.get("message", ""),
            )

        except Exception as e:
            logger.exception(f"XBookmarksSyncStatus failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksSyncStatus",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00006.SYNCSTATUSFAIL",
            )
            return XBookmarksSyncStatusResponse(
                configured=False,
                action_required="ERROR",
                guidance_message="Check engine logs for details.",
            )

    async def XBookmarksServiceStatus(
        self,
        request: XBookmarksServiceStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksServiceStatusResponse:
        """Get overall X Bookmarks service status."""
        try:
            service = self._services.x_bookmarks_service
            if not service:
                return XBookmarksServiceStatusResponse(running=False)

            status = await service.get_service_status()

            return XBookmarksServiceStatusResponse(
                running=status.get("running", False),
                total_syncs=status.get("total_syncs", 0),
                total_bookmarks=status.get("total_bookmarks", 0),
                last_sync_at=status.get("last_sync_at", ""),
                queue_poll_interval_s=status.get("queue_poll_interval_s", 0),
            )

        except Exception as e:
            logger.exception(f"XBookmarksServiceStatus failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksServiceStatus",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00007.SVCSTATUSFAIL",
            )
            return XBookmarksServiceStatusResponse(running=False)

    async def XBookmarksListFolders(
        self,
        request: XBookmarksListFoldersRequest,
        context: grpc.aio.ServicerContext,
    ) -> XBookmarksListFoldersResponse:
        """List X bookmark folders."""
        try:
            service = self._services.x_bookmarks_service
            if service is None:
                return XBookmarksListFoldersResponse(
                    folders_available=False,
                    message="XBookmarksService not initialized",
                )

            # Check if folders are available
            folders_available = await service.check_folders_available()
            if not folders_available:
                return XBookmarksListFoldersResponse(
                    folders_available=False,
                    message="Bookmark folders not available for your API tier.\n"
                    "  Guru Meditation: #XB.00000011.NOFOLDER",
                )

            # Get folders from database
            user_id = request.user_id if request.user_id else None
            folders = await service.list_folders(user_id)

            return XBookmarksListFoldersResponse(
                folders=[
                    XBookmarkFolder(
                        id=f["id"],
                        name=f["name"],
                        kb_path=f["kb_path"],
                        bookmark_count=f["bookmark_count"],
                    )
                    for f in folders
                ],
                folders_available=True,
                message=f"{len(folders)} folders",
            )

        except Exception as e:
            logger.exception(f"XBookmarksListFolders failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksListFolders",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00008.LISTFOLDERSFAIL",
            )
            return XBookmarksListFoldersResponse(
                folders_available=False,
                message=str(e),
            )

    async def XBookmarksQueueStatus(
        self,
        request: XBookmarksQueueStatusRequest,
        context: aio.ServicerContext,
    ) -> XBookmarksQueueStatusResponse:
        """Get queue status and cooldown timer for InitPanel display."""
        service = self._services.x_bookmarks_service
        if service is None:
            logger.warning("XBookmarksQueueStatus: service is None")
            return XBookmarksQueueStatusResponse(
                queue_depth=0,
                can_request=False,
                cooldown_seconds=0,
            )

        try:
            status = await service.get_queue_status()
            logger.info(f"XBookmarksQueueStatus: got status={status}")
            return XBookmarksQueueStatusResponse(
                queue_depth=status.get("queue_depth", 0),
                cooldown_end_iso=status.get("cooldown_end_iso", ""),
                cooldown_seconds=status.get("cooldown_seconds", 0),
                can_request=status.get("can_request", False),
            )
        except Exception as e:
            logger.warning(f"XBookmarksQueueStatus error: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksQueueStatus",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00009.QUEUESTATUSFAIL",
            )
            return XBookmarksQueueStatusResponse(
                queue_depth=0,
                can_request=False,
            )

    async def XBookmarksEmitTestEvent(
        self,
        request: XBookmarksEmitTestEventRequest,
        context: aio.ServicerContext,
    ) -> XBookmarksEmitTestEventResponse:
        """Emit a test XB event for debugging the event propagation chain with OTel tracing.

        This endpoint allows firing simulated XB events to verify the complete flow
        from engine → InitController → InitStream → TUI InitPanel without requiring
        actual OAuth completion.
        """
        service = self._services.x_bookmarks_service
        if service is None:
            logger.warning("XBookmarksEmitTestEvent: service is None")
            return XBookmarksEmitTestEventResponse(
                success=False,
                message="X Bookmarks service not initialized",
            )

        try:
            event_type = request.event_type or "XB_AUTH_COMPLETED"
            result = await service.emit_test_event(event_type=event_type)
            logger.info(f"XBookmarksEmitTestEvent: emitted {event_type}, result={result}")
            return XBookmarksEmitTestEventResponse(
                success=result.get("success", False),
                event_type=result.get("event_type", event_type),
                message=f"Emitted test event: {event_type}",
            )
        except Exception as e:
            logger.warning(f"XBookmarksEmitTestEvent error: {e}")
            record_exception_caught(
                component="grpc",
                operation="XBookmarksEmitTestEvent",
                exception_type=type(e).__name__,
                guru_code="#GR.XB.00010.TESTEMITFAIL",
            )
            return XBookmarksEmitTestEventResponse(
                success=False,
                message=str(e),
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # Ambient Computing Workload
    # ═══════════════════════════════════════════════════════════════════════════

    async def AmbientCycle(
        self,
        request: AmbientCycleRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[AmbientPhaseEvent]:
        """Execute an ambient computing workload cycle with streaming progress.

        This streaming RPC executes a multi-phase workload cycle that:
        1. Verifies baseline endpoint health
        2. Runs standard tasks on each baseline endpoint
        3. (Optional) Evicts baseline endpoints for reasoning
        4. (Optional) Runs reasoning workload
        5. (Optional) Restores baseline endpoints

        Args:
            request: AmbientCycleRequest with skip_reasoning, baseline_task_count
            context: gRPC context

        Yields:
            AmbientPhaseEvent for each phase transition
        """
        service = self._services.ambient_service
        if service is None:
            logger.warning("AmbientCycle: service is None")
            yield AmbientPhaseEvent(
                phase=AMBIENT_PHASE_ERROR,
                message="AmbientWorkloadService not initialized.\n"
                "  Guru: #AMB.00000001.SVCNOTINIT\n"
                "  Check engine startup logs.",
                progress=0.0,
                timestamp_ms=int(time.time() * 1000),
            )
            return

        try:
            logger.info(
                f"AmbientCycle starting: skip_reasoning={request.skip_reasoning}, "
                f"baseline_task_count={request.baseline_task_count or 1}"
            )

            # Use _run_varied_cycle which includes all phases:
            # FETCH_CONTENT, BUFFER_ANALYSIS, SUMMARIZATION
            baseline_only = request.skip_reasoning
            async for event in service._run_varied_cycle(baseline_only):
                yield event

        except Exception as e:
            logger.exception(f"AmbientCycle failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="AmbientCycle",
                exception_type=type(e).__name__,
                guru_code="#GR.AMB.00001.CYCLEFAIL",
            )
            yield AmbientPhaseEvent(
                phase=AMBIENT_PHASE_ERROR,
                message=str(e),
                progress=0.0,
                timestamp_ms=int(time.time() * 1000),
            )

    async def AmbientStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> AmbientStatusResponse:
        """Get current ambient computing status.

        Returns cycle running state, last result, and configuration.
        """
        service = self._services.ambient_service
        if service is None:
            return AmbientStatusResponse(
                cycle_running=False,
                current_phase=AMBIENT_PHASE_UNSPECIFIED,
                cycles_completed=0,
            )

        try:
            status = service.get_status()

            # Build last_result if available
            last_result = None
            if status.get("last_result"):
                lr = status["last_result"]
                last_result = AmbientCycleResponse(
                    success=lr.get("success", False),
                    phases_completed=lr.get("phases_completed", 0),
                    total_tasks=lr.get("total_tasks", 0),
                    successful_tasks=lr.get("successful_tasks", 0),
                    error_message=lr.get("error_message", ""),
                    duration_ms=lr.get("duration_ms", 0),
                )
                for ep, lat in lr.get("endpoint_latencies", {}).items():
                    last_result.endpoint_latencies[ep] = lat

            # Map phase string to enum
            phase_map = {
                "baseline_health": AMBIENT_PHASE_BASELINE_HEALTH,
                "baseline_workload": AMBIENT_PHASE_BASELINE_WORKLOAD,
                "reasoning_eviction": AMBIENT_PHASE_REASONING_EVICTION,
                "reasoning_workload": AMBIENT_PHASE_REASONING_WORKLOAD,
                "baseline_restoration": AMBIENT_PHASE_BASELINE_RESTORATION,
                "complete": AMBIENT_PHASE_COMPLETE,
                "error": AMBIENT_PHASE_ERROR,
            }
            current_phase = phase_map.get(
                status.get("current_phase", "complete"),
                AMBIENT_PHASE_UNSPECIFIED,
            )

            # Convert daemon timestamps to ms since epoch
            def iso_to_ms(iso_str: str | None) -> int:
                if not iso_str:
                    return 0
                try:
                    return int(datetime.fromisoformat(iso_str).timestamp() * 1000)
                except Exception:
                    return 0

            response = AmbientStatusResponse(
                cycle_running=status.get("cycle_running", False),
                current_phase=current_phase,
                cycles_completed=status.get("cycles_completed", 0),
                last_cycle_timestamp_ms=(
                    int(datetime.fromisoformat(status["last_cycle_at"]).timestamp() * 1000)
                    if status.get("last_cycle_at")
                    else 0
                ),
                reasoning_endpoint=status.get("reasoning_endpoint", "reasoning"),
                # Daemon mode fields
                daemon_running=status.get("daemon_running", False),
                max_cycles=status.get("max_cycles") or 0,
                current_cycle=status.get("daemon_cycle", 0),
                daemon_started_at_ms=iso_to_ms(status.get("daemon_started_at")),
                daemon_stopped_at_ms=iso_to_ms(status.get("daemon_stopped_at")),
            )

            # Add baseline endpoints
            for ep in status.get("baseline_endpoints", []):
                response.baseline_endpoints.append(ep)

            if last_result:
                response.last_result.CopyFrom(last_result)

            return response

        except Exception as e:
            logger.exception(f"AmbientStatus failed: {e}")
            return AmbientStatusResponse(
                cycle_running=False,
                current_phase=AMBIENT_PHASE_ERROR,
            )

    async def AmbientStart(
        self,
        request: AmbientStartRequest,
        context: aio.ServicerContext,
    ) -> AmbientStartResponse:
        """Start continuous ambient cycling daemon.

        Returns immediately. Events can be consumed via AmbientSubscribe.

        Args:
            request: AmbientStartRequest with baseline_only and max_cycles
            context: gRPC context

        Returns:
            AmbientStartResponse with success status
        """
        service = self._services.ambient_service
        if service is None:
            return AmbientStartResponse(
                success=False,
                message="AmbientWorkloadService not initialized.\n"
                "  Guru: #AMB.00000001.SVCNOTINIT\n"
                "  Check engine startup logs.",
            )

        try:
            max_cycles = request.max_cycles if request.max_cycles > 0 else None
            result = await service.start_daemon(
                baseline_only=request.baseline_only,
                max_cycles=max_cycles,
            )

            return AmbientStartResponse(
                success=result["success"],
                message=result["message"],
                max_cycles=result.get("max_cycles") or 0,
            )

        except Exception as e:
            logger.exception(f"AmbientStart failed: {e}")
            return AmbientStartResponse(
                success=False,
                message=str(e),
            )

    async def AmbientStop(
        self,
        request: AmbientStopRequest,
        context: aio.ServicerContext,
    ) -> AmbientStopResponse:
        """Stop ambient cycling daemon gracefully.

        Returns summary of cycles completed.

        Args:
            request: AmbientStopRequest (empty)
            context: gRPC context

        Returns:
            AmbientStopResponse with cycle count and summary
        """
        service = self._services.ambient_service
        if service is None:
            return AmbientStopResponse(
                success=False,
                message="AmbientWorkloadService not initialized.",
                cycles_completed=0,
            )

        try:
            result = await service.stop_daemon()

            return AmbientStopResponse(
                success=result["success"],
                message=result["message"],
                cycles_completed=result.get("cycles_completed", 0),
            )

        except Exception as e:
            logger.exception(f"AmbientStop failed: {e}")
            return AmbientStopResponse(
                success=False,
                message=str(e),
                cycles_completed=0,
            )

    async def AmbientSubscribe(
        self,
        request: AmbientSubscribeRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[AmbientPhaseEvent]:
        """Subscribe to ambient events stream.

        Streams events from the running daemon to the caller.
        Used by TUI InfoPanel to display progress.

        Args:
            request: AmbientSubscribeRequest (empty)
            context: gRPC context

        Yields:
            AmbientPhaseEvent for each phase transition
        """
        service = self._services.ambient_service
        if service is None:
            yield AmbientPhaseEvent(
                phase=AMBIENT_PHASE_ERROR,
                message="AmbientWorkloadService not initialized.",
                progress=0.0,
                timestamp_ms=int(time.time() * 1000),
            )
            return

        try:
            async for event in service.subscribe_events():
                yield event

        except Exception as e:
            logger.exception(f"AmbientSubscribe failed: {e}")
            yield AmbientPhaseEvent(
                phase=AMBIENT_PHASE_ERROR,
                message=str(e),
                progress=0.0,
                timestamp_ms=int(time.time() * 1000),
            )

    async def AmbientBufferExport(
        self,
        request: AmbientBufferExportRequest,
        context: aio.ServicerContext,
    ) -> AmbientBufferExportResponse:
        """Export ambient buffer to zettelkasten file.

        Creates a markdown file at scratch/{date}/{HHMMSS}_buffer.md
        containing all current buffer entries grouped by role.

        Args:
            request: AmbientBufferExportRequest with optional kb_root
            context: gRPC context

        Returns:
            AmbientBufferExportResponse with path or error
        """
        service = self._services.ambient_service
        if service is None:
            return AmbientBufferExportResponse(
                error="AmbientWorkloadService not initialized."
            )

        try:
            kb_root = request.kb_root or "build/dev"
            result = await service.export_buffer(kb_root)

            return AmbientBufferExportResponse(
                path=result.get("path", ""),
                entry_count=result.get("entry_count", 0),
                total_bytes=result.get("total_bytes", 0),
                error=result.get("error", ""),
            )
        except Exception as e:
            logger.exception(f"AmbientBufferExport failed: {e}")
            return AmbientBufferExportResponse(error=str(e))

    # =========================================================================
    # HuggingFace Dataset Discovery
    # =========================================================================

    async def ListHFDatasets(
        self,
        request: ListHFDatasetsRequest,
        context: aio.ServicerContext,
    ) -> ListHFDatasetsResponse:
        """List recent datasets from HuggingFace Hub with rich content.

        Uses two-phase fetch with Iceberg caching:
        1. Fetch larger batch from HF API
        2. Check Iceberg cache for README content
        3. Fetch README for uncached items via DatasetCard
        4. Return top N with richest content (README > 100 chars)
        """
        from pathlib import Path
        from datetime import datetime

        try:
            from ....hx import get_hf_capture

            limit = request.limit if request.limit > 0 else 5  # Default to 5 for rich content
            capture = get_hf_capture()

            # Use two-phase fetch with Iceberg caching
            rich_datasets = await capture.get_rich_datasets(
                limit=limit,
                fetch_batch=50,  # Fetch more to find ones with README
                min_readme_length=100,
            )

            if not rich_datasets:
                return ListHFDatasetsResponse(
                    count=0,
                    error="No datasets with rich README content found",
                )

            # Generate zettelkasten note with README content
            today = datetime.now().strftime("%Y-%m-%d")
            lines = [
                f"# HuggingFace Dataset Discovery - {today}",
                "",
                f"*{len(rich_datasets)} datasets with informative README content*",
                "",
            ]

            for ds in rich_datasets:
                ds_id = ds.get("dataset_id", "unknown")
                author = ds.get("author", "")
                downloads = ds.get("downloads", 0)
                likes = ds.get("likes", 0)
                readme = ds.get("readme_content", "")
                tags = ds.get("tags", [])

                lines.append(f"## {ds_id}")
                lines.append("")
                if author:
                    lines.append(f"**Author:** {author}")
                lines.append(f"**Downloads:** {downloads:,} | **Likes:** {likes}")
                if tags:
                    display_tags = [t for t in tags[:5] if not t.startswith("region:")]
                    if display_tags:
                        lines.append(f"**Tags:** {', '.join(display_tags)}")
                lines.append("")

                # Include README excerpt
                if readme:
                    excerpt = readme[:500] + ("..." if len(readme) > 500 else "")
                    lines.append(excerpt)
                    lines.append("")

                # Action links
                lines.append(f"- [action:/datasets info {ds_id}]")
                lines.append(f"- [action:/datasets add {ds_id}]")
                lines.append("")

            content = "\n".join(lines)

            # Save to scratch directory
            kb_root = Path("build/dev")
            scratch_dir = kb_root / "scratch" / today
            scratch_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{timestamp}_hf_datasets.md"
            file_path = scratch_dir / filename
            file_path.write_text(content)

            # Build response with README as description
            hf_datasets = []
            for ds in rich_datasets:
                readme = ds.get("readme_content", "")
                # Extract dates with proper None handling
                created_at = ds.get("created_at")
                last_modified = ds.get("last_modified")
                hf_datasets.append(HFDatasetInfo(
                    id=ds.get("dataset_id", ""),
                    author=ds.get("author", ""),
                    description=readme[:500] if readme else "",
                    downloads=ds.get("downloads", 0),
                    likes=ds.get("likes", 0),
                    private=ds.get("private", False),
                    created_at=created_at.isoformat() if created_at else "",
                    last_modified=last_modified.isoformat() if last_modified else "",
                    tags=ds.get("tags", [])[:10],
                ))

            return ListHFDatasetsResponse(
                datasets=hf_datasets,
                count=len(rich_datasets),
                saved_to=str(file_path.relative_to(kb_root)),
            )

        except Exception as e:
            logger.exception(f"ListHFDatasets failed: {e}")
            return ListHFDatasetsResponse(error=str(e))

    async def AddExternalDataset(
        self,
        request: AddExternalDatasetRequest,
        context: aio.ServicerContext,
    ) -> AddExternalDatasetResponse:
        """Add an external HuggingFace dataset to the KB registry."""
        from pathlib import Path

        try:
            from ....integrations import get_dataset_info

            dataset_id = request.dataset_id
            notes = request.notes or ""

            info = get_dataset_info(dataset_id)

            # Determine path: current/datasets/external/<org>/<name>.md
            if "/" in dataset_id:
                org, name = dataset_id.split("/", 1)
            else:
                org = "community"
                name = dataset_id

            kb_root = Path("build/dev")
            external_dir = kb_root / "current" / "datasets" / "external" / org
            external_dir.mkdir(parents=True, exist_ok=True)

            file_path = external_dir / f"{name}.md"

            if file_path.exists():
                return AddExternalDatasetResponse(
                    success=False,
                    dataset_id=dataset_id,
                    error=f"Dataset already exists in KB: {file_path.relative_to(kb_root)}",
                )

            # Generate KB entry
            content = info.to_kb_entry(notes=notes)
            file_path.write_text(content)

            return AddExternalDatasetResponse(
                success=True,
                dataset_id=dataset_id,
                saved_to=str(file_path.relative_to(kb_root)),
                downloads=info.downloads,
                likes=info.likes,
                description=info.description[:200] if info.description else "",
            )

        except Exception as e:
            logger.exception(f"AddExternalDataset failed: {e}")
            return AddExternalDatasetResponse(
                success=False,
                dataset_id=request.dataset_id,
                error=str(e),
            )

    async def GetHFDatasetInfo(
        self,
        request: GetHFDatasetInfoRequest,
        context: aio.ServicerContext,
    ) -> GetHFDatasetInfoResponse:
        """Get detailed info for a specific HuggingFace dataset."""
        try:
            from ....integrations import get_dataset_info

            info = get_dataset_info(request.dataset_id)

            return GetHFDatasetInfoResponse(
                info=HFDatasetInfo(
                    id=info.id,
                    author=info.author,
                    description=info.description,
                    downloads=info.downloads,
                    likes=info.likes,
                    private=info.private,
                    created_at=info.created_at.isoformat() if info.created_at else "",
                    last_modified=info.last_modified.isoformat() if info.last_modified else "",
                    tags=info.tags,
                ),
                url=f"https://huggingface.co/datasets/{info.id}",
            )

        except Exception as e:
            logger.exception(f"GetHFDatasetInfo failed: {e}")
            return GetHFDatasetInfoResponse(error=str(e))

    async def ListKBDatasets(
        self,
        request: ListKBDatasetsRequest,
        context: aio.ServicerContext,
    ) -> ListKBDatasetsResponse:
        """List known datasets in the KB (internal + external)."""
        from pathlib import Path

        kb_root = Path("build/dev")
        datasets_dir = kb_root / "current" / "datasets"

        internal = []
        external = []

        # Scan internal datasets
        internal_dir = datasets_dir / "internal"
        if internal_dir.exists():
            for item in internal_dir.iterdir():
                # Skip README.md and other metadata files
                if item.name.upper() == "README.MD":
                    continue
                if item.is_dir() or (item.is_file() and item.suffix == ".md"):
                    internal.append(KBDatasetEntry(
                        id=item.stem if item.is_file() else item.name,
                        type="internal",
                        path=str(item.relative_to(kb_root)),
                    ))

        # Scan external datasets
        external_dir = datasets_dir / "external"
        if external_dir.exists():
            for org_dir in external_dir.iterdir():
                if org_dir.is_dir():
                    for ds_file in org_dir.glob("*.md"):
                        external.append(KBDatasetEntry(
                            id=f"{org_dir.name}/{ds_file.stem}",
                            type="external",
                            path=str(ds_file.relative_to(kb_root)),
                        ))

        return ListKBDatasetsResponse(
            internal=internal,
            external=external,
            internal_count=len(internal),
            external_count=len(external),
        )

    # =========================================================================
    # HuggingFace Model Discovery
    # =========================================================================

    async def ListHFModels(
        self,
        request: ListHFModelsRequest,
        context: aio.ServicerContext,
    ) -> ListHFModelsResponse:
        """List recent models from HuggingFace Hub with rich content.

        Uses two-phase fetch with Iceberg caching:
        1. Fetch larger batch from HF API
        2. Check Iceberg cache for README content
        3. Fetch README for uncached items via ModelCard
        4. Return top N with richest content (README > 100 chars)
        """
        from datetime import datetime
        from pathlib import Path

        try:
            from ....hx import get_hf_capture

            limit = request.limit if request.limit > 0 else 5  # Default to 5 for rich content
            filter_tag = request.filter if request.filter else None
            capture = get_hf_capture()

            # Use two-phase fetch with Iceberg caching
            rich_models = await capture.get_rich_models(
                limit=limit,
                fetch_batch=50,  # Fetch more to find ones with README
                min_readme_length=100,
                filter_tag=filter_tag,
            )

            if not rich_models:
                return ListHFModelsResponse(
                    count=0,
                    error="No models with rich README content found",
                )

            # Generate zettelkasten note with README content
            today = datetime.now().strftime("%Y-%m-%d")
            lines = [
                f"# HuggingFace Model Discovery - {today}",
                "",
                f"*{len(rich_models)} models with informative README content*",
                "",
            ]

            for m in rich_models:
                m_id = m.get("model_id", "unknown")
                author = m.get("author", "")
                pipeline = m.get("pipeline_tag", "")
                library = m.get("library_name", "")
                downloads = m.get("downloads", 0)
                likes = m.get("likes", 0)
                readme = m.get("readme_content", "")
                tags = m.get("tags", [])

                lines.append(f"## {m_id}")
                lines.append("")
                if author:
                    lines.append(f"**Author:** {author}")
                lines.append(f"**Downloads:** {downloads:,} | **Likes:** {likes}")
                if pipeline:
                    lines.append(f"**Pipeline:** {pipeline}")
                if library:
                    lines.append(f"**Library:** {library}")
                if tags:
                    display_tags = [t for t in tags[:5] if not t.startswith("region:") and not t.startswith("license:")]
                    if display_tags:
                        lines.append(f"**Tags:** {', '.join(display_tags)}")
                lines.append("")

                # Include README excerpt
                if readme:
                    excerpt = readme[:500] + ("..." if len(readme) > 500 else "")
                    lines.append(excerpt)
                    lines.append("")

                # Action links
                lines.append(f"- [action:/models info {m_id}]")
                lines.append(f"- [action:/models add {m_id}]")
                lines.append("")

            content = "\n".join(lines)

            # Save to scratch directory
            kb_root = Path("build/dev")
            scratch_dir = kb_root / "scratch" / today
            scratch_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{timestamp}_hf_models.md"
            file_path = scratch_dir / filename
            file_path.write_text(content)

            # Build response with README as description
            model_infos = []
            for m in rich_models:
                readme = m.get("readme_content", "")
                # Extract dates with proper None handling
                created_at = m.get("created_at")
                last_modified = m.get("last_modified")
                model_infos.append(HFModelInfo(
                    id=m.get("model_id", ""),
                    author=m.get("author", ""),
                    pipeline_tag=m.get("pipeline_tag", ""),
                    downloads=m.get("downloads", 0),
                    likes=m.get("likes", 0),
                    private=m.get("private", False),
                    created_at=created_at.isoformat() if created_at else "",
                    last_modified=last_modified.isoformat() if last_modified else "",
                    tags=m.get("tags", [])[:10],
                    gated=m.get("gated", False),
                    library_name=m.get("library_name", ""),
                ))

            return ListHFModelsResponse(
                models=model_infos,
                count=len(rich_models),
                saved_to=str(file_path.relative_to(kb_root)),
            )

        except Exception as e:
            logger.exception(f"ListHFModels failed: {e}")
            return ListHFModelsResponse(error=str(e))

    async def AddExternalModel(
        self,
        request: AddExternalModelRequest,
        context: aio.ServicerContext,
    ) -> AddExternalModelResponse:
        """Add an external model reference to KB."""
        from pathlib import Path

        try:
            from huggingface_hub import model_info

            model_id = request.model_id
            notes = request.notes

            # Fetch model info
            info = model_info(model_id)

            # Determine path: current/models/external/<org>/<name>.md
            if "/" in model_id:
                org, name = model_id.split("/", 1)
            else:
                org = "community"
                name = model_id

            kb_root = Path("build/dev")
            external_dir = kb_root / "current" / "models" / "external" / org
            external_dir.mkdir(parents=True, exist_ok=True)

            file_path = external_dir / f"{name}.md"

            # Check if already exists
            if file_path.exists():
                return AddExternalModelResponse(
                    success=False,
                    model_id=model_id,
                    error=f"Model already exists in KB: {file_path.relative_to(kb_root)}",
                )

            # Generate KB entry
            content = f"""# {model_id}

**URL**: https://huggingface.co/{model_id}
**Pipeline**: {info.pipeline_tag or 'N/A'}
**Library**: {info.library_name or 'N/A'}
**Downloads**: {info.downloads or 0:,}
**Likes**: {info.likes or 0}
**Gated**: {'Yes' if info.gated else 'No'}

## Tags
{', '.join(info.tags) if info.tags else 'None'}

## Notes
{notes if notes else 'No notes provided.'}

---
*Added to KB on {Path(file_path).stat().st_mtime if file_path.exists() else 'now'}*
"""
            file_path.write_text(content)

            return AddExternalModelResponse(
                success=True,
                model_id=model_id,
                saved_to=str(file_path.relative_to(kb_root)),
                downloads=info.downloads or 0,
                likes=info.likes or 0,
                pipeline_tag=info.pipeline_tag or "",
            )

        except Exception as e:
            logger.exception(f"AddExternalModel failed: {e}")
            return AddExternalModelResponse(error=str(e))

    async def GetHFModelInfo(
        self,
        request: GetHFModelInfoRequest,
        context: aio.ServicerContext,
    ) -> GetHFModelInfoResponse:
        """Get detailed info for a specific HuggingFace model."""
        try:
            from huggingface_hub import model_info

            info = model_info(request.model_id)

            return GetHFModelInfoResponse(
                info=HFModelInfo(
                    id=info.id,
                    author=info.author or "",
                    pipeline_tag=info.pipeline_tag or "",
                    downloads=info.downloads or 0,
                    likes=info.likes or 0,
                    private=info.private or False,
                    created_at=info.created_at.isoformat() if info.created_at else "",
                    last_modified=info.last_modified.isoformat() if info.last_modified else "",
                    tags=list(info.tags) if info.tags else [],
                    gated=bool(info.gated) if hasattr(info, 'gated') else False,
                    library_name=info.library_name or "",
                ),
                url=f"https://huggingface.co/{info.id}",
            )

        except Exception as e:
            logger.exception(f"GetHFModelInfo failed: {e}")
            return GetHFModelInfoResponse(error=str(e))

    async def ListKBModels(
        self,
        request: ListKBModelsRequest,
        context: aio.ServicerContext,
    ) -> ListKBModelsResponse:
        """List known models in the KB (internal = cached, external = references)."""
        from pathlib import Path
        import os

        kb_root = Path("build/dev")
        models_dir = kb_root / "current" / "models"
        hf_cache = Path(os.environ.get("HF_HOME", "/raid/cache/huggingface")) / "hub"

        internal = []
        external = []
        total_cache_bytes = 0

        # Scan HuggingFace cache for internal (cached) models
        if hf_cache.exists():
            for item in hf_cache.iterdir():
                if item.is_dir() and item.name.startswith("models--"):
                    # Parse model ID from cache dir name: models--org--name -> org/name
                    parts = item.name.replace("models--", "").split("--")
                    if len(parts) >= 2:
                        model_id = f"{parts[0]}/{parts[1]}"
                    else:
                        model_id = parts[0]

                    # Calculate size
                    size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    total_cache_bytes += size

                    internal.append(KBModelEntry(
                        id=model_id,
                        type="internal",
                        path=str(item),
                        size_bytes=size,
                    ))

        # Scan external model references in KB
        external_dir = models_dir / "external"
        if external_dir.exists():
            for org_dir in external_dir.iterdir():
                if org_dir.is_dir():
                    for model_file in org_dir.glob("*.md"):
                        external.append(KBModelEntry(
                            id=f"{org_dir.name}/{model_file.stem}",
                            type="external",
                            path=str(model_file.relative_to(kb_root)),
                        ))

        return ListKBModelsResponse(
            internal=internal,
            external=external,
            internal_count=len(internal),
            external_count=len(external),
            total_cache_bytes=total_cache_bytes,
        )

    # =========================================================================
    # Prospects / Stewardship
    # =========================================================================

    async def ProspectsStatus(
        self,
        request: ProspectsStatusRequest,
        context: aio.ServicerContext,
    ) -> ProspectsStatusResponse:
        """Get lightweight prospects status (no LLM calls, cached data)."""
        try:
            service = self._services.prospects_service
            if not service:
                # Service not yet initialized - return empty but valid response
                return ProspectsStatusResponse(
                    success=True,
                    profile=request.profile or "zndx",
                    domain=request.domain or "prospecting",
                    update_recommended=False,
                    update_reason="Prospects service initializing",
                )

            status = await service.get_status(
                profile=request.profile,
                domain=request.domain,
                symbols=list(request.symbols) if request.symbols else None,
            )

            # Convert to proto candidates
            candidates = []
            for c in status.get("candidates", []):
                candidates.append(CandidateSummary(
                    symbol=c.get("symbol", ""),
                    company_name=c.get("company_name", ""),
                    exchange=c.get("exchange", ""),
                    cik=c.get("cik", ""),
                    last_filing_date=c.get("last_filing_date", ""),
                    last_filing_type=c.get("last_filing_type", ""),
                    pending_filings=c.get("pending_filings", 0),
                ))

            # Convert to proto strategies
            strategies = []
            for s in status.get("strategies", []):
                strategies.append(StrategySummary(
                    symbol=s.get("symbol", ""),
                    category=s.get("category", ""),
                    allocation_weight=s.get("allocation_weight", 0.0),
                    target_weight=s.get("target_weight", 0.0),
                    conviction=s.get("conviction", 0.0),
                    last_analysis_at=s.get("last_analysis_at", ""),
                    needs_update=s.get("needs_update", False),
                ))

            buf = status.get("buffer") or {}
            return ProspectsStatusResponse(
                success=True,
                profile=status.get("profile", request.profile or "zndx"),
                domain=status.get("domain", request.domain or "prospecting"),
                candidates=candidates,
                strategies=strategies,
                pending_filings=status.get("pending_filings", 0),
                last_fmp_sync_at=status.get("last_fmp_sync_at", ""),
                update_recommended=status.get("update_recommended", False),
                update_reason=status.get("update_reason", ""),
                buffer_bytes=int(buf.get("current_bytes", 0)),
                buffer_max_bytes=int(buf.get("max_bytes", 0)),
                buffer_entries=int(buf.get("entry_count", 0)),
            )

        except Exception as e:
            logger.exception(f"ProspectsStatus failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="ProspectsStatus",
                exception_type=type(e).__name__,
                guru_code="#GR.PS.00001.STATUSFAIL",
            )
            return ProspectsStatusResponse(
                success=False,
                error=str(e),
            )

    async def ProspectsCheck(
        self,
        request: ProspectsCheckRequest,
        context: aio.ServicerContext,
    ) -> ProspectsCheckResponse:
        """Run daily check for new SEC filings (local LLM only, $0 cost)."""
        try:
            service = self._services.prospects_service
            if not service:
                return ProspectsCheckResponse(
                    success=False,
                    error="Prospects service not initialized",
                )

            start_time = time.time()

            result = await service.run_check(
                profile=request.profile,
                domain=request.domain,
                force=request.force,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            return ProspectsCheckResponse(
                success=True,
                update_recommended=result.get("update_recommended", False),
                reason=result.get("reason", ""),
                new_filings_count=result.get("new_filings_count", 0),
                symbols_with_new_filings=result.get("symbols_with_new_filings", []),
                checked_at=datetime.now(timezone.utc).isoformat(),
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"ProspectsCheck failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="ProspectsCheck",
                exception_type=type(e).__name__,
                guru_code="#GR.PS.00002.CHECKFAIL",
            )
            return ProspectsCheckResponse(
                success=False,
                error=str(e),
            )

    async def ProspectsUpdate(
        self,
        request: ProspectsUpdateRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[ProspectsUpdateEvent]:
        """Run full billable analysis (streaming progress events).

        Cost model:
        - ~$0.06/filing (Cerebras GLM 4.7 analysis)
        - ~$0.50/synthesis (XAI Grok)
        """
        try:
            # Emit queued event
            yield ProspectsUpdateEvent(
                type=ProspectsUpdateEvent.QUEUED,
                timestamp_ms=int(time.time() * 1000),
                progress=0.0,
                message="Update queued",
            )

            service = self._services.prospects_service
            if not service:
                yield ProspectsUpdateEvent(
                    type=ProspectsUpdateEvent.FAILED,
                    timestamp_ms=int(time.time() * 1000),
                    progress=0.0,
                    message="Prospects service not initialized",
                )
                return

            # Stream progress events from service
            sitrep_path = ""
            last_type: int | None = None
            async for event in service.run_update(
                profile=request.profile,
                domain=request.domain,
                symbols=list(request.symbols) if request.symbols else None,
                force=request.force,
                filings_per_symbol=request.filings_per_symbol if request.filings_per_symbol > 0 else None,
            ):
                # Track sitrep_path from events
                if "sitrep_path" in event and event["sitrep_path"]:
                    sitrep_path = event["sitrep_path"]

                last_type = int(event.get("type", ProspectsUpdateEvent.QUEUED))
                yield ProspectsUpdateEvent(
                    type=last_type,
                    timestamp_ms=int(time.time() * 1000),
                    progress=event.get("progress", 0.0),
                    message=event.get("message", ""),
                    symbol=event.get("symbol", ""),
                    filing_type=event.get("filing_type", ""),
                    sitrep_path=event.get("sitrep_path", ""),
                )

            if last_type != ProspectsUpdateEvent.FAILED:
                yield ProspectsUpdateEvent(
                    type=ProspectsUpdateEvent.COMPLETED,
                    timestamp_ms=int(time.time() * 1000),
                    progress=1.0,
                    message="Update completed",
                    sitrep_path=sitrep_path,
                )

        except Exception as e:
            logger.exception(f"ProspectsUpdate failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="ProspectsUpdate",
                exception_type=type(e).__name__,
                guru_code="#GR.PS.00003.UPDATEFAIL",
            )
            yield ProspectsUpdateEvent(
                type=ProspectsUpdateEvent.FAILED,
                timestamp_ms=int(time.time() * 1000),
                progress=0.0,
                message=str(e),
            )

    # =========================================================================
    # Search (Multi-Phase Metaflow Search Flow)
    # =========================================================================

    async def SearchFlowStream(
        self,
        request: SearchFlowRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[SearchFlowEvent]:
        """Run multi-phase search via Metaflow SearchFlow (streaming progress events).

        Phases:
        1. BM25 lexical search (KB)
        2. Vector search (ColBERT-Zero MaxSim - evicts thinking)
        3. Web search (Brave API)
        4. Ensure thinking endpoint restored
        5. Parallel synthesis (local + Grok branch/join)
        6. Merge results and write KB zettelkasten
        """
        try:
            # Emit queued event
            yield SearchFlowEvent(
                type=SearchFlowEvent.QUEUED,
                timestamp_ms=int(time.time() * 1000),
                progress=0.0,
                message=f"Search queued: {request.query}",
            )

            # Lazy import to avoid circular dependencies
            from ...services.search_workload_service import SearchWorkloadService

            # Create service instance (stateless - no need for long-lived service)
            service = SearchWorkloadService()
            await service.start()

            try:
                # Stream progress events from service
                async for event in service.run_search(
                    query=request.query,
                    skip_grok=request.skip_grok,
                    bm25_limit=request.bm25_limit if request.bm25_limit > 0 else None,
                    vector_limit=request.vector_limit if request.vector_limit > 0 else None,
                    web_limit=request.web_limit if request.web_limit > 0 else None,
                ):
                    # Map event type to proto enum
                    event_type = event.get("type", 0)

                    # Build SearchFlowEvent - include result for COMPLETED events
                    flow_event = SearchFlowEvent(
                        type=event_type,
                        timestamp_ms=event.get("timestamp_ms", int(time.time() * 1000)),
                        progress=event.get("progress", 0.0),
                        message=event.get("message", ""),
                        error=event.get("error", ""),
                        guru_code=event.get("guru_code", ""),
                    )

                    # Include result with kb_path for COMPLETED events
                    kb_path = event.get("kb_path", "")
                    if event_type == SearchFlowEvent.COMPLETED and kb_path:
                        flow_event.result.CopyFrom(SearchFlowResult(kb_path=kb_path))

                    yield flow_event

            finally:
                await service.stop()

        except Exception as e:
            logger.exception(f"SearchFlowStream failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="SearchFlowStream",
                exception_type=type(e).__name__,
                guru_code="#GR.SF.00001.STREAMFAIL",
            )
            yield SearchFlowEvent(
                type=SearchFlowEvent.FAILED,
                timestamp_ms=int(time.time() * 1000),
                progress=0.0,
                message=str(e),
                guru_code="#SF.00000007.FLOWFAIL",
            )

    # =========================================================================
    # Research (Multi-Pass Deep Research Flow with MemRL)
    # =========================================================================

    async def ResearchFlowStream(
        self,
        request: ResearchFlowRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[ResearchFlowEvent]:
        """Run multi-pass deep research via Metaflow ResearchFlow (streaming progress events).

        Implements MemRL pattern:
        1. Retrieve episodic memories from KB (Q-value weighted)
        2. Multi-pass research cycle:
           - Search (BM25 + vector + web)
           - 7-agent swarm analysis
           - Grok synthesis
           - Reward computation (coherence/coverage/novelty)
           - Q-value update via Bellman EMA
        3. Convergence detection (drift threshold or max passes)
        4. Final Grok synthesis for polished output
        5. Write to KB with MemRL frontmatter
        """
        try:
            # Emit queued event
            yield ResearchFlowEvent(
                type=ResearchFlowEvent.QUEUED,
                timestamp_ms=int(time.time() * 1000),
                progress=0.0,
                message=f"Research queued: {request.query}",
            )

            # Lazy import to avoid circular dependencies
            from ...services.research_workload_service import ResearchWorkloadService

            # Create and cache service instance for status/stop operations
            service = ResearchWorkloadService()
            self._research_service = service
            await service.start()

            try:
                # Stream progress events from service
                async for event in service.run_research(
                    query=request.query,
                    max_passes=request.max_passes if request.max_passes > 0 else None,
                    drift_threshold=request.drift_threshold if request.drift_threshold > 0 else None,
                    bm25_limit=request.bm25_limit if request.bm25_limit > 0 else None,
                    vector_limit=request.vector_limit if request.vector_limit > 0 else None,
                    web_limit=request.web_limit if request.web_limit > 0 else None,
                ):
                    # Map event type to proto enum
                    event_type = event.get("type", 0)
                    type_name = event.get("type_name", "")

                    # Build ResearchFlowEvent
                    flow_event = ResearchFlowEvent(
                        type=event_type,
                        timestamp_ms=event.get("timestamp_ms", int(time.time() * 1000)),
                        progress=event.get("progress", 0.0),
                        message=event.get("message", ""),
                        error=event.get("error", ""),
                        guru_code=event.get("guru_code", ""),
                        pass_number=event.get("pass_number", 0),
                    )

                    # Include result for COMPLETED events
                    kb_path = event.get("kb_path", "")
                    best_q_value = event.get("best_q_value", 0.0)
                    total_passes = event.get("total_passes", 0)
                    convergence_reason = event.get("convergence_reason", "")

                    if type_name == "completed" and kb_path:
                        flow_event.result.CopyFrom(ResearchFlowResult(
                            kb_path=kb_path,
                            best_q_value=best_q_value,
                            total_passes=total_passes,
                            convergence_reason=convergence_reason,
                        ))

                    yield flow_event

            finally:
                await service.stop()

        except Exception as e:
            logger.exception(f"ResearchFlowStream failed: {e}")
            record_exception_caught(
                component="grpc",
                operation="ResearchFlowStream",
                exception_type=type(e).__name__,
                guru_code="#GR.RF.00001.STREAMFAIL",
            )
            yield ResearchFlowEvent(
                type=ResearchFlowEvent.FAILED,
                timestamp_ms=int(time.time() * 1000),
                progress=0.0,
                message=str(e),
                guru_code="#RF.00000007.FLOWFAIL",
            )

    async def ResearchFlowStatus(
        self,
        request: empty_pb2.Empty,
        context: grpc.aio.ServicerContext,
    ) -> ResearchFlowStatusResponse:
        """Get current research status for /research status command."""
        if self._research_service is None:
            # No research has been started yet
            return ResearchFlowStatusResponse(
                running=False,
                query="",
                pass_number=0,
                progress=0.0,
                phase="",
                elapsed_s=0.0,
                events_count=0,
                stop_requested=False,
            )

        status = await self._research_service.get_status()
        return ResearchFlowStatusResponse(
            running=status.get("running", False),
            query=status.get("query", ""),
            pass_number=status.get("pass", 0),
            progress=float(status.get("progress", 0.0)),
            phase=status.get("phase", ""),
            elapsed_s=float(status.get("elapsed_s", 0.0)),
            events_count=status.get("events_count", 0),
            stop_requested=status.get("stop_requested", False),
        )

    async def ResearchFlowStop(
        self,
        request: empty_pb2.Empty,
        context: grpc.aio.ServicerContext,
    ) -> ResearchFlowStopResponse:
        """Request stop of running research for /research stop command."""
        if self._research_service is None:
            return ResearchFlowStopResponse(
                success=False,
                message="",
                error="No research running",
            )

        result = await self._research_service.request_stop()
        if result.get("success", False):
            return ResearchFlowStopResponse(
                success=True,
                message=result.get("message", "Stop requested"),
                error="",
            )
        else:
            return ResearchFlowStopResponse(
                success=False,
                message="",
                error=result.get("error", "Unknown error"),
            )

    # =========================================================================
    # MetaAgent Service (Sync, Audit, Budget)
    # =========================================================================

    async def MetaAgentStatus(
        self,
        request: MetaAgentStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> MetaAgentStatusResponse:
        """Get MetaAgent service status including sync and budget info."""
        service = self._services.metaagent_service
        if service is None:
            return MetaAgentStatusResponse(
                running=False,
                metabase_connected=False,
                error="MetaAgent service not initialized",
            )

        try:
            status = await service.get_status()
            return status
        except Exception as e:
            logger.error(f"MetaAgentStatus error: {e}")
            return MetaAgentStatusResponse(
                running=False,
                metabase_connected=False,
                error=str(e),
            )

    async def MetabaseSyncTrigger(
        self,
        request: MetabaseSyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> MetabaseSyncResponse:
        """Trigger Metabase model sync."""
        service = self._services.metaagent_service
        if service is None:
            return MetabaseSyncResponse(
                success=False,
                error="MetaAgent service not initialized",
            )

        try:
            result = await service.trigger_sync(full_refresh=request.full_refresh)
            return result
        except Exception as e:
            logger.error(f"MetabaseSyncTrigger error: {e}")
            return MetabaseSyncResponse(
                success=False,
                error=str(e),
            )

    async def MetaAgentAuditTrigger(
        self,
        request: MetaAgentAuditRequest,
        context: grpc.aio.ServicerContext,
    ) -> MetaAgentAuditResponse:
        """Trigger a MetaAgent audit with optional remote LLM."""
        service = self._services.metaagent_service
        if service is None:
            return MetaAgentAuditResponse(
                success=False,
                error="MetaAgent service not initialized",
            )

        try:
            result = await service.trigger_audit(
                scope=request.scope or "full",
                use_remote_llm=request.use_remote_llm,
            )
            return result
        except Exception as e:
            logger.error(f"MetaAgentAuditTrigger error: {e}")
            return MetaAgentAuditResponse(
                success=False,
                error=str(e),
            )

    async def GetPooledBudget(
        self,
        request: GetPooledBudgetRequest,
        context: grpc.aio.ServicerContext,
    ) -> GetPooledBudgetResponse:
        """Get current pooled budget status."""
        service = self._services.metaagent_service
        if service is None:
            return GetPooledBudgetResponse(
                budget=PooledBudgetStatus(
                    weekly_limit=0,
                    weekly_used=0,
                    weekly_remaining=0,
                    budget_health="unknown",
                ),
                error="MetaAgent service not initialized",
            )

        try:
            budget_status = await service.budget_manager.get_status()
            return GetPooledBudgetResponse(budget=budget_status, error="")
        except Exception as e:
            logger.error(f"GetPooledBudget error: {e}")
            return GetPooledBudgetResponse(
                budget=PooledBudgetStatus(
                    weekly_limit=0,
                    weekly_used=0,
                    weekly_remaining=0,
                    budget_health="error",
                ),
                error=str(e),
            )

    async def GetQualitySummary(
        self,
        request: GetQualitySummaryRequest,
        context: grpc.aio.ServicerContext,
    ) -> GetQualitySummaryResponse:
        """Get quality assessment summary by source type."""
        service = self._services.metaagent_service
        if service is None:
            return GetQualitySummaryResponse(error="MetaAgent service not initialized")

        try:
            summary = await service.get_quality_summary(
                source_type=request.source_type if request.source_type else None,
            )
            return summary
        except Exception as e:
            logger.error(f"GetQualitySummary error: {e}")
            return GetQualitySummaryResponse(error=str(e))

    async def ListRecommendations(
        self,
        request: ListRecommendationsRequest,
        context: grpc.aio.ServicerContext,
    ) -> ListRecommendationsResponse:
        """List audit recommendations with optional filters."""
        service = self._services.metaagent_service
        if service is None:
            return ListRecommendationsResponse(
                error="MetaAgent service not initialized",
            )

        try:
            result = await service.list_recommendations(
                status_filter=request.status_filter if request.status_filter else None,
                severity_filter=request.severity_filter if request.severity_filter else None,
                limit=request.limit if request.limit > 0 else 20,
            )
            return result
        except Exception as e:
            logger.error(f"ListRecommendations error: {e}")
            return ListRecommendationsResponse(error=str(e))

    async def UpdateRecommendation(
        self,
        request: UpdateRecommendationRequest,
        context: grpc.aio.ServicerContext,
    ) -> UpdateRecommendationResponse:
        """Update a recommendation status (accept/reject/implement/verify)."""
        service = self._services.metaagent_service
        if service is None:
            return UpdateRecommendationResponse(
                success=False,
                error="MetaAgent service not initialized",
            )

        try:
            result = await service.update_recommendation(
                recommendation_id=request.recommendation_id,
                new_status=request.new_status,
            )
            return result
        except Exception as e:
            logger.error(f"UpdateRecommendation error: {e}")
            return UpdateRecommendationResponse(
                success=False,
                error=str(e),
            )

    # =========================================================================
    # Collections (Public Content Landing Page)
    # =========================================================================

    async def CollectionStatus(
        self,
        request: CollectionStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionStatusResponse:
        """Get collection statistics."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionStatusResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            stats = await service.get_stats()
            featured = await service.get_featured_collection()

            featured_info = None
            if featured:
                featured_cards = await service.list_cards(featured.collection_id)
                pending = sum(1 for c in featured_cards if c.status == "pending")
                published = sum(1 for c in featured_cards if c.status == "published")
                featured_info = CollectionInfo(
                    collection_id=featured.collection_id,
                    slug=featured.slug,
                    name=featured.name,
                    description=featured.description,
                    status=featured.status,
                    featured=featured.featured,
                    total_cards=len(featured_cards),
                    pending_cards=pending,
                    published_cards=published,
                    created_at=featured.created_at.isoformat() if featured.created_at else "",
                )

            return CollectionStatusResponse(
                success=True,
                total_collections=stats.get("total_collections", 0),
                total_cards=stats.get("total_cards", 0),
                pending_cards=stats.get("pending_cards", 0),
                published_cards=stats.get("published_cards", 0),
                featured_collection=featured_info,
            )
        except Exception as e:
            logger.exception(f"CollectionStatus failed: {e}")
            return CollectionStatusResponse(success=False, error=str(e))

    async def CollectionList(
        self,
        request: CollectionListRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionListResponse:
        """List all collections."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionListResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            status_filter = request.status if request.status else None
            limit = request.limit if request.limit > 0 else 50
            collections = await service.list_collections(status=status_filter, limit=limit)

            collection_infos = []
            for col in collections:
                cards = await service.list_cards(col.collection_id)
                pending = sum(1 for c in cards if c.status == "pending")
                published = sum(1 for c in cards if c.status == "published")
                collection_infos.append(CollectionInfo(
                    collection_id=col.collection_id,
                    slug=col.slug,
                    name=col.name,
                    description=col.description,
                    status=col.status,
                    featured=col.featured,
                    total_cards=len(cards),
                    pending_cards=pending,
                    published_cards=published,
                    created_at=col.created_at.isoformat() if col.created_at else "",
                ))

            return CollectionListResponse(success=True, collections=collection_infos)
        except Exception as e:
            logger.exception(f"CollectionList failed: {e}")
            return CollectionListResponse(success=False, error=str(e))

    async def CollectionCreate(
        self,
        request: CollectionCreateRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionCreateResponse:
        """Create a new collection."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionCreateResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            collection = await service.create_collection(
                slug=request.slug,
                name=request.name,
                description=request.description,
                featured=request.featured,
            )

            return CollectionCreateResponse(
                success=True,
                collection=CollectionInfo(
                    collection_id=collection.collection_id,
                    slug=collection.slug,
                    name=collection.name,
                    description=collection.description,
                    status=collection.status,
                    featured=collection.featured,
                    total_cards=0,
                    pending_cards=0,
                    published_cards=0,
                    created_at=collection.created_at.isoformat() if collection.created_at else "",
                ),
            )
        except Exception as e:
            logger.exception(f"CollectionCreate failed: {e}")
            return CollectionCreateResponse(success=False, error=str(e))

    async def CollectionSetFeatured(
        self,
        request: CollectionSetFeaturedRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionSetFeaturedResponse:
        """Set a collection as featured."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionSetFeaturedResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            collection = await service.get_collection_by_slug(request.slug)
            if not collection:
                return CollectionSetFeaturedResponse(
                    success=False,
                    error=f"Collection not found: {request.slug}",
                )

            await service.set_featured(collection.collection_id)
            # Refresh to get updated state
            collection = await service.get_collection(collection.collection_id)

            return CollectionSetFeaturedResponse(
                success=True,
                collection=CollectionInfo(
                    collection_id=collection.collection_id,
                    slug=collection.slug,
                    name=collection.name,
                    description=collection.description,
                    status=collection.status,
                    featured=collection.featured,
                    total_cards=0,
                    pending_cards=0,
                    published_cards=0,
                    created_at=collection.created_at.isoformat() if collection.created_at else "",
                ),
            )
        except Exception as e:
            logger.exception(f"CollectionSetFeatured failed: {e}")
            return CollectionSetFeaturedResponse(success=False, error=str(e))

    async def CollectionAddCard(
        self,
        request: CollectionAddCardRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionAddCardResponse:
        """Add a card to a collection."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionAddCardResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            collection = await service.get_collection_by_slug(request.slug)
            if not collection:
                return CollectionAddCardResponse(
                    success=False,
                    error=f"Collection not found: {request.slug}",
                )

            card = await service.add_card(
                collection_id=collection.collection_id,
                title=request.title,
                summary=request.summary,
                source_url=request.source_url,
                source_type=request.source_type,
                image_url=request.image_url if request.image_url else None,
            )

            return CollectionAddCardResponse(
                success=True,
                card=CardInfo(
                    card_id=card.card_id,
                    title=card.title,
                    summary=card.summary,
                    source_url=card.source_url,
                    source_type=card.source_type,
                    image_url=card.image_url or "",
                    status=card.status,
                    published_at=card.published_at.isoformat() if card.published_at else "",
                    sequence=card.sequence or 0,
                ),
            )
        except Exception as e:
            logger.exception(f"CollectionAddCard failed: {e}")
            return CollectionAddCardResponse(success=False, error=str(e))

    async def CollectionListCards(
        self,
        request: CollectionListCardsRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionListCardsResponse:
        """List cards in a collection."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionListCardsResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            collection = await service.get_collection_by_slug(request.slug)
            if not collection:
                return CollectionListCardsResponse(
                    success=False,
                    error=f"Collection not found: {request.slug}",
                )

            status_filter = request.status if request.status else None
            limit = request.limit if request.limit > 0 else 100
            cards = await service.list_cards(
                collection_id=collection.collection_id,
                status=status_filter,
                limit=limit,
            )

            card_infos = [
                CardInfo(
                    card_id=c.card_id,
                    title=c.title,
                    summary=c.summary,
                    source_url=c.source_url,
                    source_type=c.source_type,
                    image_url=c.image_url or "",
                    status=c.status,
                    published_at=c.published_at.isoformat() if c.published_at else "",
                    sequence=c.sequence or 0,
                )
                for c in cards
            ]

            return CollectionListCardsResponse(
                success=True,
                cards=card_infos,
                total=len(cards),
            )
        except Exception as e:
            logger.exception(f"CollectionListCards failed: {e}")
            return CollectionListCardsResponse(success=False, error=str(e))

    async def CollectionPublishCards(
        self,
        request: CollectionPublishCardsRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionPublishCardsResponse:
        """Publish pending cards."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionPublishCardsResponse(
                    success=False,
                    error="Collection service not initialized",
                )

            count = request.count if request.count > 0 else 3
            collection_id = None

            if request.collection_slug:
                collection = await service.get_collection_by_slug(request.collection_slug)
                if not collection:
                    return CollectionPublishCardsResponse(
                        success=False,
                        error=f"Collection not found: {request.collection_slug}",
                    )
                collection_id = collection.collection_id

            # Use publish_and_sync to publish cards and sync to Cloudflare KV
            result = await service.publish_and_sync(count=count, collection_id=collection_id)

            card_infos = [
                CardInfo(
                    card_id=c["card_id"],
                    title=c["title"],
                    summary=c["summary"],
                    source_url=c["source_url"],
                    source_type=c["source_type"],
                    image_url=c.get("image_url") or "",
                    status=c.get("status") or "published",
                    published_at=c.get("published_at") or "",
                    sequence=c.get("sequence") or 0,
                )
                for c in result.get("published", [])
            ]

            kv_sync = result.get("kv_sync", {})
            kv_status = "synced" if kv_sync.get("success") else "not synced"

            # Use error field to communicate KV sync status (no kv_synced field in proto)
            error_msg = ""
            if not kv_sync.get("success"):
                error_msg = f"Cards published but KV sync failed: {kv_status}"

            return CollectionPublishCardsResponse(
                success=True,
                published_cards=card_infos,
                published_count=result.get("published_count", len(card_infos)),
                error=error_msg,
            )
        except Exception as e:
            logger.exception(f"CollectionPublishCards failed: {e}")
            return CollectionPublishCardsResponse(success=False, error=str(e))

    async def CollectionPublishViz(
        self,
        request: CollectionPublishVizRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionPublishVizResponse:
        """Publish 3D visualization data to Cloudflare KV."""
        try:
            # TODO: Implement when Cloudflare KV integration is added
            return CollectionPublishVizResponse(
                success=True,
                points_count=0,
                clusters_count=0,
                published_at="",
                error="Not yet implemented - Cloudflare KV integration pending",
            )
        except Exception as e:
            logger.exception(f"CollectionPublishViz failed: {e}")
            return CollectionPublishVizResponse(success=False, error=str(e))

    async def CollectionSyncTheme(
        self,
        request: CollectionSyncThemeRequest,
        context: grpc.aio.ServicerContext,
    ) -> CollectionSyncThemeResponse:
        """Sync theme configuration from HOCON to Cloudflare KV."""
        try:
            service = self._services.collection_service
            if service is None:
                return CollectionSyncThemeResponse(
                    success=False,
                    error="Collection service not initialized.\n  Try: /health fix engine\n  Or:  just restart-clean",
                )

            result = await service.sync_theme_config()

            return CollectionSyncThemeResponse(
                success=result.get("success", False),
                theme_id=result.get("theme_id", ""),
                title=result.get("title", ""),
                namespace_id=result.get("namespace_id", ""),
            )
        except Exception as e:
            logger.exception(f"CollectionSyncTheme failed: {e}")
            return CollectionSyncThemeResponse(success=False, error=str(e))

    # =========================================================================
    # Article Curation (gRPC-First, Engine Owns Filesystem)
    # =========================================================================

    async def ArticleStatus(
        self,
        request: ArticleStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> ArticleStatusResponse:
        """Get article curation situational awareness.

        Returns status for /article sitrep display including:
        - Is curation flow currently running?
        - List of pending articles with zk counts
        - Recent curation completions
        - Pending/published card counts
        """
        try:
            service = self._services.collection_service
            if service is None:
                return ArticleStatusResponse(
                    success=False,
                    error="Collection service not initialized.\n  Try: /health fix engine\n  Or:  just restart-clean",
                )

            status = await service.get_article_status()

            # Convert articles to proto
            articles = [
                ArticleInfo(
                    slug=a["slug"],
                    title=a["title"],
                    status=a["status"],
                    zk_count=a.get("zk_count", 0),
                    sources_count=a.get("sources_count", 0),
                )
                for a in status.get("articles_list", [])
            ]

            # Convert recent curations to proto
            recent = [
                CurationRunInfo(
                    run_id=r["run_id"],
                    slug=r.get("slug", ""),
                    completed_at=r.get("completed_at", ""),
                    cards_created=r.get("cards_created", 0),
                )
                for r in status.get("recent_curations", [])
            ]

            return ArticleStatusResponse(
                success=True,
                running=status.get("running", False),
                current_run_id=status.get("current_run_id") or "",
                current_step=status.get("current_step") or "",
                articles_pending=status.get("articles_pending", 0),
                articles=articles,
                recent_curations=recent,
                total_cards_pending=status.get("total_cards_pending", 0),
                total_cards_published=status.get("total_cards_published", 0),
            )
        except Exception as e:
            logger.exception(f"ArticleStatus failed: {e}")
            return ArticleStatusResponse(success=False, error=str(e))

    async def ArticleNew(
        self,
        request: ArticleNewRequest,
        context: grpc.aio.ServicerContext,
    ) -> ArticleNewResponse:
        """Create new article directory structure.

        Engine owns KB filesystem - clients MUST NOT write directly.
        Creates directory structure, article.md, and database record.
        """
        try:
            service = self._services.collection_service
            if service is None:
                return ArticleNewResponse(
                    success=False,
                    error="Collection service not initialized.\n  Try: /health fix engine\n  Or:  just restart-clean",
                )

            result = await service.create_article(
                slug=request.slug,
                title=request.title or "",
            )

            return ArticleNewResponse(
                success=True,
                slug=result.get("slug", ""),
                title=result.get("title", ""),
                kb_path=result.get("kb_path", ""),
                article_id=result.get("article_id", ""),
                collection_id=result.get("collection_id", ""),
                message=result.get("message", ""),
            )
        except Exception as e:
            logger.exception(f"ArticleNew failed: {e}")
            return ArticleNewResponse(success=False, error=str(e))

    async def ArticleCurate(
        self,
        request: ArticleCurateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[ArticleCurationEvent]:
        """Stream article curation progress events.

        Starts ArticleCurationFlow and streams progress via pg_notify.
        """
        try:
            service = self._services.collection_service
            if service is None:
                yield ArticleCurationEvent(
                    run_id="",
                    step="failed",
                    step_number=-1,
                    total_steps=9,
                    progress=-1.0,
                    message="Collection service not initialized.\n  Try: /health fix engine\n  Or:  just restart-clean",
                )
                return

            async for event in service.article_curate_stream(
                slug=request.slug or "",
            ):
                yield ArticleCurationEvent(
                    run_id=event.run_id,
                    step=event.step,
                    step_number=event.step_number,
                    total_steps=event.total_steps,
                    progress=event.progress,
                    message=event.message,
                )

        except Exception as e:
            logger.exception(f"ArticleCurate failed: {e}")
            yield ArticleCurationEvent(
                run_id="",
                step="failed",
                step_number=-1,
                total_steps=9,
                progress=-1.0,
                message=f"ArticleCurate error: {e}",
            )

    async def RenderCards(
        self,
        request: RenderCardsRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[RenderCardEvent]:
        """Stream card rendering progress events."""
        try:
            service = self._services.collection_service
            if service is None:
                yield RenderCardEvent(
                    phase=RENDER_PHASE_FAILED,
                    message="Collection service not initialized.\n"
                    "  #VIZ.00000010.SVCNOTINIT\n"
                    "  Try: /health fix engine\n"
                    "  Or:  just restart-clean",
                )
                return

            async for event in service.render_cards_stream(
                collection_slug=request.collection_slug,
                card_id=request.card_id,
                sample=request.sample,
                variants=list(request.variants),
                force=request.force,
                upload=request.upload,
                orchestrator=self._services.orchestrator_service,
            ):
                yield event

        except Exception as e:
            logger.exception(f"RenderCards failed: {e}")
            yield RenderCardEvent(
                phase=RENDER_PHASE_FAILED,
                message=f"RenderCards error: {e}",
                error=str(e),
            )
