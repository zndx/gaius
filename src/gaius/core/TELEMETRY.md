# Gaius Telemetry Strategy

OpenTelemetry (OTel) instrumentation strategy for metrics and distributed tracing. This document covers the **emission side** of telemetry. For the **consumption side** (querying Prometheus), see [observability/README.md](../observability/README.md).

## Current State (2026-01)

### Maturity Assessment

| Aspect | Level | Notes |
|--------|-------|-------|
| **Metrics** | Production | 30+ instruments, comprehensive coverage |
| **Entry-point tracing** | Beta | Command-level spans work |
| **Service tracing** | Alpha | Most services lack span instrumentation |
| **Trace context propagation** | Alpha | Breaks at gRPC/async boundaries |
| **Correlation IDs** | Missing | No request ID threading |

### What Works Today

```
CLI command → traced_command() → span created
             ↓
             gaius.cli/command/domain [span with attributes]
             ↓
             [Service work - NOT TRACED]
             ↓
             Metrics recorded (always)
```

Metrics are comprehensive and production-ready. Tracing provides entry-point visibility but loses context once requests enter services.

## Strategic Direction

### Problem: Deep Event Chains

Consider a typical Gaius workflow:

```
Periodic fetch → returns post with article link
    ↓
Article link fetched → Docling flow
    ↓
Multiple AI API calls (Bytez, local swarm)
    ↓
Content indexed in KB
    ↓
Exchanges recorded in Iceberg HX
    ↓
Insights added to buffer → /sitrep
```

**Current state**: Each stage is invisible. If Bytez fails, we see an error counter increment but can't trace *which* workflow triggered it or what happened before/after.

**Goal**: Follow a single workflow instance through all stages, even across:
- gRPC service boundaries
- Async task spawning
- External API calls (black boxes)
- Federated engine topology

### Three-Tier Tracing Strategy

Rather than instrument everything uniformly, we adopt a selective approach:

#### Tier 1: Always-On Metrics

Every operation records metrics. This is complete and production-ready.

```python
from gaius.engine.metrics import record_exception_caught, record_inference

# Errors are always counted
record_exception_caught(
    component="ambient",
    operation="bytez_analysis",
    exception_type="TimeoutError",
)

# Inference is always metered
record_inference(model="reasoning", latency_ms=150, tokens=500)
```

#### Tier 2: Selective Path Tracing

Instrument specific "debug-worthy" paths with spans. Focus on:

1. **State transitions** - fetch complete, Docling done, KB write
2. **External API calls** - wrap black boxes to measure duration
3. **Service boundaries** - gRPC calls, async task spawning

```python
from gaius.core.telemetry import get_tracer, trace_operation

tracer = get_tracer("gaius.flows")

@trace_operation("docling_extraction")
async def extract_document(url: str, flow_id: str) -> Document:
    with tracer.start_as_current_span("fetch_and_parse") as span:
        span.set_attribute("flow.id", flow_id)
        span.set_attribute("document.url", url)
        # ... extraction logic
```

#### Tier 3: Flow ID Correlation

Pass a `flow_id` through method calls for grep-able logs even when spans break:

```python
import uuid
import logging

logger = logging.getLogger(__name__)

async def process_bookmark(bookmark: XBookmark) -> None:
    flow_id = str(uuid.uuid4())[:8]  # Short for readability

    logger.info(f"[flow:{flow_id}] Starting bookmark processing", extra={"flow_id": flow_id})

    # Pass flow_id to all downstream calls
    article = await fetch_article(bookmark.url, flow_id=flow_id)
    content = await extract_content(article, flow_id=flow_id)
    await index_to_kb(content, flow_id=flow_id)

    logger.info(f"[flow:{flow_id}] Bookmark processing complete")
```

This provides correlation even when:
- OTel tracing fails
- Spans cross async boundaries incorrectly
- External systems don't propagate trace context

## Federated Engine Topology

### Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Home Lab      │    │   LambdaLabs    │    │      AWS        │
│   (Tinybox)     │    │   (H100 Pool)   │    │   (p4d.24xl)    │
│                 │    │                 │    │                 │
│  gaius-engine   │←──→│  gaius-engine   │←──→│  gaius-engine   │
│  :50051         │gRPC│  :50051         │gRPC│  :50051         │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        ↑                      ↑                      ↑
        └──────────────────────┴──────────────────────┘
                         Federated Coordinator
                         (OR-Tools Makespan Scheduler)
```

### Cross-Engine Tracing Requirements

1. **W3C Trace Context** - Propagate `traceparent` header in gRPC metadata
2. **Engine Identity** - Include `engine.location` attribute (home, lambda, aws)
3. **Makespan Correlation** - Link all spans in a makespan to a single `makespan.id`

### gRPC Interceptor Pattern

```python
from opentelemetry.propagate import inject, extract
from opentelemetry import trace

class TracingClientInterceptor(grpc.aio.UnaryUnaryClientInterceptor):
    async def intercept_unary_unary(self, continuation, client_call_details, request):
        tracer = trace.get_tracer("gaius.grpc")

        with tracer.start_as_current_span(
            f"grpc.{client_call_details.method}",
            kind=trace.SpanKind.CLIENT,
        ) as span:
            # Inject trace context into gRPC metadata
            metadata = dict(client_call_details.metadata or [])
            inject(metadata)

            new_details = client_call_details._replace(
                metadata=list(metadata.items())
            )

            return await continuation(new_details, request)
```

### Federated Sampling Strategy

Different sampling rates per location to manage costs:

| Location | Trace Sampling | Rationale |
|----------|---------------|-----------|
| Home Lab | 100% | Low volume, full visibility |
| LambdaLabs | 10% | High volume, sample representative |
| AWS | 1% | Production traffic, minimize overhead |

Configure via environment:

```bash
# Home Lab
export OTEL_TRACES_SAMPLER=always_on

# LambdaLabs
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.1

# AWS Production
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.01
```

## OR-Tools Makespan Tracing

### Scheduler Integration

The AgendaTracker manages makespan operations. Each operation should create a parent span:

```python
from gaius.core.telemetry import get_tracer

tracer = get_tracer("gaius.scheduler")

async def execute_makespan(makespan: Makespan) -> MakespanResult:
    with tracer.start_as_current_span(
        "makespan.execute",
        attributes={
            "makespan.id": str(makespan.id),
            "makespan.operations": len(makespan.operations),
            "makespan.target_endpoints": ",".join(makespan.target_endpoints),
        }
    ) as span:
        for operation in makespan.operations:
            await execute_operation(operation, parent_span=span)
```

### Operation Phases

Each OR-Tools scheduled operation has distinct phases to trace:

```
Makespan
├── allocate_gpus          # OR-Tools resource assignment
├── evict_if_needed        # Preemption decisions
├── start_endpoints        # vLLM process spawning
│   ├── endpoint: reasoning
│   │   ├── process_spawn
│   │   ├── model_load     # ~240s for 70B
│   │   └── health_check
│   └── endpoint: coding
├── execute_workload       # Actual inference
└── restore_baseline       # Return to set points
```

### Black Box Stages

External API calls (Bytez, Anthropic, external search) are "black boxes" - we can't instrument inside them, but we can trace around them:

```python
async def call_bytez_api(content: str, flow_id: str) -> AnalysisResult:
    with tracer.start_as_current_span(
        "external.bytez",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "flow.id": flow_id,
            "external.service": "bytez",
            "external.operation": "analyze",
            "request.size_bytes": len(content),
        }
    ) as span:
        start = time.time()
        try:
            result = await bytez_client.analyze(content)
            span.set_attribute("response.tokens", result.token_count)
            return result
        except Exception as e:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            span.record_exception(e)
            # Also record to metrics for Ops Errors visibility
            record_exception_caught(
                component="flows",
                operation="bytez_api",
                exception_type=type(e).__name__,
            )
            raise
        finally:
            span.set_attribute("duration_ms", int((time.time() - start) * 1000))
```

### Tracing Strategy for API Uncertainty

When black box APIs have variable latency or transient failures:

1. **Timeout spans** - Record timeout as explicit event, not just error
2. **Retry spans** - Each retry is a child span with `retry.attempt` attribute
3. **Circuit breaker state** - Log state transitions as span events

```python
@trace_operation("api_with_retry")
async def call_with_retry(request: Request, flow_id: str) -> Response:
    for attempt in range(3):
        with tracer.start_as_current_span(
            f"attempt.{attempt}",
            attributes={"retry.attempt": attempt, "flow.id": flow_id}
        ) as span:
            try:
                return await make_request(request)
            except TimeoutError:
                span.add_event("timeout", {"attempt": attempt})
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

## Understanding Full W3C Trace Context (Informative)

This section describes the "full" W3C Trace Context implementation - what it entails, why it's intensive, and tactical mitigations. This is informative context for understanding the tracing landscape, not a prescription for Gaius.

### What Full W3C Implementation Requires

The W3C Trace Context specification (W3C, 2023) defines a standard for propagating trace correlation across service boundaries. A complete implementation involves:

#### 1. Context Propagation Layer

Every inter-process communication must inject and extract trace headers:

```
traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
             ├─ version
                ├─ trace-id (128-bit)
                               ├─ parent-id (64-bit)
                                                     └─ flags (sampled)
tracestate: vendor1=value1,vendor2=value2
```

This requires interceptors/middleware for:
- HTTP clients and servers
- gRPC clients and servers
- Message queues (Kafka, RabbitMQ, Redis)
- Database connections (for query tracing)
- Background task spawning (Celery, asyncio tasks)

#### 2. Span Creation Overhead

Every "unit of work" creates a span:

```python
# Full instrumentation creates spans for everything
with tracer.start_as_current_span("db.query") as span:
    with tracer.start_as_current_span("db.connect") as connect_span:
        conn = await pool.acquire()
    with tracer.start_as_current_span("db.execute") as exec_span:
        result = await conn.fetch(query)
    with tracer.start_as_current_span("db.serialize") as serial_span:
        return serialize(result)
```

Each span involves:
- UUID generation (trace_id, span_id)
- Timestamp capture (start, end)
- Attribute storage (key-value pairs)
- Parent-child relationship tracking
- Export to collector

#### 3. Baggage Propagation

W3C Baggage carries application-specific metadata through the entire call chain:

```
baggage: userId=alice,requestId=abc123,tenant=acme
```

Every service must:
- Extract baggage from incoming requests
- Store in context-local storage
- Inject into outgoing requests
- Handle size limits (8KB typical)

#### 4. Auto-Instrumentation Libraries

Full implementation typically relies on auto-instrumentation:

```python
# OpenTelemetry auto-instrumentation wraps libraries
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient

RequestsInstrumentor().instrument()
AsyncPGInstrumentor().instrument()
GrpcInstrumentorClient().instrument()
```

Each instrumented library adds overhead and potential version conflicts.

### Why Full Implementation is Intensive

#### Performance Costs

| Component | Overhead | Notes |
|-----------|----------|-------|
| Span creation | ~1-5μs per span | Adds up with deep call stacks |
| Context propagation | ~0.5μs per boundary | gRPC metadata, HTTP headers |
| Attribute recording | ~0.1μs per attribute | More attributes = more cost |
| Export batching | Background thread | Memory pressure, GC pauses |
| Sampling decision | ~0.1μs per request | Head-based sampling at entry |

For a request that touches 50 spans across 5 services, expect 50-250μs overhead - negligible for most web apps, but significant for:
- High-throughput inference pipelines
- Low-latency trading systems
- Tight loops processing millions of items

#### Cognitive Complexity

Full instrumentation generates massive trace volumes:

```
One user request → 1 trace
  └─ API gateway → 5 spans
      └─ Auth service → 8 spans
          └─ User service → 12 spans
              └─ Database → 20 spans
                  └─ Cache → 15 spans
                      └─ External API → 3 spans

Total: 63 spans for one request
At 1000 RPS: 63,000 spans/second
At 10% sampling: 6,300 spans/second
Storage: ~500 bytes/span = 3.15 MB/second = 270 GB/day
```

Finding the relevant span in this haystack requires sophisticated query tooling.

#### Async Boundary Complexity

Python's asyncio makes context propagation tricky:

```python
# Context is lost when spawning tasks naively
async def handler(request):
    # Current span exists here
    asyncio.create_task(background_work())  # Context NOT propagated!

# Correct approach requires explicit context copying
async def handler(request):
    ctx = context.get_current()
    asyncio.create_task(background_work(ctx))

async def background_work(ctx):
    token = context.attach(ctx)
    try:
        # Now spans link correctly
        ...
    finally:
        context.detach(token)
```

This must be done at every async boundary - `create_task()`, `gather()`, `wait()`, thread pool submissions, process pool submissions.

#### Library Version Matrix

Auto-instrumentation libraries must match both:
- OpenTelemetry SDK version
- Instrumented library version

```
opentelemetry-instrumentation-asyncpg 0.43b0 requires:
  - opentelemetry-api ~= 1.22
  - opentelemetry-instrumentation == 0.43b0
  - asyncpg >= 0.12.0
```

Upgrading asyncpg may break instrumentation. Upgrading OTel may require upgrading all instrumentors simultaneously.

### Tactical Mitigations

#### 1. Selective Instrumentation Over Auto-Instrumentation

Instead of instrumenting everything automatically, instrument explicitly at meaningful boundaries:

```python
# Instead of auto-instrumenting all HTTP calls...
# ...manually instrument the ones that matter

async def fetch_article(url: str, flow_id: str) -> Article:
    # Only this external call gets a span
    with tracer.start_as_current_span(
        "external.fetch",
        attributes={"url.domain": urlparse(url).netloc, "flow.id": flow_id}
    ) as span:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            span.set_attribute("http.status_code", response.status_code)
            return parse_article(response.text)
```

**Trade-off**: Less automatic coverage, but controlled overhead and meaningful spans.

#### 2. Span Filtering at Collector

Use OpenTelemetry Collector processors to drop low-value spans:

```yaml
# otel-collector-config.yaml
processors:
  filter/drop-health-checks:
    spans:
      exclude:
        match_type: regexp
        span_names:
          - "health.*"
          - "metrics.*"
          - "readiness.*"

  filter/drop-short-spans:
    spans:
      exclude:
        match_type: expr
        expressions:
          - duration_nano < 1000000  # Drop spans < 1ms
```

**Trade-off**: Spans are still created (overhead paid), but storage reduced.

#### 3. Tail-Based Sampling

Instead of deciding at request entry whether to sample (head-based), collect all spans and decide at the end based on outcome:

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: errors-policy
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow-traces-policy
        type: latency
        latency: {threshold_ms: 1000}
      - name: probabilistic-policy
        type: probabilistic
        probabilistic: {sampling_percentage: 1}
```

**Trade-off**: Requires buffering all spans temporarily; higher collector memory.

#### 4. Exemplars Instead of Full Traces

Link metrics to trace IDs without storing full traces:

```python
# Record metric with exemplar (trace_id reference)
histogram.record(
    latency_ms,
    attributes={"endpoint": "reasoning"},
    exemplar={"trace_id": span.get_span_context().trace_id}
)
```

When investigating a latency spike in Prometheus, click through to the specific trace that caused it - without storing every trace.

**Trade-off**: Only traces linked from metrics are accessible; no browsing.

#### 5. Correlation ID Logging (Trace-Lite)

The lightest approach: just pass an ID through logs without OTel machinery:

```python
import uuid
import structlog

logger = structlog.get_logger()

async def process_request(request):
    correlation_id = str(uuid.uuid4())[:8]
    log = logger.bind(correlation_id=correlation_id)

    log.info("starting_processing")
    result = await do_work(correlation_id)
    log.info("completed_processing", result_size=len(result))
```

Then grep: `grep "correlation_id=abc123" /var/log/gaius/*.log`

**Trade-off**: No visualization, no timing, but nearly zero overhead.

### Decision Framework

| If you need... | Use... | Overhead |
|---------------|--------|----------|
| Post-mortem debugging | Correlation ID logging | Minimal |
| Latency investigation | Exemplars + selective spans | Low |
| Cross-service visibility | Manual span instrumentation | Medium |
| Full request tracing | Auto-instrumentation + sampling | High |
| Compliance/audit trails | Full instrumentation + 100% sampling | Very High |

### Gaius Position

Gaius adopts a **pragmatic middle ground**:

1. **Always**: Metrics (zero-overhead design, essential for operations)
2. **Default**: Correlation ID in logs (grep-able, minimal overhead)
3. **Selective**: Manual spans at service boundaries and black-box wrappers
4. **Optional**: Full W3C when debugging specific issues (enable via config)

This provides 80% of the debugging value at 20% of the implementation and runtime cost.

## Implementation Priorities

### Phase 1: Foundation (Current)

- [x] Metrics infrastructure (complete)
- [x] Entry-point tracing (complete)
- [ ] Exception recording at all catch sites
- [ ] flow_id convention documented

### Phase 2: Service Layer

- [ ] gRPC client/server interceptors for trace propagation
- [ ] Orchestrator service span instrumentation
- [ ] Scheduler/makespan span instrumentation
- [ ] AgendaTracker operation tracing

### Phase 3: External Integration

- [ ] Black box wrapper pattern for all external APIs
- [ ] Federated engine trace context propagation
- [ ] Cross-engine span linking via `makespan.id`

### Phase 4: Advanced

- [ ] Async context propagation (contextvars)
- [ ] Exemplars (trace IDs in metrics) for Prometheus correlation
- [ ] Baggage propagation for flow metadata

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_SDK_DISABLED` | `false` | Disable all telemetry |
| `OTEL_TRACES_EXPORTER` | `otlp` | Exporter type (otlp, console) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector endpoint |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Sampling strategy |
| `OTEL_TRACES_SAMPLER_ARG` | `0.01` | Sampling rate (1%) |
| `OTEL_SERVICE_NAME` | `gaius-{entry_point}` | Service identifier |

### HOCON Configuration

```hocon
# config/base.conf
telemetry {
  exporter = "otlp"
  exporter = ${?OTEL_TRACES_EXPORTER}

  endpoint = "http://localhost:4317"
  endpoint = ${?OTEL_EXPORTER_OTLP_ENDPOINT}

  service_name = "gaius"

  # Engine-specific: lower sampling for production
  sampling_rate = 0.01  # 1% trace sampling
}
```

## Debugging with OTel

### Finding a Flow

When debugging an issue:

1. **Start with metrics** - Which component shows errors?
   ```bash
   curl 'http://localhost:9090/api/v1/query?query=gaius_gaius_exception_caught_total{component="ambient"}'
   ```

2. **Find flow_id in logs** - Grep for the time window
   ```bash
   grep "flow:" /var/log/gaius/engine.log | grep "2026-01-06T10:3"
   ```

3. **Trace in Jaeger/Tempo** - Search by flow_id attribute
   ```
   flow.id = "a1b2c3d4"
   ```

### Span Naming Conventions

```
gaius.{module}/{operation}
gaius.cli/command/domain
gaius.scheduler/makespan.execute
gaius.orchestrator/endpoint.start
gaius.flows/docling.extract
external.{service}
external.bytez
external.anthropic
```

## See Also

- [observability/README.md](../observability/README.md) - Metric consumption (Prometheus queries)
- [engine/metrics.py](../engine/metrics.py) - Metric definitions
- [engine/services/README.md](../engine/services/README.md) - AgendaTracker, scheduler
- [telemetry.py](./telemetry.py) - Core telemetry module

## References

- Blanco, A., Shkuro, Y., & Parker, D. (2024). *OpenTelemetry in Action*. Manning Publications.
- W3C Trace Context. (2023). https://www.w3.org/TR/trace-context/
- W3C Baggage. (2023). https://www.w3.org/TR/baggage/
- OpenTelemetry Collector Configuration. https://opentelemetry.io/docs/collector/configuration/
- Sridharan, C. (2018). *Distributed Systems Observability*. O'Reilly Media. (Chapter 4: Tracing)

---

<!-- GAI:META
module: gaius.core.telemetry
layer: L1-core
key_types: [TracerProvider, MeterProvider, trace_operation]
key_funcs: [get_tracer, get_meter, init_from_config, traced_command]
depends: [opentelemetry-sdk, opentelemetry-exporter-otlp]
dependents: [engine, health, flows, agents]
config_keys: [telemetry.exporter, telemetry.endpoint, telemetry.service_name, telemetry.sampling_rate]
env_vars: [OTEL_SDK_DISABLED, OTEL_TRACES_EXPORTER, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_TRACES_SAMPLER, OTEL_TRACES_SAMPLER_ARG, OTEL_SERVICE_NAME]
strategic_doc: true
-->
