# MetaAgent Multi-Agent Debate Implementation

**Date**: 2026-01-19
**Status**: Complete

## Overview

Implemented actual LLM-powered audit analysis using Multi-Agent Debate architecture - the first truly agentic implementation in Gaius. This SOTA pattern overcomes "Degeneration-of-Thought" where single-agent systems become overconfident.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Multi-Agent Debate Flow                          │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Phase 1: Data Gathering (No LLM)                                     │
│   SQL queries → GPU health, endpoints, evolution metrics             │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Phase 2: Initial Analysis (Cerebras GLM 4.7 - Fast)                  │
│   ANALYST role → First-pass findings and recommendations             │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Phase 3: Skeptic Critique (XAI Grok - High Quality)                  │
│   SKEPTIC role → Challenges assumptions, identifies weak evidence    │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Phase 4: Actionability Validation (Cerebras - Fast)                  │
│   ACTIONABILITY_CRITIC → Validates commands are executable           │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Phase 5: Judge Synthesis (XAI Grok - High Quality)                   │
│   JUDGE role → Final verdict weighing analyst vs skeptic             │
└─────────────────────────────────────────────────────────────────────┘
```

## Files Created/Modified

### Created

#### `src/gaius/engine/services/metaagent_debate.py` (NEW)
Core Multi-Agent Debate coordinator implementing:
- `MetaAgentDebateCoordinator` - Orchestrates the 5-phase debate
- `DebateTranscript` - Records each phase's output with exchange IDs
- `DebateResult` - Final findings, recommendations, and metadata
- Role-specific system prompts for each agent

### Modified

#### `src/gaius/agents/roles.py`
Added three new debate-specific roles:
- `SKEPTIC` - Adversarial reviewer challenging assumptions
- `ACTIONABILITY_CRITIC` - Validates recommendations are executable
- `JUDGE` - Synthesizes balanced verdict from debate

#### `src/gaius/engine/services/metaagent_service.py`
- Replaced placeholder `_run_audit_analysis()` with debate implementation
- Added `json.dumps()` serialization for JSONB column (bug fix)
- Added KB artifact storage for debate transcripts

## HX Exchange Tracking Verification

Confirmed 4 LLM exchanges captured in Iceberg via MinIO:

```
2026-01-19 18:21:57 | xai      | grok-4-1-fast | metaagent_judg...      (Phase 5)
2026-01-19 18:21:48 | cerebras | zai-glm-4.7   | metaagent...           (Phase 4)
2026-01-19 18:21:45 | xai      | grok-4-1-fast | metaagent_skep...      (Phase 3)
2026-01-19 18:21:37 | cerebras | zai-glm-4.7   | metaagent...           (Phase 2)
```

Each exchange includes:
- `source_context` with agent_alias, task_type, parent_run_id
- `request_hash` for deduplication/lineage
- `exchange_id` for linking to KB artifacts

## Budget Strategy

**Quality-First**: Uses Cerebras for fast phases, XAI Grok for critical phases (Skeptic & Judge).

| Phase | Provider | Model | Rationale |
|-------|----------|-------|-----------|
| 2 | Cerebras | zai-glm-4.7 | Fast initial pass |
| 3 | XAI | grok-4-1-fast | High-quality critique |
| 4 | Cerebras | zai-glm-4.7 | Fast validation |
| 5 | XAI | grok-4-1-fast | High-quality synthesis |

Estimated: ~4 LLM calls per audit, ~18K tokens, ~$0.20/audit

## Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#MA.DEBATE.00000001.GATHERINGFAIL` | Data gathering phase failed |
| `#MA.DEBATE.00000002.ANALYSISFAIL` | Initial analysis phase failed |
| `#MA.DEBATE.00000003.SKEPTICFAIL` | Skeptic critique phase failed |
| `#MA.DEBATE.00000004.CRITICFAIL` | Actionability validation failed |
| `#MA.DEBATE.00000005.JUDGEFAIL` | Judge synthesis failed |
| `#MA.DEBATE.00000006.NOXAI` | XAI backend not available |
| `#MA.DEBATE.00000007.NOCEREBRAS` | Cerebras backend not available |

## Type Checking

All modified files pass type checking:
```bash
ty check src/gaius/engine/services/metaagent_debate.py
ty check src/gaius/engine/services/metaagent_service.py
ty check src/gaius/agents/roles.py
# Only pre-existing utcnow() deprecation warnings
```

## Testing

### Initialization Test
```bash
uv run python -c "
from gaius.engine.services.metaagent_debate import get_debate_coordinator
coordinator = get_debate_coordinator(pool=None, parent_run_id='test-123')
print(f'Coordinator initialized: {coordinator}')
print(f'Has XAI: {coordinator._xai_available}')
print(f'Has Cerebras: {coordinator._cerebras_available}')
"
# PASSED - XAI and Cerebras both available
```

### Full Debate Test
The Multi-Agent Debate executed successfully:
- 4 LLM calls made (2 Cerebras, 2 XAI)
- All exchanges captured in HX Iceberg table
- Debate transcript generated

## Known Limitations

1. **Database persistence**: The `health_incidents` table doesn't exist, causing a warning in `_get_system_context()`. This is pre-existing and doesn't affect the debate flow.

2. **KB artifact linking**: The `link_kb_artifact()` call happens after KB write but before the response returns. Could be made async for better latency.

## Usage

The Multi-Agent Debate runs automatically during weekly audits via MetaAgentService. It can also be triggered manually:

```python
from gaius.engine.services.metaagent_debate import get_debate_coordinator

coordinator = get_debate_coordinator(pool=db_pool, parent_run_id="audit-123")
result = await coordinator.run_debate(scope="full")

# Result contains:
# - findings: List[Finding] with severity, category, evidence
# - recommendations: List[Recommendation] with suggested_implementation
# - transcript: DebateTranscript with all phases recorded
# - exchange_ids: List[str] for HX lineage
```

---
*Generated by Code Quality Agent*
