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
    # Workload Management
    BeginWorkloadRequest,
    BeginWorkloadResponse,
    CompleteWorkloadRequest,
    EndpointAllocationInfo,
    ActiveWorkloadInfo,
    GetActiveWorkloadsResponse,
    WorkloadType,
    # Embeddings
    EmbedTextsRequest,
    EmbedTextsResponse,
    EmbeddingVector,
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
    # State Service (Thin Client Architecture)
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
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
    SwarmResult,
    # Dataset generation
    DatasetGenerationRequest,
    DatasetJobStatus,
    DatasetProgressEvent,
    GetDatasetJobRequest,
    CancelDatasetJobRequest,
    DatasetLineageRequest,
    DatasetLineageResponse,
    LineageNode,
    LineageEdge,
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
    # Gaius - Orchestrator
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
    # Gaius - Scheduler
    "CompleteRequest",
    "CompleteResponse",
    "SubmitJobRequest",
    "SubmitJobResponse",
    "GetJobResultRequest",
    "GetJobResultResponse",
    "SchedulerStatusResponse",
    # Gaius - Workload Management
    "BeginWorkloadRequest",
    "BeginWorkloadResponse",
    "CompleteWorkloadRequest",
    "EndpointAllocationInfo",
    "ActiveWorkloadInfo",
    "GetActiveWorkloadsResponse",
    "WorkloadType",
    # Gaius - Embeddings
    "EmbedTextsRequest",
    "EmbedTextsResponse",
    "EmbeddingVector",
    # Gaius - Evolution
    "EvolutionStatusResponse",
    "TriggerEvolutionRequest",
    "EvolutionCycleResponse",
    # Gaius - Cognition
    "CognitionStatusResponse",
    "ThoughtMessage",
    "GetRecentThoughtsRequest",
    "GetRecentThoughtsResponse",
    "TriggerCognitionRequest",
    "TriggerCognitionResponse",
    "CognitionActivityResponse",
    # Gaius - State Service
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
    # Gaius - Health
    "HealthStreamRequest",
    "HealthMetrics",
    "GPUMetrics",
    "EndpointHealth",
    # Gaius - Events
    "EventStreamRequest",
    "Event",
    # Gaius - Grid
    "ProjectEmbeddingsRequest",
    "GridPosition",
    "ProjectEmbeddingsResponse",
    "ProjectQueryRequest",
    "ProjectQueryResponse",
    # Gaius - TDA
    "ComputeTDARequest",
    "PersistenceInterval",
    "TDAResponse",
    # Gaius - Explain
    "ExplainRequest",
    "ExplainResponse",
    # Gaius - Init streaming
    "InitCommand",
    "InitEvent",
    # Gaius - Command Service
    "ExecuteCommandRequest",
    "ExecuteCommandResponse",
    # Gaius - Init/Reindex
    "InitRequest",
    "InitResponse",
    "InitProgress",
    "ReindexRequest",
    "ReindexResponse",
    "ReindexProgress",
    # Gaius - Swarm streaming
    "SwarmStreamRequest",
    "SwarmEvent",
    "SwarmResult",
    # Gaius - Dataset generation
    "DatasetGenerationRequest",
    "DatasetJobStatus",
    "DatasetProgressEvent",
    "GetDatasetJobRequest",
    "CancelDatasetJobRequest",
    "DatasetLineageRequest",
    "DatasetLineageResponse",
    "LineageNode",
    "LineageEdge",
    # Service stubs
    "GaiusServiceStub",
    "GaiusServiceServicer",
    "add_GaiusServiceServicer_to_server",
]
