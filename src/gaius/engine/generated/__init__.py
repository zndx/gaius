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
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
    SwarmResult,
    # Workload Management
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
    # Init streaming
    InitCommand,
    InitEvent,
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
    # Gaius - Swarm
    "SwarmStreamRequest",
    "SwarmEvent",
    "SwarmResult",
    # Gaius - Workload Management
    "WorkloadType",
    "BeginWorkloadRequest",
    "BeginWorkloadResponse",
    "CompleteWorkloadRequest",
    "EndpointAllocationInfo",
    "ActiveWorkloadInfo",
    "GetActiveWorkloadsResponse",
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
    # Gaius - Init
    "InitCommand",
    "InitEvent",
    # Gaius - Service
    "GaiusServiceStub",
    "GaiusServiceServicer",
    "add_GaiusServiceServicer_to_server",
]
