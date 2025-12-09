# BDD Feature: Content Pipeline with QwQ Reasoning Integration

## Summary

Created a comprehensive BDD feature file for end-to-end testing of the Gaius content pipeline, including:

1. **Content Fetching** - WorkerPool acquires content from real arXiv sources
2. **Content Triage** - Two-stage scoring (heuristic + LLM) with lineage tracking
3. **KB Creation** - Markdown generation with YAML frontmatter
4. **LLM Reflection** - QwQ-32B reasoning with 4-GPU tensor parallel deployment
5. **Swarm Evolution** - Agent optimization using learned content

## Files Created/Modified

### New Files

| File | Purpose |
|------|---------|
| `features/content_pipeline.feature` | Main BDD feature with tiered scenarios |
| `features/steps/content_pipeline_fixtures.py` | Test infrastructure classes |
| `features/steps/content_pipeline_steps.py` | Step definitions |
| `src/gaius/workers/triage.py` | Triage module with heuristic + LLM scoring |

### Modified Files

| File | Change |
|------|--------|
| `config/agents.conf` | Updated QwQ reasoning to use 4-GPU tensor parallel |
| `features/environment.py` | Added pipeline cleanup hooks |

## Test Tier Architecture

| Tier | Tag | Requirements | Purpose |
|------|-----|--------------|---------|
| 1 | `@tier-1` | DB only | Fetch job scheduling, content storage |
| 2 | `@tier-2` | DB + KB | ContentProcessor, markdown generation |
| 3 | `@tier-3` | DB + KB + Inference | LLM triage, fast model |
| 4 | `@tier-4` | Full pipeline | QwQ reasoning, 4-GPU deployment |
| 5 | `@tier-5` | + Evolution | Agent optimization integration |

## Running the Tests

```bash
# Full pipeline (requires all services)
uv run behave features/content_pipeline.feature

# DB-only tests (no inference)
uv run behave --tags="@tier-1,@tier-2" features/content_pipeline.feature

# Skip QwQ tests (faster CI)
uv run behave --tags="~@qwq" features/content_pipeline.feature

# Just evolution tests
uv run behave --tags="@swarm-evolution" features/content_pipeline.feature
```

## QwQ Configuration

Updated `config/agents.conf` for 4-GPU deployment:

```hocon
reasoning {
  model = "Qwen/QwQ-32B"
  backend = "vllm"
  resources {
    gpus = 4                    # 4-GPU tensor parallel for intensive reasoning
    vram-gb = 96                # 24GB x 4 GPUs
    context-length = 131072     # 128K context window
  }
  endpoint {
    port = 8081
    tensor-parallel = 4         # Distribute across 4 GPUs
  }
}
```

## Triage Pipeline

The new triage module implements two-stage content quality assessment:

1. **Heuristic Scoring** (fast, no LLM):
   - Content length (30%)
   - Title quality (20%)
   - Metadata completeness (30%)
   - Source reputation (20%)

2. **LLM Quality Assessment** (via optillm):
   - Relevance, quality, completeness, originality scores
   - Combined with heuristic for final score

Items with combined score >= 50 proceed to KB creation.

## Lineage Tracking

Throughout the pipeline, lineage is tracked:

```
feed_source
    ↓ (fetch)
fetch_job
    ↓ (store)
content_item ──► iceberg_id ──► raw.content (Iceberg HX)
    ↓ (heuristic triage)
triage_assessment (type=heuristic)
    ↓ (LLM triage)
triage_assessment (type=llm)
    ↓ (process)
kb_entry (markdown file)
    ↓ (cognition)
thought
    ↓ (evolution)
training_example ──► agent_version
```
