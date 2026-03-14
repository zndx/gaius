# Traceability

`TraceableId` and `DigitalThread` form the traceability spine linking all RASE artifacts. Every model element carries a URI-based identifier that enables cross-model linking, impact analysis, and full audit trails from requirement to training reward.

## TraceableId

A `TraceableId` mirrors the SysML v2 human ID pattern: `<'scheme:path'>`. It is immutable (`frozen=True`) and hashable for use as dict keys and set members.

### URI Schemes

| Scheme | Namespace | Example |
|--------|-----------|---------|
| `bdd` | BDD features, scenarios, steps | `bdd://features/basic_flows#Scenario:CreateFlow` |
| `nifi` | NiFi processors, groups, connections | `nifi://groups/root/processors/abc123` |
| `otel` | OpenTelemetry spans and events | `otel://spans/trace123/span456` |
| `metaflow` | Metaflow runs, steps, tasks | `metaflow://flows/train/runs/42` |
| `rase` | Internal artifacts (results, threads) | `rase://verify/a1b2c3d4e5f6` |
| `som` | Set-of-Mark UI annotations | `som://screenshots/frame42` |
| `tom` | Trace-of-Mark action sequences | `tom://traces/episode7` |

### Factory Methods

```python
from gaius.rase import TraceableId

# BDD scenario
tid = TraceableId.from_bdd("basic_flows", scenario="CreateFlow")
# → bdd://features/basic_flows#Scenario:CreateFlow

# NiFi processor
tid = TraceableId.from_nifi("root", processor_id="abc123")
# → nifi://groups/root/processors/abc123

# Auto-generated with UUID
tid = TraceableId.generate(scheme=IdScheme.RASE, prefix="verify")
# → rase://verify/a1b2c3d4e5f6

# Stable BDD step hash (survives line number changes)
tid = TraceableId.from_bdd_step_hash("flow.feature", "I create a group named 'ETL'")
```

## DigitalThread

A `DigitalThread` captures one complete verification-to-training cycle. It links the full chain:

**Requirement --> Verification Case --> Execution Result --> Evidence --> Training Episode**

```python
from gaius.rase import DigitalThread

thread = DigitalThread(
    requirement_id=req_id,
    verification_case_id=case_id,
    verification_result_id=result_id,
    api_state_before=before_id,
    api_state_after=after_id,
    reward_outcome=0.85,
)
thread.add_evidence(screenshot_id, "screenshot")
thread.add_evidence(span_id, "span")
```

## TraceabilityGraph

The `TraceabilityGraph` collects `TraceabilityLink` objects (directed, typed relationships) and supports queries:

- **Forward trace**: What derives from this requirement?
- **Backward trace**: What requirements does this artifact satisfy?
- **Impact analysis**: What verification cases need re-running if this changes?

Link types follow MBSE semantics: `DERIVES`, `SATISFIES`, `VERIFIES`, `ALLOCATES`, `TRACES`, `REFINES`.

## Source

All traceability infrastructure lives in `src/gaius/rase/traceability.py`.
