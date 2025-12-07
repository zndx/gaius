# gRPC/OIP Transport Implementation

## Summary

Implemented gRPC transport for gaius-engine using KServe Open Inference Protocol (OIP) v2 as the standard, with custom Gaius extensions for orchestrator, scheduler, evolution, and other services.

## Components Created

### Phase 1: Proto Infrastructure
- `src/gaius/engine/proto/open_inference_grpc.proto` - KServe OIP v2 definitions
- `src/gaius/engine/proto/gaius_service.proto` - Custom Gaius extensions
- `scripts/compile_protos.sh` - Proto compilation script
- `src/gaius/engine/generated/` - Generated Python bindings

### Phase 2: gRPC Server
- `src/gaius/engine/grpc/server.py` - GrpcServer class with async support
- `src/gaius/engine/grpc/servicers/inference_servicer.py` - KServe OIP implementation
- `src/gaius/engine/grpc/servicers/gaius_servicer.py` - Custom Gaius service

### Phase 3: gRPC Client
- `src/gaius/client/grpc_client.py` - GrpcEngineClient matching EngineClient interface
- `src/gaius/client/__init__.py` - Transport auto-selection (gRPC preferred)

### Phase 4: BDD Tests
- `features/grpc.feature` - 17 scenarios covering OIP, Gaius, transport, streaming, errors
- `features/steps/grpc_steps.py` - Step definitions
- `features/environment.py` - Updated for gRPC test support

### Phase 5: Engine Integration
- `src/gaius/engine/config.py` - Added GrpcConfig dataclass
- `src/gaius/engine/server.py` - Integrated gRPC as PRIMARY transport

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    gaius-engine                          │
├─────────────────────────────────────────────────────────┤
│  GrpcServer (PRIMARY)                                    │
│  ├── GRPCInferenceService (KServe OIP v2)               │
│  │   ├── ServerLive/Ready                               │
│  │   ├── ModelReady/Metadata                            │
│  │   └── ModelInfer (streaming support)                 │
│  └── GaiusService (custom extensions)                   │
│      ├── OrchestratorStatus                             │
│      ├── SchedulerStatus/Complete/Submit                │
│      ├── EvolutionStatus/Trigger/Start/Stop            │
│      ├── Grid/TDA operations                            │
│      └── HealthStream/EventStream (server streaming)    │
├─────────────────────────────────────────────────────────┤
│  Aeron Bridge (optional/legacy)                         │
│  Unix Socket (debugging fallback)                       │
└─────────────────────────────────────────────────────────┘
```

## Test Results

```
Proto compilation tests: 2 passed
Transport selection tests: 3 passed
Integration tests: 12 skipped (server not running)
Total: 5 passed, 12 skipped
```

## Usage

### Start Engine with gRPC
```bash
gaius-engine --verbose
# Listens on 0.0.0.0:50051 by default
```

### Client Usage
```python
from gaius.client import get_engine_client

# Auto-selects gRPC (preferred) or socket (fallback)
client = await get_engine_client()

# Or explicitly use gRPC
from gaius.client import GrpcEngineClient
client = GrpcEngineClient()
await client.connect()

# Call services
result = await client.call("Orchestrator", "status")
```

### Environment Variables
- `GAIUS_TRANSPORT=grpc|socket` - Force specific transport
- `GAIUS_ENABLE_FALLBACKS=true` - Enable socket fallback
- `GAIUS_GRPC_HOST`, `GAIUS_GRPC_PORT` - Override defaults

## Dependencies Added

```toml
grpc = [
    "grpcio>=1.59.0",
    "grpcio-tools>=1.59.0",
    "grpcio-status>=1.59.0",
    "grpcio-health-checking>=1.59.0",
    "protobuf>=4.25.0",
]
```

## Next Steps

1. Run integration tests with live engine: `GAIUS_RUN_GRPC_TESTS=true uv run behave features/grpc.feature`
2. Add TLS support for production
3. Implement ModelInfer for actual inference routing
4. Add bidirectional streaming for interactive sessions
