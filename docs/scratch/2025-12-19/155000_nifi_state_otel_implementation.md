# NiFiStateManager and OTel Integration Implementation

**Date**: 2025-12-19
**Status**: Complete

## Summary

Implemented core MetaAgent functionality in three phases per the approved plan:

1. **NiFiStateManager** - Oracle for state capture, comparison, and ground truth management
2. **OTel Instrumentation** - TracedFlow base class, NiFi client tracing, semantic events
3. **NiFi OTel Receiving Flow** - ListenOTLP → RouteOnAttribute → per-step JSON output

## Files Created/Modified

### Phase 1: NiFiStateManager

**New Files:**
- `src/gaius/agents/metaagent/nifi/state.py` - NiFiStateManager class
  - `capture_state()` - Snapshot process group state
  - `compare_states()` - Semantic comparison by name (not position)
  - `clear_process_group()` - Recursive deletion for clean slate
  - Guru Meditation codes: `#NF.00000002.STATECAPTURE`, `#NF.00000003.STATEAPPLY`, `#NF.00000004.CLEARFAILED`

**Extended:**
- `src/gaius/agents/metaagent/nifi/models.py`
  - `ProcessorState` - Processor state with semantic key
  - `ConnectionState` - Connection state with semantic key
  - `FlowState` - Complete process group snapshot
  - `SemanticDiff` - Comparison result with accuracy metrics
  - `ProcessorMismatch`, `ConnectionMismatch` - Detailed diff info

- `src/gaius/agents/metaagent/nifi/client.py`
  - `get_process_group_contents()` - Full contents fetch
  - `list_processors()`, `list_connections()`, `list_child_process_groups()`
  - `delete_processor()`, `delete_connection()`, `delete_process_group()`
  - `drop_connection_queue()`, `stop_processor()`
  - Fixed `create_connection()` to include `groupId` in source/destination

### Phase 2: OTel Instrumentation

**New Package:** `src/gaius/agents/metaagent/telemetry/`

- `__init__.py` - Package exports
- `attributes.py` - Standard OTel attribute names
  - `MetaflowAttrs` - `FLOW_NAME`, `STEP_NAME`, `RUN_ID`, etc.
  - `NiFiAttrs` - `CORRELATION_ID`, `PROCESS_GROUP_ID`, etc.
  - `GaiusAttrs` - Cross-cutting attributes
  - `EventNames` - Semantic event names for `span.add_event()`

- `metaflow_trace.py` - Metaflow tracing
  - `TracedFlow` - Base class with `correlation_id`
  - `@traced_step` - Decorator for step methods

- `nifi_trace.py` - NiFi API tracing
  - `@trace_nifi_operation` - Decorator for NiFi client methods
  - Metrics: `gaius.nifi.api.calls`, `gaius.nifi.api.latency`

**Modified:**
- `src/gaius/agents/metaagent/nifi/client.py` - Added `@trace_nifi_operation` to all public methods

### Phase 3: NiFi OTel Receiving Flow

**New Files:**
- `src/gaius/agents/metaagent/nifi/otel_flow.py`
  - `create_otel_receiving_flow()` - Creates the complete flow
  - `get_otel_flow_status()` - Status check for existing flow
  - `OTelFlowConfig` - Configuration dataclass
  - Guru Meditation code: `#NF.00000005.OTELFLOW`

**Flow Architecture:**
```
ListenOTLP (port 4319)
    │
    ▼
RouteOnAttribute (by metaflow.step_name)
    │
    ├── Log-start
    ├── Log-fetch_pdf
    ├── Log-end
    └── Log-unmatched
```

## Usage Examples

### State Capture and Comparison
```python
from gaius.agents.metaagent.nifi import NiFiStateManager

async with NiFiStateManager(config) as mgr:
    # Capture ground truth
    expected = await mgr.capture_state(process_group_id)

    # After browser agent makes changes...
    actual = await mgr.capture_state(process_group_id)

    # Compare
    diff = mgr.compare_states(expected, actual)
    print(f"Match: {diff.is_match}, Accuracy: {diff.accuracy:.1%}")
```

### Traced Metaflow
```python
from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from metaflow import FlowSpec, step

class ArxivFlow(TracedFlow, FlowSpec):
    @traced_step
    @step
    def fetch_pdf(self):
        self.emit_event("pdf.extraction.started", {"arxiv_id": self.arxiv_id})
        # ...
        self.next(self.end)
```

### Create OTel Flow
```python
from gaius.agents.metaagent.nifi import create_otel_receiving_flow, OTelFlowConfig

async with NiFiClient(config) as client:
    pg_id = await create_otel_receiving_flow(
        client,
        parent_id=root_id,
        config=OTelFlowConfig(
            process_group_name="Metaflow-Telemetry",
            steps_to_route=["start", "fetch_pdf", "end"],
        ),
    )
```

## Verification

All phases verified against running NiFi instance:
- State capture works across nested process groups
- Semantic comparison correctly ignores position
- TracedFlow and @traced_step decorators function
- OTel receiving flow creates complete pipeline with ListenOTLP

## Next Steps

1. Configure OTel Collector to forward to NiFi ListenOTLP port
2. Create sample Metaflow with TracedFlow for end-to-end demo
3. Add filtering in OTel Collector per plan (step-specific events)
