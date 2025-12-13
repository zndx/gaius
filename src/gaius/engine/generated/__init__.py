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
    EndpointAllocationInfo,
    # Scheduler
    CompleteRequest,
    CompleteResponse,
    SubmitJobRequest,
    SubmitJobResponse,
    GetJobResultRequest,
    GetJobResultResponse,
    SchedulerStatusResponse,
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
    GridState,
    # TDA
    ComputeTDARequest,
    PersistenceInterval,
    TDAResponse,
    TDAFeatures,
    # Explain (Grid Position Interpretation)
    ExplainRequest,
    ExplainResponse,
    GeometryFeatures,
    GradientVector,
    BoundingBox,
    # Init streaming
    InitCommand,
    InitEvent,
    InitRequest,
    InitResponse,
    InitProgress,
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
    SwarmResult,
    # Workload tracking
    WorkloadType,
    BeginWorkloadRequest,
    BeginWorkloadResponse,
    CompleteWorkloadRequest,
    ActiveWorkloadInfo,
    GetActiveWorkloadsResponse,
    # Cognition
    TriggerCognitionRequest,
    TriggerCognitionResponse,
    ThoughtMessage,
    GetRecentThoughtsRequest,
    GetRecentThoughtsResponse,
    CognitionStatusResponse,
    CognitionActivityResponse,
    # State management
    GetStateRequest,
    StateUpdate,
    SubscribeStateRequest,
    UIPreferences,
    GetPreferencesRequest,
    SavePreferencesRequest,
    # Command execution
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    # Embedding
    EmbeddingVector,
    EmbedTextsRequest,
    EmbedTextsResponse,
    # Reindex
    ReindexRequest,
    ReindexResponse,
    ReindexProgress,
    PruneSnapshotsRequest,
    PruneSnapshotsResponse,
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
    "EndpointAllocationInfo",
    # Gaius - Scheduler
    "CompleteRequest",
    "CompleteResponse",
    "SubmitJobRequest",
    "SubmitJobResponse",
    "GetJobResultRequest",
    "GetJobResultResponse",
    "SchedulerStatusResponse",
    # Gaius - Evolution
    "EvolutionStatusResponse",
    "TriggerEvolutionRequest",
    "EvolutionCycleResponse",
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
    "GridState",
    # Gaius - TDA
    "ComputeTDARequest",
    "PersistenceInterval",
    "TDAResponse",
    "TDAFeatures",
    # Gaius - Explain
    "ExplainRequest",
    "ExplainResponse",
    "GeometryFeatures",
    "GradientVector",
    "BoundingBox",
    # Gaius - Init
    "InitCommand",
    "InitEvent",
    "InitRequest",
    "InitResponse",
    "InitProgress",
    # Gaius - Swarm
    "SwarmStreamRequest",
    "SwarmEvent",
    "SwarmResult",
    # Gaius - Workload
    "WorkloadType",
    "BeginWorkloadRequest",
    "BeginWorkloadResponse",
    "CompleteWorkloadRequest",
    "ActiveWorkloadInfo",
    "GetActiveWorkloadsResponse",
    # Gaius - Cognition
    "TriggerCognitionRequest",
    "TriggerCognitionResponse",
    "ThoughtMessage",
    "GetRecentThoughtsRequest",
    "GetRecentThoughtsResponse",
    "CognitionStatusResponse",
    "CognitionActivityResponse",
    # Gaius - State
    "GetStateRequest",
    "StateUpdate",
    "SubscribeStateRequest",
    "UIPreferences",
    "GetPreferencesRequest",
    "SavePreferencesRequest",
    # Gaius - Command
    "ExecuteCommandRequest",
    "ExecuteCommandResponse",
    # Gaius - Embedding
    "EmbeddingVector",
    "EmbedTextsRequest",
    "EmbedTextsResponse",
    # Gaius - Reindex
    "ReindexRequest",
    "ReindexResponse",
    "ReindexProgress",
    "PruneSnapshotsRequest",
    "PruneSnapshotsResponse",
    # Service stubs
    "GaiusServiceStub",
    "GaiusServiceServicer",
    "add_GaiusServiceServicer_to_server",
]
