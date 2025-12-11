# OTel Span Facts Architecture for Health Watch

Designed and implemented a simplified OTel observation system using "span facts" -
discrete events that can be pattern-matched without parsing complex span hierarchies.

## The Problem

Raw OTel spans are hard to parse for pattern matching:
- Hierarchical parent-child relationships across services
- Attributes scattered across many spans
- Temporal relationships are implicit
- Full RETE-style pattern matching would be complex

Your CDR/call bridge experience is directly relevant - events over time with participant
state changes, multiple parties, external services. Federated engines will have similar
complexity.

## Solution: Span Facts

Instead of parsing span trees, we flatten span activity into discrete **facts**:

```python
@dataclass
class SpanFact:
    timestamp: float
    event_type: str  # span_start, span_end, event, attribute_set
    span_name: str
    attributes: dict[str, Any]
    trace_id: str | None
    parent_span: str | None
```

Facts are like CDR events:
- **Timestamp**: When it occurred
- **Event type**: What happened (span start/end, event, attribute set)
- **Span name**: The operation name
- **Attributes**: Key-value context

## Pattern Matching

Simple regex-based patterns (not full RETE, but sufficient for v1):

```python
@dataclass
class FactPattern:
    event_type: str | None          # Match specific event type
    span_name: str | None           # Regex to match span name
    attribute_patterns: dict[str, str] | None  # key -> regex
    indicates: ObservationType
    description: str
```

Standard patterns detect:
- `implementation.status = "stub"` → STUB
- `fallback.used = true` → FALLBACK
- `event.name = "legacy_fallback"` → LEGACY
- `event.name = "exception_caught"` → EXCEPTION_CAUGHT

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       CommandWatcher                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐   │
│  │ LogCapture  │   │ Stdout/Err  │   │ SpanFactCollector   │   │
│  │  Handler    │   │   Capture   │   │                     │   │
│  └──────┬──────┘   └──────┬──────┘   └──────────┬──────────┘   │
│         │                 │                      │              │
│         ▼                 ▼                      ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Pattern Matching Engine                      │  │
│  │                                                           │  │
│  │  Log Patterns (regex)     Span Patterns (FactPattern)    │  │
│  │  - LEGACY_FALLBACK        - implementation.status=stub   │  │
│  │  - (stub)                 - fallback.used=true           │  │
│  │  - not implemented        - event.name=legacy_fallback   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│                       WatchResult                               │
│                    - observations[]                             │
│                    - span_facts[]                               │
└─────────────────────────────────────────────────────────────────┘
```

## Instrumentation Helpers

Code can emit standard span events for watchability:

```python
from gaius.health.watcher import emit_stub_event, emit_fallback_event

with tracer.start_as_current_span("evolution.start") as span:
    emit_stub_event(span, "StartEvolution", "gRPC endpoint not wired")
    return {"started": True}  # stub response

with tracer.start_as_current_span("scheduler.submit") as span:
    if not engine_available:
        emit_fallback_event(span, "submit", "direct_scheduler", "engine unreachable")
        return direct_scheduler.submit(job)
```

Available helpers:
- `emit_stub_event(span, operation, reason)` - Mark stub implementation
- `emit_fallback_event(span, operation, fallback_to, reason)` - Mark fallback use
- `emit_legacy_fallback(span, component, tech_debt_note)` - Mark legacy code path
- `emit_exception_caught(span, exc, continued)` - Mark handled exception

## Future Enhancements

### 1. Temporal Patterns

For federated engines, we'll need patterns that match across time:

```python
# Pattern: "If span A starts, then B must complete within 5s"
temporal_pattern = TemporalPattern(
    trigger=FactPattern(event_type="span_start", span_name="engine.request"),
    expect=FactPattern(event_type="span_end", span_name="engine.response"),
    within_ms=5000,
    indicates=ObservationType.TIMEOUT,
)
```

### 2. Cross-Trace Correlation

For federated scenarios with multiple engines:

```python
# Track facts by trace_id for multi-party correlation
collector.correlate_traces(["trace_a", "trace_b"])
```

### 3. Heuristic-Driven Patterns

Load patterns from heuristic KB entries:

```yaml
# In heuristics/gaius/evolution/daemon_not_running.md
span_patterns:
  - event_type: attribute_set
    span_name: evolution.*
    attribute_patterns:
      implementation.status: stub
    indicates: stub
    description: Evolution gRPC endpoint is stub
```

## Files Changed

| File | Changes |
|------|---------|
| `src/gaius/health/watcher.py` | Added SpanFact, FactPattern, SpanFactCollector, InstrumentedSpan/Tracer, emit_* helpers |

## Testing

```bash
# Watch a command (log patterns work, span patterns need instrumented code)
uv run gaius-cli --cmd "/health watch /scheduler status" --format json

# Output shows spans: null until code uses emit_* helpers
```

## The CDR Analogy

| CDR Concept | Span Fact Equivalent |
|-------------|---------------------|
| Call leg | Span |
| Participant join/leave | span_start/span_end |
| DTMF event | add_event("dtmf", ...) |
| Transfer | event with parent correlation |
| External TTS | Federated engine span |
| Speaker ID | Span attributes |

The key insight is that we don't need to reconstruct the full "call state" (span tree) -
we just need to detect problematic patterns in the event stream.
