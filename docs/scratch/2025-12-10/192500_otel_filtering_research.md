# OTel Stream Filtering for Health Watch

Research on methods to filter the OTel stream before it reaches the health watch command, reducing verbosity and focusing on relevant patterns.

## Problem

OTel generates verbose telemetry. The `/health watch` command knows what patterns it's looking for beforehand (stubs, fallbacks, exceptions). We should filter early to avoid processing irrelevant spans.

## Filtering Approaches

### 1. SDK-Level: Custom SpanProcessor (Recommended for Watch)

Create a filtering SpanProcessor that only collects spans matching watch criteria:

```python
from opentelemetry.sdk.trace import SpanProcessor, ReadableSpan

class WatchFilteringProcessor(SpanProcessor):
    """Only process spans relevant to health watch patterns."""

    def __init__(self, collector: SpanFactCollector, filters: list[SpanFilter]):
        self._collector = collector
        self._filters = filters

    def on_end(self, span: ReadableSpan):
        # Early exit if span doesn't match any filter
        if not self._matches_any_filter(span):
            return

        # Convert to SpanFact and collect
        self._collector.on_span_from_readable(span)

    def _matches_any_filter(self, span: ReadableSpan) -> bool:
        for f in self._filters:
            if f.matches(span):
                return True
        return False
```

**Filters can match on:**
- Span name patterns (regex): `gaius\..*`
- Attribute existence: `has_attr("implementation.status")`
- Attribute values: `attr("fallback.used") == "true"`
- Entry point: `attr("gaius.entry_point") == "cli"`

### 2. SDK-Level: Custom Sampler

For probabilistic filtering or dropping entire traces:

```python
from opentelemetry.sdk.trace.sampling import Sampler, Decision, SamplingResult

class WatchSampler(Sampler):
    """Sample only spans we care about watching."""

    def __init__(self, watch_patterns: list[str]):
        self._patterns = [re.compile(p) for p in watch_patterns]

    def should_sample(self, parent_context, trace_id, name, kind, attributes, links):
        # Check if span name matches any watch pattern
        for pattern in self._patterns:
            if pattern.search(name):
                return SamplingResult(Decision.RECORD_AND_SAMPLE)

        # Drop spans we don't care about
        return SamplingResult(Decision.DROP)
```

**Limitation**: Samplers decide at span START, before most attributes are set.

### 3. Filtering Exporter Wrapper

Wrap the exporter to filter at export time:

```python
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

class FilteringExporter(SpanExporter):
    """Filters spans before delegating to real exporter."""

    def __init__(self, exporter: SpanExporter, predicate: Callable[[ReadableSpan], bool]):
        self._exporter = exporter
        self._predicate = predicate

    def export(self, spans):
        filtered = [s for s in spans if self._predicate(s)]
        if filtered:
            return self._exporter.export(filtered)
        return SpanExportResult.SUCCESS
```

### 4. Collector-Level: Filter Processor (For Production)

Use OTel Collector's filter processor with OTTL:

```yaml
processors:
  filter/watch:
    traces:
      span:
        # Keep only spans with watch-relevant attributes
        - 'attributes["implementation.status"] != nil'
        - 'attributes["fallback.used"] != nil'
        - 'IsMatch(name, "gaius\\..*")'
```

**Pros**: Filters before network transmission, reduces bandwidth
**Cons**: Requires running a collector

## Recommended Architecture for `/health watch`

```
┌─────────────────────────────────────────────────────────────────────┐
│                    /health watch /evolve start                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. Parse watch targets from command:                                │
│     - Span name patterns: ["gaius.cli/command/evolve", "evolve.*"]  │
│     - Attribute filters: ["implementation.status", "fallback.used"] │
│                                                                      │
│  2. Create WatchSpanProcessor with filters                          │
│     ┌──────────────────────────────────────────────────────────┐    │
│     │ WatchSpanProcessor                                        │    │
│     │   filters: [SpanNameFilter, AttributeExistsFilter]       │    │
│     │   collector: SpanFactCollector                           │    │
│     │                                                          │    │
│     │   on_end(span):                                          │    │
│     │     if not matches_filters(span): return  # EARLY EXIT   │    │
│     │     collector.add_fact(span)                             │    │
│     └──────────────────────────────────────────────────────────┘    │
│                                                                      │
│  3. Execute command with filtered processor active                   │
│                                                                      │
│  4. Pattern match only on collected (pre-filtered) facts            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Filter Types for Watch Command

```python
@dataclass
class SpanFilter:
    """Base filter for watch command."""
    pass

@dataclass
class SpanNameFilter(SpanFilter):
    """Match span names by regex."""
    pattern: str

    def matches(self, span: ReadableSpan) -> bool:
        return bool(re.search(self.pattern, span.name))

@dataclass
class AttributeExistsFilter(SpanFilter):
    """Match spans with specific attribute keys."""
    keys: list[str]

    def matches(self, span: ReadableSpan) -> bool:
        attrs = span.attributes or {}
        return any(k in attrs for k in self.keys)

@dataclass
class AttributeValueFilter(SpanFilter):
    """Match spans with specific attribute values."""
    key: str
    value_pattern: str

    def matches(self, span: ReadableSpan) -> bool:
        attrs = span.attributes or {}
        if self.key not in attrs:
            return False
        return bool(re.search(self.value_pattern, str(attrs[self.key])))

@dataclass
class EntryPointFilter(SpanFilter):
    """Match spans from specific entry points."""
    entry_points: list[str]  # ["cli", "mcp", "tui"]

    def matches(self, span: ReadableSpan) -> bool:
        attrs = span.attributes or {}
        ep = attrs.get("gaius.entry_point", "")
        return ep in self.entry_points
```

## Default Watch Filters

For the common case of watching for implementation issues:

```python
DEFAULT_WATCH_FILTERS = [
    # Watch for any span with implementation status
    AttributeExistsFilter(keys=["implementation.status"]),
    # Watch for fallback usage
    AttributeExistsFilter(keys=["fallback.used"]),
    # Watch for exception events
    AttributeValueFilter(key="otel.status_code", value_pattern="ERROR"),
    # Watch for our specific span events
    SpanNameFilter(pattern=r"gaius\.(cli|mcp|tui|engine|worker)/"),
]
```

## CLI Integration

```bash
# Watch with default filters (stubs, fallbacks, errors)
/health watch /evolve start

# Watch with custom span name filter
/health watch --filter "name:evolve.*" /evolve start

# Watch with attribute filter
/health watch --filter "attr:implementation.status" /evolve start

# Watch specific entry point only
/health watch --entry-point cli /evolve start
```

## Sources

- [OpenTelemetry Sampling, Filtering, Enrichment](https://last9.io/blog/opentelemetry-configurations-filtering-sampling-enrichment/)
- [OpenTelemetry Collector Filter Processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/filterprocessor/README.md)
- [Transforming Telemetry](https://opentelemetry.io/docs/collector/transforming-telemetry/)
- [OTel SDK Trace Specification](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/trace/sdk.md)
