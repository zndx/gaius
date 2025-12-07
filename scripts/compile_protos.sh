#!/bin/bash
# Compile Protocol Buffers for Gaius gRPC services
#
# This script generates Python bindings from the proto files:
# - open_inference_grpc.proto (KServe OIP)
# - gaius_service.proto (Gaius extensions)
#
# Usage: ./scripts/compile_protos.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

PROTO_DIR="$PROJECT_ROOT/src/gaius/engine/proto"
OUTPUT_DIR="$PROJECT_ROOT/src/gaius/engine/generated"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Check if grpcio-tools is available
if ! python -c "import grpc_tools.protoc" 2>/dev/null; then
    echo "Error: grpcio-tools not installed. Run: uv sync --extra grpc"
    exit 1
fi

echo "Compiling Protocol Buffers..."
echo "  Proto dir:  $PROTO_DIR"
echo "  Output dir: $OUTPUT_DIR"

# Compile OIP proto
echo "  - open_inference_grpc.proto"
python -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --python_out="$OUTPUT_DIR" \
    --grpc_python_out="$OUTPUT_DIR" \
    "$PROTO_DIR/open_inference_grpc.proto"

# Compile Gaius service proto
echo "  - gaius_service.proto"
python -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --python_out="$OUTPUT_DIR" \
    --grpc_python_out="$OUTPUT_DIR" \
    "$PROTO_DIR/gaius_service.proto"

# Fix imports in generated files (grpc_tools generates absolute imports)
echo "Fixing imports in generated files..."
for file in "$OUTPUT_DIR"/*_pb2_grpc.py; do
    if [[ -f "$file" ]]; then
        # Fix import statements to use relative imports within the package
        sed -i 's/^import \([a-z_]*_pb2\)/from . import \1/' "$file"
    fi
done

# Create __init__.py for the generated package
cat > "$OUTPUT_DIR/__init__.py" << 'EOF'
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
    EndpointResponse,
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
    # TDA
    ComputeTDARequest,
    PersistenceInterval,
    TDAResponse,
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
    "EndpointResponse",
    "CompleteRequest",
    "CompleteResponse",
    "SubmitJobRequest",
    "SubmitJobResponse",
    "GetJobResultRequest",
    "GetJobResultResponse",
    "SchedulerStatusResponse",
    "EvolutionStatusResponse",
    "TriggerEvolutionRequest",
    "EvolutionCycleResponse",
    "HealthStreamRequest",
    "HealthMetrics",
    "GPUMetrics",
    "EndpointHealth",
    "EventStreamRequest",
    "Event",
    "ProjectEmbeddingsRequest",
    "GridPosition",
    "ProjectEmbeddingsResponse",
    "ProjectQueryRequest",
    "ProjectQueryResponse",
    "ComputeTDARequest",
    "PersistenceInterval",
    "TDAResponse",
    "GaiusServiceStub",
    "GaiusServiceServicer",
    "add_GaiusServiceServicer_to_server",
]
EOF

echo "Done! Generated files in $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
