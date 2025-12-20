# OTel + Metaflow + NiFi Integration Complete

**Date**: 2025-12-20
**Status**: Complete

## Summary

Extended the MetaAgent implementation with operational OTel integration, connecting ArxivDoclingFlow telemetry to NiFi for real-time observability.

## What Was Implemented

### 1. ArxivDoclingFlow OTel Integration
**File**: `src/gaius/flows/docling/flow.py`

Added `TracedFlow` inheritance and `@traced_step` decorators with semantic events:

| Step | Event(s) |
|------|----------|
| start | `paper.processing.started` |
| fetch_pdf | `pdf.extraction.started`, `pdf.extraction.completed` |
| archive_step | `pdf.archived` |
| convert_to_markdown | `docling.conversion.started`, `docling.conversion.completed` |
| score_relevance | `scoring.started`, `scoring.completed` |
| extract_topics | `topics.extraction.started`, `topics.extracted` |
| create_zettelkasten | `zettelkasten.created` |
| end | `paper.processing.completed` |

### 2. OTel Collector NiFi Forwarding
**File**: `devenv.nix`

Added OTLP HTTP exporter to forward traces to NiFi:
```nix
exporters = {
  otlphttp = {
    endpoint = "http://localhost:4319";
    tls.insecure = true;
  };
};
pipelines.traces.exporters = ["debug" "otlphttp"];
```

### 3. EventNames Constants
**File**: `src/gaius/agents/metaagent/telemetry/attributes.py`

Added missing event name constants:
- `SCORING_STARTED`, `SCORING_COMPLETED`, `SCORING_FAILED`
- `ZETTELKASTEN_CREATED`

### 4. TriggerMetaflow NiFi Flow
**File**: `src/gaius/agents/metaagent/nifi/trigger_flow.py`

New flow enabling NiFi to trigger Metaflow executions:

```
GenerateFlowFile (arXiv IDs as JSON)
    │
    ▼
SplitJson (one FlowFile per ID)
    │
    ▼
EvaluateJsonPath (extract arxiv_url)
    │
    ▼
ExecuteStreamCommand (uv run gaius-cli --cmd "/flow run docling ...")
    │
    ├─success─▶ LogAttribute
    └─failure─▶ LogAttribute
```

## Architecture Overview

```
                        OTel Collector
                       ┌──────────────┐
                       │   :4317      │
                       │   (gRPC)     │
                       └──────┬───────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐    ┌───────────┐
        │ Prometheus│   │  Debug   │    │ NiFi OTLP │
        │  :8889   │   │  Logs    │    │   :4319   │
        └──────────┘   └──────────┘    └─────┬─────┘
                                             │
                                             ▼
                                   ┌──────────────────┐
                                   │ RouteOnAttribute │
                                   │ (by step_name)   │
                                   └────────┬─────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    ▼                       ▼                       ▼
             ┌────────────┐          ┌────────────┐          ┌────────────┐
             │Log-start   │          │Log-fetch_pdf│          │Log-end     │
             └────────────┘          └────────────┘          └────────────┘
```

## Verification

Ran end-to-end verification against live NiFi instance:

```
============================================================
MetaAgent NiFi + OTel Integration Verification
============================================================

[OK] NiFi is healthy
[OK] Root process group: 32ddb6ab...
[OK] Created OTel receiving flow: 3934ebc7...
[OK] Created TriggerMetaflow flow: 3934ec44...
```

## Usage

### Run ArXiv Flow with OTel
```bash
uv run gaius-cli --cmd "/flow run docling https://arxiv.org/abs/2312.02149"
```

### View NiFi Flows
```
http://localhost:8450/nifi
```

### Create Custom Trigger Flow
```python
from gaius.agents.metaagent.nifi import (
    create_trigger_metaflow,
    TriggerFlowConfig,
)

async with NiFiClient(config) as client:
    pg_id = await create_trigger_metaflow(
        client,
        parent_id=root_id,
        config=TriggerFlowConfig(
            arxiv_ids=["2312.02149", "2401.12345"],
        ),
    )
```

## Next Steps

1. Configure OTel Collector filter rules to route specific events
2. Add NiFi dashboards for flow monitoring
3. Create BDD scenarios for browser agent using TriggerMetaflow
4. Integrate with evolution daemon for automated paper discovery
