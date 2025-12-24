"""Generated gRPC/Protobuf bindings for Gaius Engine.

This package contains:
- open_inference_grpc_pb2.py: KServe Open Inference Protocol messages
- open_inference_grpc_pb2_grpc.py: KServe OIP service stubs
- gaius_service_pb2.py: Gaius extension messages
- gaius_service_pb2_grpc.py: Gaius service stubs

Regenerate with: ./scripts/compile_protos.sh
"""

from .open_inference_grpc_pb2 import (
    ServerLiveRequest,
    ServerLiveResponse,
    ServerReadyRequest,
    ServerReadyResponse,
    ModelReadyRequest,
    ModelReadyResponse,
    ServerMetadataRequest,
    ServerMetadataResponse,
    ModelMetadataRequest,
    ModelMetadataResponse,
    ModelInferRequest,
    ModelInferResponse,
    InferTensorContents,
    InferParameter,
)

from .open_inference_grpc_pb2_grpc import (
    GRPCInferenceServiceStub,
    GRPCInferenceServiceServicer,
    add_GRPCInferenceServiceServicer_to_server,
)

from .gaius_service_pb2 import (
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
    EnsureEndpointResponse,
    # Scheduler
    CompleteRequest,
    CompleteResponse,
    SubmitJobRequest,
    SubmitJobResponse,
    GetJobResultRequest,
    GetJobResultResponse,
    SchedulerStatusResponse,
    # Workload
    WorkloadType,
    BeginWorkloadRequest,
    BeginWorkloadResponse,
    CompleteWorkloadRequest,
    EndpointAllocationInfo,
    ActiveWorkloadInfo,
    GetActiveWorkloadsResponse,
    # Embeddings
    EmbedTextsRequest,
    EmbedTextsResponse,
    EmbeddingVector,
    # Cognition
    CognitionStatusResponse,
    ThoughtMessage,
    GetRecentThoughtsRequest,
    GetRecentThoughtsResponse,
    TriggerCognitionRequest,
    TriggerCognitionResponse,
    CognitionActivityResponse,
    # State Service
    GetStateRequest,
    GridState,
    TDAFeatures,
    BoundingBox,
    GeometryFeatures,
    GradientVector,
    SubscribeStateRequest,
    StateUpdate,
    GetPreferencesRequest,
    UIPreferences,
    SavePreferencesRequest,
    PruneSnapshotsRequest,
    PruneSnapshotsResponse,
    # Init/Reindex
    InitRequest,
    InitResponse,
    InitProgress,
    ReindexRequest,
    ReindexResponse,
    ReindexProgress,
    # Evolution
    EvolutionStatusResponse,
    TriggerEvolutionRequest,
    EvolutionCycleResponse,
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
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
    SwarmResult,
    # Semantic Search
    SemanticSearchRequest,
    SearchResult,
    SemanticSearchResponse,
    # Command Execution
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    # Dataset Service
    DatasetGenerationRequest,
    DatasetJobStatus,
    DatasetProgressEvent,
    GetDatasetJobRequest,
    CancelDatasetJobRequest,
    DatasetLineageRequest,
    DatasetLineageResponse,
    LineageNode,
    LineageEdge,
    # MetaAgent
    MetaAgentQueryRequest,
    MetaAgentQueryResponse,
    MetaAgentEvent,
    # ThetaAgent
    ThetaSitrepRequest,
    ThetaSitrepResponse,
    ThetaConsolidateRequest,
    ThetaConsolidateResponse,
    ThetaConsolidationStatsRequest,
    ThetaConsolidationStatsResponse,
    # CLT (Cross-Layer Transcoders)
    CLTExtractRequest,
    CLTExtractResponse,
    SparseFeature,
    CLTAttributeRequest,
    CLTAttributeResponse,
    CLTAttributionEdge,
    CLTStatusRequest,
    CLTStatusResponse,
)

from .gaius_service_pb2_grpc import (
    GaiusServiceStub,
    GaiusServiceServicer,
    add_GaiusServiceServicer_to_server,
)

__all__ = [
    # OIP
    "ServerLiveRequest",
    "ServerLiveResponse",
    "ServerReadyRequest",
    "ServerReadyResponse",
    "ModelReadyRequest",
    "ModelReadyResponse",
    "ServerMetadataRequest",
    "ServerMetadataResponse",
    "ModelMetadataRequest",
    "ModelMetadataResponse",
    "ModelInferRequest",
    "ModelInferResponse",
    "InferTensorContents",
    "InferParameter",
    "GRPCInferenceServiceStub",
    "GRPCInferenceServiceServicer",
    "add_GRPCInferenceServiceServicer_to_server",
    # Gaius
    "OrchestratorStatusResponse",
    "GPUAllocation",
    "EndpointInfo",
    "StartEndpointRequest",
    "StopEndpointRequest",
    "RestartEndpointRequest",
    "CleanStartRequest",
    "CleanStartResponse",
    "EndpointResponse",
    "EnsureEndpointResponse",
    "CompleteRequest",
    "CompleteResponse",
    "SubmitJobRequest",
    "SubmitJobResponse",
    "GetJobResultRequest",
    "GetJobResultResponse",
    "SchedulerStatusResponse",
    # Workload
    "WorkloadType",
    "BeginWorkloadRequest",
    "BeginWorkloadResponse",
    "CompleteWorkloadRequest",
    "EndpointAllocationInfo",
    "ActiveWorkloadInfo",
    "GetActiveWorkloadsResponse",
    # Embeddings
    "EmbedTextsRequest",
    "EmbedTextsResponse",
    "EmbeddingVector",
    # Cognition
    "CognitionStatusResponse",
    "ThoughtMessage",
    "GetRecentThoughtsRequest",
    "GetRecentThoughtsResponse",
    "TriggerCognitionRequest",
    "TriggerCognitionResponse",
    "CognitionActivityResponse",
    # State Service
    "GetStateRequest",
    "GridState",
    "TDAFeatures",
    "BoundingBox",
    "GeometryFeatures",
    "GradientVector",
    "SubscribeStateRequest",
    "StateUpdate",
    "GetPreferencesRequest",
    "UIPreferences",
    "SavePreferencesRequest",
    "PruneSnapshotsRequest",
    "PruneSnapshotsResponse",
    # Init/Reindex
    "InitRequest",
    "InitResponse",
    "InitProgress",
    "ReindexRequest",
    "ReindexResponse",
    "ReindexProgress",
    # Evolution
    "EvolutionStatusResponse",
    "TriggerEvolutionRequest",
    "EvolutionCycleResponse",
    # Health
    "HealthStreamRequest",
    "HealthMetrics",
    "GPUMetrics",
    "EndpointHealth",
    # Events
    "EventStreamRequest",
    "Event",
    # Grid
    "ProjectEmbeddingsRequest",
    "GridPosition",
    "ProjectEmbeddingsResponse",
    "ProjectQueryRequest",
    "ProjectQueryResponse",
    # TDA
    "ComputeTDARequest",
    "PersistenceInterval",
    "TDAResponse",
    # Explain
    "ExplainRequest",
    "ExplainResponse",
    # Init streaming
    "InitCommand",
    "InitEvent",
    # Swarm streaming
    "SwarmStreamRequest",
    "SwarmEvent",
    "SwarmResult",
    # Semantic Search
    "SemanticSearchRequest",
    "SearchResult",
    "SemanticSearchResponse",
    # Command Execution
    "ExecuteCommandRequest",
    "ExecuteCommandResponse",
    # Dataset Service
    "DatasetGenerationRequest",
    "DatasetJobStatus",
    "DatasetProgressEvent",
    "GetDatasetJobRequest",
    "CancelDatasetJobRequest",
    "DatasetLineageRequest",
    "DatasetLineageResponse",
    "LineageNode",
    "LineageEdge",
    # MetaAgent
    "MetaAgentQueryRequest",
    "MetaAgentQueryResponse",
    "MetaAgentEvent",
    # ThetaAgent
    "ThetaSitrepRequest",
    "ThetaSitrepResponse",
    "ThetaConsolidateRequest",
    "ThetaConsolidateResponse",
    "ThetaConsolidationStatsRequest",
    "ThetaConsolidationStatsResponse",
    # CLT (Cross-Layer Transcoders)
    "CLTExtractRequest",
    "CLTExtractResponse",
    "SparseFeature",
    "CLTAttributeRequest",
    "CLTAttributeResponse",
    "CLTAttributionEdge",
    "CLTStatusRequest",
    "CLTStatusResponse",
    # Stubs
    "GaiusServiceStub",
    "GaiusServiceServicer",
    "add_GaiusServiceServicer_to_server",
]
