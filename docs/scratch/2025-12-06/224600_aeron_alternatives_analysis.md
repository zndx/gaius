# Aeron IPC Alternatives Analysis

## Current Architecture Issues

### Problems with Aeron

1. **C Bindings Complexity**: Aeron requires native C/C++ bindings that don't exist for Python. The `aeron_bridge.py` attempts to work around this but introduces fragility.

2. **Media Driver Dependency**: Requires `aeronmd` to be running separately - adds operational complexity and another failure point.

3. **Testing Friction**: The BDD tests show constant issues with socket fallbacks, connection states, and the need for `GAIUS_ALLOW_FALLBACKS=true` everywhere.

4. **Over-Engineering for Use Case**: Aeron is designed for ultra-low-latency financial trading systems. We're doing LLM inference where network latency dwarfs IPC overhead.

5. **Unix Socket Fallback**: We already have a working Unix socket fallback that's simpler and more reliable.

### What We Actually Need

From `server.py`, the engine provides:
- Request/Response RPC to 6 services (Orchestrator, Scheduler, Evolution, Grid, TDA, Health)
- Event broadcasting (evolution progress, health updates)
- Health metric streaming
- OpenTelemetry trace context propagation

## Alternative Approaches

### Option 1: Pure HTTP/REST with SSE (Recommended)

**Use vLLM's existing OpenAI-compatible API pattern**

```
gaius-engine
├── GET  /v1/health           - Health check
├── GET  /v1/models           - List models/agents
├── POST /v1/completions      - Text completion
├── POST /v1/chat/completions - Chat completion
├── GET  /v1/events           - Server-Sent Events stream
├── POST /v2/models/{name}/infer - OIP compatible inference
└── WebSocket /v1/ws          - Bidirectional for TUI
```

**Pros:**
- No native dependencies
- Works with standard Python (FastAPI/Starlette)
- OpenAI SDK client compatibility
- Easy to test with `httpx` or `requests`
- SSE for events (evolution progress, health)
- Native streaming for completions

**Cons:**
- HTTP overhead (minimal for our scale)
- Need WebSocket for true bidirectional

**Implementation:**
```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

app = FastAPI()

@app.post("/v1/completions")
async def complete(request: CompletionRequest):
    result = await backend_router.complete(...)
    return CompletionResponse(...)

@app.get("/v1/events")
async def events():
    async def event_generator():
        async for event in engine.events():
            yield {"event": event.type, "data": event.json()}
    return EventSourceResponse(event_generator())
```

### Option 2: gRPC (KServe Open Inference Protocol)

**Adopt KServe's standardized inference protocol**

```protobuf
service GRPCInferenceService {
  rpc ServerLive(ServerLiveRequest) returns (ServerLiveResponse) {}
  rpc ServerReady(ServerReadyRequest) returns (ServerReadyResponse) {}
  rpc ModelInfer(ModelInferRequest) returns (ModelInferResponse) {}
  // Custom extensions for evolution, health streaming
  rpc HealthStream(HealthRequest) returns (stream HealthMetrics) {}
  rpc EventStream(EventRequest) returns (stream Event) {}
}
```

**Pros:**
- Industry standard (KServe, Triton, Seldon all use it)
- Strong typing via protobuf
- Efficient binary serialization
- Native streaming support
- Excellent Python support via `grpcio`

**Cons:**
- Proto compilation step
- Slightly more complex than REST
- Need to extend OIP for our custom services

### Option 3: ZeroMQ (Simple Messaging)

```python
import zmq.asyncio

# Server
ctx = zmq.asyncio.Context()
router = ctx.socket(zmq.ROUTER)
router.bind("tcp://*:5555")

# Client
dealer = ctx.socket(zmq.DEALER)
dealer.connect("tcp://localhost:5555")
```

**Pros:**
- Simple API
- Good Python bindings
- Flexible patterns (REQ/REP, PUB/SUB, ROUTER/DEALER)
- No media driver needed

**Cons:**
- Not HTTP-compatible
- No browser support (unlike REST/WebSocket)
- Custom protocol needed

### Option 4: Unix Domain Socket with FlatBuffers

**Simplify current approach with our preferred serialization**

Keep Unix socket, drop Aeron entirely, use FlatBuffers for zero-copy performance:

```python
import asyncio
from gaius.engine.generated import Request, Response  # FlatBuffers

async def handle_client(reader, writer):
    while True:
        length = int.from_bytes(await reader.readexactly(4), 'big')
        data = await reader.readexactly(length)
        # FlatBuffers zero-copy access - no deserialization needed
        request = Request.GetRootAs(data, 0)
        response = await handle_request(request)
        builder = flatbuffers.Builder(256)
        # ... build response
        writer.write(len(buf).to_bytes(4, 'big') + buf)
```

**Pros:**
- Already works (just remove Aeron code path)
- Zero-copy deserialization - access fields directly from buffer
- Schema already defined in `config/gaius.fbs`
- Aligns with project preference for FlatBuffers
- Type-safe with generated Python bindings

**Cons:**
- Local-only (fine for our use case)
- No standards compliance
- Requires flatc compilation step

### Option 5: Apache Arrow Flight (High-Performance Data Services)

**Use Arrow Flight for high-throughput columnar data exchange**

Arrow Flight is a gRPC-based protocol optimized for transferring Apache Arrow data. It provides
wire-speed data transfer with zero serialization overhead when both ends use Arrow format.

```python
import pyarrow.flight as flight

class GaiusFlightServer(flight.FlightServerBase):
    def do_get(self, context, ticket):
        # Return streaming Arrow RecordBatches
        table = self._get_inference_results(ticket)
        return flight.RecordBatchStream(table)

    def do_action(self, context, action):
        # RPC-style actions for orchestrator, evolution, etc.
        if action.type == "orchestrator_status":
            return self._get_orchestrator_status()
```

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│                      gaius-engine                                │
├─────────────────────────────────────────────────────────────────┤
│  Arrow Flight Server (port 8100)                                │
│  ├── do_get()     → Stream inference results as Arrow batches  │
│  ├── do_put()     → Receive batch inference requests           │
│  ├── do_action()  → RPC for orchestrator, evolution, health    │
│  └── list_flights() → Available endpoints/agents               │
│                                                                  │
│  Built on gRPC (HTTP/2) with TLS support                        │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:**
- Wire-speed performance: 2-3 GB/s throughput, 95% bandwidth utilization
- Zero-copy: Arrow RecordBatches don't require serialization/deserialization
- Built on gRPC: HTTP/2, TLS, proper streaming, industry-standard
- Parallel transfers: Stream from multiple endpoints simultaneously
- Python support: `pyarrow.flight` is mature and well-documented
- Future-proof for batch inference, embeddings, TDA results (columnar data)

**Cons:**
- Heavyweight for simple RPC (overkill for status queries)
- Primarily designed for columnar analytical data
- GIL considerations for CPU-bound inference serving
- Less browser-friendly than pure HTTP/REST

**Best Use Cases:**
- Batch embedding generation (send 1000 texts, get 1000 vectors)
- TDA results (persistence diagrams as Arrow tables)
- Grid projection results (19x19 positions with metadata)
- Evolution metrics history (columnar time-series)

**References:**
- [Arrow Flight RPC Documentation](https://arrow.apache.org/docs/format/Flight.html)
- [Benchmarking Arrow Flight (ACM)](https://dl.acm.org/doi/fullHtml/10.1145/3527199.3527264)
- [PyArrow Flight Cookbook](https://arrow.apache.org/cookbook/py/flight.html)

## Serialization: FlatBuffers Preference

The project already has a comprehensive FlatBuffers schema in `config/gaius.fbs` defining:
- Service enumeration (Orchestrator, Scheduler, Evolution, Grid, TDA, Health)
- Request/Response envelopes with FlexBuffer params
- Event types for streaming
- Health metrics structures
- OpenTelemetry trace context propagation

**Current State:** `protocol.py` notes "Initial implementation uses JSON for simplicity.
Can be upgraded to FlatBuffers for zero-copy performance when needed."

**FlatBuffers vs Arrow:**
| Aspect | FlatBuffers | Arrow |
|--------|-------------|-------|
| Use Case | RPC messages, small payloads | Columnar data, bulk transfer |
| Access Pattern | Selective field access | Full table scans |
| Serialization | Zero-copy read | Zero-copy for Arrow-native |
| Schema | `.fbs` files, flatc | `.arrow` schema, runtime |
| Overhead | Minimal (bytes) | Higher (metadata) |

**Recommendation:** Use both:
- **FlatBuffers** for RPC messages (request/response, events, health metrics)
- **Arrow** for bulk data transfer (embeddings, TDA results, batch inference)

## Revised Recommendation: gRPC-First with OIP

**Key Insight from User**: Since we'll inevitably end up at gRPC/OIP (Cloudera Inference Service
uses OIP under the hood), starting with REST creates throwaway work. The mental model shift
between JSON/REST and Protobuf/gRPC is significant enough that a later migration would be
nearly a complete rewrite.

**Why gRPC-First Makes Sense:**

1. **OIP is gRPC-primary**: The HTTP/REST spec is *derived from* the gRPC spec, not the other way
2. **Cloudera AI Inference**: Uses OIP with gRPC - this is where we're headed anyway
3. **Arrow Flight uses gRPC**: Built on top of gRPC, so gRPC expertise transfers directly
4. **FlatBuffers & Protobuf**: Similar mental model (schema-first, code generation, zero-copy)
5. **Testing**: `grpcio-testing` provides proper mocking; pytest-grpc exists

**Revised Tiered Strategy:**

```
┌─────────────────────────────────────────────────────────────────┐
│                   gRPC-First Protocol Tiers                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  TIER 1: OIP gRPC (Primary Interface)                           │
│  ├── GRPCInferenceService.ModelInfer() - inference              │
│  ├── ServerLive/ServerReady/ModelReady - health                 │
│  ├── ServerMetadata/ModelMetadata - discovery                   │
│  └── Custom service extensions for Gaius (evolution, grid)      │
│                                                                  │
│  TIER 2: Arrow Flight (Bulk Data, also gRPC-based)              │
│  ├── do_get() - Stream embeddings, TDA results, metrics         │
│  ├── do_put() - Batch inference requests                        │
│  └── Shares gRPC infrastructure with Tier 1                     │
│                                                                  │
│  TIER 3: gRPC-Web Gateway (Optional, for browser/debugging)     │
│  ├── Envoy or grpcwebproxy for TUI web interface                │
│  └── Only if browser support needed                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Why Skip REST Entirely:**

| Factor | REST-First | gRPC-First |
|--------|------------|------------|
| Final destination | gRPC (OIP) | gRPC (OIP) |
| Intermediate work | Throwaway | Builds toward final |
| Mental model | JSON → Protobuf shift | Consistent from start |
| Testing approach | httpx → grpcio | grpcio throughout |
| Streaming | SSE/WebSocket (different) | Native gRPC streaming |
| Type safety | Runtime validation | Compile-time via proto |
| Code generation | Manual or Pydantic | protoc + grpcio |

## Proposed Architecture (gRPC-First)

```
┌─────────────────────────────────────────────────────────────────┐
│                        gaius-engine                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  gRPC Server (port 8100) - Primary Interface                    │
│  ├── GRPCInferenceService (OIP)                                 │
│  │   ├── ModelInfer() → Backend Router → optillm/vLLM          │
│  │   ├── ServerLive(), ServerReady(), ModelReady()             │
│  │   └── ServerMetadata(), ModelMetadata()                      │
│  │                                                               │
│  ├── GaiusService (Custom Extensions)                           │
│  │   ├── OrchestratorStatus(), SchedulerStatus()               │
│  │   ├── TriggerEvolution(), EvolutionStatus()                 │
│  │   ├── HealthStream() → server streaming                      │
│  │   └── EventStream() → server streaming                       │
│  │                                                               │
│  └── Arrow Flight Server (port 8101, same process)             │
│      ├── do_get() → Stream embeddings, TDA, metrics            │
│      ├── do_put() → Batch inference requests                    │
│      └── do_action() → High-throughput operations              │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  vLLM Backends (ports 8001-8006)                                │
│  └── OpenAI-compatible API (HTTP - internal only)              │
│                                                                  │
│  optillm (port 8000)                                            │
│  └── OpenAI-compatible with reasoning techniques                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

Clients:
- CLI: Uses grpcio to call GaiusService
- MCP Server: Uses grpcio to call GRPCInferenceService + GaiusService
- TUI: Uses gRPC streaming for real-time, unary RPCs for commands
- Python SDK: Uses Arrow Flight for batch operations
- External: gRPC clients (any language with proto support)
- (Optional) grpc-web proxy for browser debugging
```

**Benefits:**
1. **Delete Aeron entirely** - removes C binding issues
2. **No throwaway work** - building toward final OIP target
3. **Standards-aligned** - KServe OIP gRPC is the canonical spec
4. **Arrow Flight native** - both use gRPC, shared expertise
5. **Type-safe** - protobuf schemas catch errors at compile time
6. **Streaming native** - gRPC streaming beats SSE/WebSocket
7. **FlatBuffers affinity** - similar schema-first mental model

**Migration Path:**
1. Define `.proto` files (extend OIP with GaiusService)
2. Generate Python bindings with `grpc_tools.protoc`
3. Implement gRPC server in gaius-engine
4. Migrate client from socket to grpcio
5. Remove Aeron bridge code
6. Simplify testing - use `grpcio-testing`
7. Add Arrow Flight endpoints for bulk operations

## Protocol Alignment

### KServe OIP gRPC (Primary - from open_inference_grpc.proto)
```protobuf
service GRPCInferenceService {
  // Health
  rpc ServerLive(ServerLiveRequest) returns (ServerLiveResponse) {}
  rpc ServerReady(ServerReadyRequest) returns (ServerReadyResponse) {}
  rpc ModelReady(ModelReadyRequest) returns (ModelReadyResponse) {}

  // Discovery
  rpc ServerMetadata(ServerMetadataRequest) returns (ServerMetadataResponse) {}
  rpc ModelMetadata(ModelMetadataRequest) returns (ModelMetadataResponse) {}

  // Inference
  rpc ModelInfer(ModelInferRequest) returns (ModelInferResponse) {}
}
```

### Gaius Extensions (gaius_service.proto)
```protobuf
service GaiusService {
  // Orchestrator
  rpc OrchestratorStatus(Empty) returns (OrchestratorStatusResponse) {}
  rpc StartEndpoint(StartEndpointRequest) returns (StartEndpointResponse) {}
  rpc StopEndpoint(StopEndpointRequest) returns (StopEndpointResponse) {}

  // Scheduler
  rpc SchedulerStatus(Empty) returns (SchedulerStatusResponse) {}
  rpc SubmitJob(SubmitJobRequest) returns (SubmitJobResponse) {}

  // Evolution
  rpc EvolutionStatus(Empty) returns (EvolutionStatusResponse) {}
  rpc TriggerEvolution(TriggerEvolutionRequest) returns (TriggerEvolutionResponse) {}

  // Streaming (server-side streaming RPCs)
  rpc HealthStream(HealthStreamRequest) returns (stream HealthMetrics) {}
  rpc EventStream(EventStreamRequest) returns (stream Event) {}
}
```

### Arrow Flight (for bulk columnar data)
```python
# Flight endpoints use gRPC under the hood
class GaiusFlightServer(flight.FlightServerBase):
    def do_get(ticket) -> RecordBatchStream   # embeddings, TDA results
    def do_put(descriptor) -> FlightMetadataWriter  # batch inputs
    def do_action(action) -> Iterator[Result]  # orchestration commands
```

### vLLM Backends (internal HTTP, not exposed)
```
# gaius-engine translates gRPC → HTTP internally
POST http://localhost:800{1-6}/v1/completions
POST http://localhost:8000/v1/chat/completions  # optillm
```

## Implementation Estimate (gRPC-First)

### Phase 1: OIP gRPC Server (MVP)
1. **Define proto files**: 0.5 day
   - Import `open_inference_grpc.proto` from KServe
   - Define `gaius_service.proto` for extensions
2. **Generate Python bindings**: 0.5 day
   - `grpc_tools.protoc` compilation
   - Set up build process
3. **Implement GRPCInferenceService**: 1 day
   - ModelInfer routing to vLLM backends
   - Health/metadata endpoints
4. **Implement GaiusService**: 1 day
   - Orchestrator, Scheduler, Evolution status
   - Streaming endpoints
5. **Migrate client to grpcio**: 1 day
6. **Remove Aeron code**: 0.5 day
7. **Update tests with grpcio-testing**: 0.5 day

**Phase 1 Total: ~5 days** for complete gRPC migration.

### Phase 2: Arrow Flight (Bulk Data)
1. **Arrow Flight server implementation**: 1 day
2. **Batch embedding endpoint (do_get)**: 1 day
3. **TDA results streaming**: 0.5 day
4. **Batch inference (do_put)**: 0.5 day

**Phase 2 Total: ~3 days** for Arrow Flight integration.

### Phase 3: Polish & Observability
1. **OpenTelemetry gRPC interceptors**: 0.5 day
2. **Prometheus metrics**: 0.5 day
3. **gRPC-web gateway (optional)**: 1 day

**Phase 3 Total: ~2 days** for production hardening.

## Decision Matrix (Revised)

| Criteria | gRPC/OIP | Arrow Flight | REST/JSON |
|----------|----------|--------------|-----------|
| Aligns with destination | ★★★★★ | ★★★★★ | ★☆☆☆☆ |
| Ease of testing | ★★★★☆ | ★★★☆☆ | ★★★★★ |
| Standards compliance | ★★★★★ | ★★★★☆ | ★★★☆☆ |
| Performance (small) | ★★★★☆ | ★★★☆☆ | ★★★☆☆ |
| Performance (bulk) | ★★★☆☆ | ★★★★★ | ★★☆☆☆ |
| Type safety | ★★★★★ | ★★★★☆ | ★★☆☆☆ |
| Streaming | ★★★★★ | ★★★★★ | ★★☆☆☆ |
| Schema evolution | ★★★★★ | ★★★★☆ | ★★☆☆☆ |
| Browser support | ★★☆☆☆ | ☆☆☆☆☆ | ★★★★★ |

**Recommended Approach:**
1. Start with gRPC/OIP (Phase 1) - builds toward Cloudera/KServe compatibility
2. Add Arrow Flight (Phase 2) - for batch operations, same gRPC foundation
3. Add gRPC-web if browser debugging needed (Phase 3)

## Multi-Scale Spatial-Temporal-Spectral Data Considerations

### The Question
Can OIP/Arrow Flight handle multi-scale spatial-temporal-spectral datasets, keeping GPU
processing consolidated in gaius-engine rather than adding Dask/Holoviews dependencies?

### OIP Tensor Capabilities

OIP's `ModelInferRequest` natively supports N-dimensional tensors:

```protobuf
message InferInputTensor {
  string name = 1;           // e.g., "raster_cube"
  string datatype = 2;       // FP32, FP16, INT16, etc.
  repeated int64 shape = 3;  // [batch, time, bands, height, width]
  InferTensorContents contents = 5;
}
```

**Supported shapes for spatial-temporal-spectral:**
- `[batch, time, height, width, channels]` - video/temporal
- `[batch, bands, height, width]` - multispectral raster
- `[batch, z, y, x]` - volumetric/3D
- `[batch, time, bands, height, width]` - full hypercube

**Raw binary transfer:** `raw_input_contents` provides high-performance path:
- Flattened row-major order
- No protobuf allocation overhead
- FP16 support (critical for GPU efficiency)
- Direct GPU memory transfer possible

### OIP Limitations for Large Rasters

| Aspect | OIP Status | Workaround |
|--------|------------|------------|
| Arbitrary N-dim tensors | ✅ Supported | Use shape field |
| Chunked streaming | ⚠️ Per-request | Multiple requests |
| Coordinate labels (lat/lon/time) | ❌ Not native | Use parameters map |
| CRS/projection metadata | ❌ Not native | Use parameters map |
| Variable-size dims | ✅ Via shape=-1 | Works |
| >2GB messages | ⚠️ gRPC limit | Chunk or Flight |

### Arrow Flight: The Chunking Solution

For large rasters that exceed gRPC message limits, Arrow Flight provides:

```python
# Server: Stream raster as chunked RecordBatches
def do_get(self, context, ticket):
    raster = load_raster(ticket.ticket)  # [time, bands, height, width]

    # Stream as chunked Arrow table with metadata
    schema = pa.schema([
        pa.field("data", pa.list_(pa.float32())),
        pa.field("shape", pa.list_(pa.int64())),
        pa.field("chunk_idx", pa.int32()),
    ], metadata={
        b"crs": b"EPSG:4326",
        b"bounds": b"[-180,-90,180,90]",
        b"time_range": b"2020-01-01/2024-12-31",
    })

    for chunk in raster.iter_chunks(chunk_size=1024*1024):
        batch = pa.RecordBatch.from_arrays([...], schema=schema)
        yield batch
```

**Arrow Flight advantages for rasters:**
- Stream arbitrarily large data
- Schema metadata for CRS, bounds, timestamps
- Parallel endpoint streaming (multi-GPU)
- Zero-copy to GPU via CUDA Arrow

### Proposed Hybrid Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│              Spatial-Temporal-Spectral Data Flow                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Small/Medium Rasters (<2GB)                                    │
│  └── OIP ModelInfer with raw_input_contents                     │
│      └── shape: [1, 365, 12, 1024, 1024]  # 1yr, 12 bands       │
│                                                                  │
│  Large Rasters (>2GB) / Streaming                               │
│  └── Arrow Flight do_get/do_put                                 │
│      └── Chunked RecordBatches with metadata                    │
│      └── Parallel streaming from multiple endpoints             │
│                                                                  │
│  GPU Processing (stays in engine)                               │
│  └── vLLM for inference                                         │
│  └── RAPIDS cuDF for tabular GPU ops                            │
│  └── CuPy for array ops                                         │
│  └── TDA on GPU (giotto-tda with CUDA)                          │
│                                                                  │
│  Avoids: Dask distributed, Holoviews, external schedulers       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Metadata Convention for Rasters

Since OIP doesn't have native CRS/coordinate support, use the parameters map:

```python
request = ModelInferRequest(
    model_name="raster_processor",
    inputs=[InferInputTensor(
        name="cube",
        datatype="FP32",
        shape=[1, 12, 6, 1024, 1024],  # batch, time, bands, h, w
        parameters={
            "crs": InferParameter(string_param="EPSG:4326"),
            "bounds": InferParameter(string_param="-180,-90,180,90"),
            "time_dim": InferParameter(string_param="2024-01-01/2024-12-31/MS"),
            "bands": InferParameter(string_param="B01,B02,B03,B04,B05,B06"),
        },
    )],
    raw_input_contents=[raster_bytes],  # Flattened FP32
)
```

### Comparison: OIP+Flight vs Dask/Holoviews

| Capability | OIP + Arrow Flight | Dask + Holoviews |
|------------|-------------------|------------------|
| GPU consolidation | ✅ All in engine | ❌ Separate workers |
| Chunked streaming | ✅ Flight | ✅ Native |
| Coordinate labels | ⚠️ Via parameters | ✅ Native xarray |
| Lazy evaluation | ❌ Eager | ✅ Native |
| Visualization | ❌ Not built-in | ✅ Holoviews |
| Standards-aligned | ✅ OIP/gRPC | ❌ Custom |
| Dependencies | grpcio, pyarrow | dask, distributed, holoviews |

### Recommendation

**Yes, OIP can handle spatial-temporal-spectral data** with these caveats:

1. **Use OIP for inference requests** where tensor fits in gRPC message (~2GB)
2. **Use Arrow Flight for bulk transfer** of large rasters and time series
3. **Store metadata in parameters map** (CRS, bounds, time coordinates)
4. **Keep GPU ops in engine** - no need for Dask distributed scheduler

This keeps the architecture clean: one place for GPU work (gaius-engine), standard
protocols throughout (OIP + Flight), and no proliferation of dependencies.

### References
- [xarray Arrow integration (open issue)](https://github.com/apache/arrow/issues/17672)
- [OIP V2 Protocol](https://kserve.github.io/website/docs/concepts/architecture/data-plane/v2-protocol)
- [Arrow Flight for scientific data](https://arrow.apache.org/docs/format/Flight.html)
- [Zarr chunked arrays](https://guide.cloudnativegeo.org/zarr/intro.html)

## Concrete Use Case: The Well + PINNs + xLSTM

### The Well Dataset Collection

[The Well](https://github.com/PolymathicAI/the_well) is a 15TB collection of physics simulation
datasets from PolymathicAI (NeurIPS 2024), designed for training PDE surrogate models.

**Local datasets available:**
```
/raid/datasets/the-well/datasets/
├── acoustic_scattering_maze/     # 279GB - 15GB chunks (HDF5)
│   └── data/{train,valid,test}/
└── turbulent_radiative_layer_2D/ # 5.4GB - parameterized tcool values
    └── data/train/
```

**Dataset characteristics:**
- Format: HDF5 chunked files
- Structure: Spatiotemporal fields (time × space × channels)
- Physics: PDEs governing fluid dynamics, acoustics, MHD, biology
- Scale: Individual chunks 15GB, full dataset up to 5.1TB

### xLSTM for PDE Surrogate Modeling

[xLSTM](https://arxiv.org/abs/2405.04517) (Hochreiter et al., NeurIPS 2024) is promising for
physics simulations because:

1. **O(N) time complexity** vs O(N²) for transformers - critical for long sequences
2. **mLSTM is fully parallelizable** - GPU-friendly matrix memory
3. **Exponential gating** - better information flow control
4. **Covariance update rule** - captures correlations in physical fields

**Application to PINNs:**
- Physics-informed loss: Embed PDE residuals in training
- Surrogate modeling: Learn time-stepper for expensive simulations
- xLSTM handles temporal dependencies efficiently

### Multi-Host HPC Scaling Requirements

```
┌─────────────────────────────────────────────────────────────────┐
│                   Scaling Architecture                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  LOCAL (tinybox, 6× GPU)                                        │
│  └── Develop & validate on subset of The Well                   │
│  └── gaius-engine: OIP + Arrow Flight                           │
│  └── Single-node training with gradient accumulation            │
│                                                                  │
│  SCALE (HPC, 100s of GPUs)                                      │
│  └── Same OIP interface - just more endpoints                   │
│  └── Arrow Flight parallel streaming from many nodes            │
│  └── Distributed training: FSDP or DeepSpeed                    │
│  └── Data parallel across The Well chunks                       │
│                                                                  │
│  Why OIP + Flight Pays Off at Scale:                            │
│  ├── Standard protocol = works with Cloudera/KServe infra       │
│  ├── Arrow Flight = multi-node parallel data streaming          │
│  ├── gRPC = proven at Google/Meta scale                         │
│  └── No custom protocols to debug at 100+ nodes                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow for The Well + xLSTM Training

```python
# OIP request for a batch of physics simulation data
request = ModelInferRequest(
    model_name="xlstm_pinn_surrogate",
    inputs=[InferInputTensor(
        name="field_sequence",
        datatype="FP32",
        shape=[batch, time_steps, height, width, channels],
        # e.g., [32, 64, 256, 256, 4] for velocity + pressure fields
        parameters={
            "dataset": InferParameter(string_param="acoustic_scattering_maze"),
            "physics": InferParameter(string_param="wave_equation"),
            "pde_weight": InferParameter(double_param=0.1),  # PINN loss weight
        },
    )],
    raw_input_contents=[field_bytes],  # 32×64×256×256×4×4 = 2GB
)

# For larger batches, use Arrow Flight streaming
flight_client = flight.connect("grpc://gaius-engine:8101")
reader = flight_client.do_get(flight.Ticket(b"well/acoustic/train/chunk_0"))
for batch in reader:  # Stream 15GB chunks without OOM
    process_batch(batch)
```

### Investment Payoff

| Complexity Now | Return at Scale |
|----------------|-----------------|
| Define .proto files | Works with any OIP-compliant system |
| Learn grpcio | Same API at 100 nodes |
| Arrow Flight setup | Parallel streaming across HPC |
| OIP parameters for physics metadata | Standard interface for PINNs |

The "extra complexity locally" of gRPC/OIP/Flight is actually *less* total complexity
because you're not rewriting protocols when you scale. The same gaius-engine that
serves 6 local GPUs can serve 600 distributed GPUs with config changes, not code changes.

## Sources

### KServe Open Inference Protocol
- [OIP gRPC Specification](https://github.com/kserve/open-inference-protocol/blob/main/specification/protocol/inference_grpc.md)
- [open_inference_grpc.proto](https://github.com/open-inference/open-inference-protocol/blob/main/specification/protocol/open_inference_grpc.proto)
- [KServe V2 Protocol Documentation](https://kserve.github.io/website/docs/concepts/architecture/data-plane/v2-protocol)
- [KServe Python Runtime SDK API](https://kserve.github.io/website/docs/reference/python-runtime-sdk/python-runtime-sdk-api)

### Apache Arrow Flight
- [Arrow Flight RPC Documentation](https://arrow.apache.org/docs/format/Flight.html)
- [Introducing Arrow Flight](https://arrow.apache.org/blog/2019/10/13/introducing-arrow-flight/)
- [Benchmarking Arrow Flight (ACM)](https://dl.acm.org/doi/fullHtml/10.1145/3527199.3527264)
- [PyArrow Flight Cookbook](https://arrow.apache.org/cookbook/py/flight.html)
- [gRPC & Apache Arrow Flight](https://blog.dataengineerthings.org/grpc-apache-arrow-flight-are-game-changers-for-high-performance-data-transfer-8182eb2dd2cc)

### FlatBuffers & Serialization
- [Arrow FAQ - FlatBuffers vs Arrow](https://arrow.apache.org/faq/)
- [FlatBuffers Wikipedia](https://en.wikipedia.org/wiki/FlatBuffers)

### Cloudera
- [Cloudera AI Inference Service](https://www.cloudera.com/products/machine-learning/ai-inference-service.html)
- [Cloudera AI Inference with NVIDIA NIM](https://www.cloudera.com/about/news-and-blogs/press-releases/2024-10-08-cloudera-unveils-ai-inference-service-with-embedded-nvidia-nim-microservices-to-accelerate-genai-development-and-deployment.html)

### The Well & Physics-Informed ML
- [The Well: 15TB Physics Simulation Collection (GitHub)](https://github.com/PolymathicAI/the_well)
- [The Well (arXiv, NeurIPS 2024)](https://arxiv.org/abs/2412.00568)
- [xLSTM: Extended Long Short-Term Memory (arXiv)](https://arxiv.org/abs/2405.04517)
- [xLSTM Official Repository](https://github.com/NX-AI/xlstm)
- [Physics-Informed Neural Networks (Raissi et al.)](https://github.com/maziarraissi/PINNs)
