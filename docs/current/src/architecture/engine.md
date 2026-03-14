# gRPC Engine

The engine is the central nervous system of Gaius. It's a long-running daemon that manages GPU resources, coordinates services, and exposes all functionality via gRPC on port 50051.

## Architecture

```
┌──────────────────────────────────────────────┐
│                gRPC Server :50051             │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ KServe OIP   │  │ Gaius Extensions     │  │
│  │ (inference)  │  │ (health, evolution,  │  │
│  │              │  │  orchestrator, ...)  │  │
│  └──────┬───────┘  └──────────┬───────────┘  │
├─────────┼─────────────────────┼──────────────┤
│         │    37 Services      │              │
│  ┌──────┴──────┐  ┌──────────┴───────────┐  │
│  │ Orchestrator │  │ Scheduler            │  │
│  │ Evolution    │  │ Cognition            │  │
│  │ Health       │  │ Topology             │  │
│  │ CLT          │  │ Dataset              │  │
│  │ ...          │  │ ...                  │  │
│  └──────┬───────┘  └──────────┬───────────┘  │
├─────────┼─────────────────────┼──────────────┤
│         │ Backend Controllers │              │
│  ┌──────┴──────┐  ┌──────────┴───────────┐  │
│  │ vLLM Ctrl   │  │ Embedding Ctrl       │  │
│  │ optillm Ctrl│  │ Backend Router       │  │
│  └──────┬───────┘  └──────────┬───────────┘  │
│         │                     │              │
│  ┌──────┴─────────────────────┴───────────┐  │
│  │           GPU Pool (6x NVIDIA)         │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## Startup Sequence

The engine initializes in 9 phases, streaming progress to connected clients:

| Phase | Duration | Action |
|-------|----------|--------|
| INIT | Immediate | InitController starts |
| GRPC | ~1s | gRPC server binds to :50051 |
| TELEMETRY | ~2s | OpenTelemetry setup |
| BACKENDS | ~5s | Backend router initialization |
| ORCHESTRATOR | ~2s | Orchestrator service starts |
| ENDPOINTS | ~240s | vLLM model loading to VRAM |
| TRANSPORT | ~2s | Aeron bridge setup |
| SERVICES | ~5s | Background services start |
| COMPLETE | - | Ready for inference |

The gRPC server starts early (phase 2) so clients can connect immediately and receive real-time progress during the ~4 minute vLLM startup.

## Module Structure

```
engine/
├── server.py              # Main daemon entry point
├── config.py              # Engine configuration
├── init_controller.py     # Initialization progress streaming
├── workloads.py           # Workload definitions
├── grpc/
│   ├── server.py          # gRPC server setup
│   └── servicers/
│       ├── inference_servicer.py  # KServe OIP implementation
│       └── gaius_servicer.py      # Gaius extensions
├── backends/
│   ├── backend_router.py  # Unified request routing
│   ├── vllm_controller.py # vLLM process management
│   ├── optillm_controller.py
│   └── embedding_controller.py
├── services/              # 37 registered services
├── compute/               # Grid projection, TDA
├── resources/             # GPU allocation
├── transport/             # Aeron bridge
├── generated/             # Protobuf generated code
└── proto/                 # Protobuf definitions
```

## gRPC Protocol

The engine implements two gRPC services:

### KServe Open Inference Protocol

Standard inference protocol for compatibility with ML platforms:

```protobuf
service GRPCInferenceService {
    rpc ServerLive(ServerLiveRequest) returns (ServerLiveResponse);
    rpc ServerReady(ServerReadyRequest) returns (ServerReadyResponse);
    rpc ModelMetadata(ModelMetadataRequest) returns (ModelMetadataResponse);
    rpc ModelInfer(ModelInferRequest) returns (ModelInferResponse);
}
```

### Gaius Extensions

Custom RPCs for Gaius-specific functionality:

```protobuf
service GaiusService {
    rpc WatchInit(stream InitRequest) returns (stream InitProgress);
    rpc WatchHealth(HealthRequest) returns (stream HealthMetrics);
    rpc EvolutionStatus(Empty) returns (EvolutionStatusResponse);
    rpc TriggerEvolution(TriggerRequest) returns (TriggerResponse);
    rpc GetEndpointStatus(Empty) returns (EndpointStatusResponse);
    rpc StartEndpoint(StartRequest) returns (StartResponse);
    rpc StopEndpoint(StopRequest) returns (StopResponse);
}
```

## Configuration

```hocon
engine {
    grpc {
        host = "0.0.0.0"
        port = 50051
        max_workers = 10
        max_message_size = 104857600  # 100MB
    }
    orchestrator {
        preload_endpoints = ["reasoning"]
        startup_timeout = 600  # 10 minutes
        health_check_interval = 30
    }
    scheduler {
        max_queue_size = 1000
        default_timeout = 120
    }
    evolution {
        enabled = true
        idle_threshold = 60
        cycle_interval = 3600
    }
}
```

## Running the Engine

```bash
# Via devenv process-compose (normal operation)
devenv processes up

# Standalone
uv run gaius-engine

# Clean restart (stops everything, cleans up, restarts)
just restart-clean
```

## Verifying Engine Health

```bash
# Check if gRPC port is listening
nc -zv localhost 50051

# Check endpoint status
uv run gaius-cli --cmd "/gpu status" --format json

# Watch engine logs
tail -f .devenv/processes.log | grep gaius-engine
```
