# Phase 4: Evaluation Framework for APO

**Date**: 2025-11-30
**Session**: Frontier Model Judging for Synthesis Quality

## Summary

Implemented a comprehensive evaluation framework for Zettelkasten synthesis quality. The system uses frontier models (Claude, Grok, or GPT-4) as judges to score generated notes across multiple dimensions, enabling Automatic Prompt Optimization (APO).

**Supported Judge Backends:**
- **Anthropic** - Claude Sonnet 4 (`claude-sonnet-4-20250514`)
- **XAI** - Grok 3 Mini (`grok-3-mini-beta`)
- **OpenAI** - GPT-4o (`gpt-4o`)

## Architecture

```
/research-eval "query"
       │
       ├──► Hybrid Search (BM25 + Vector + Web)
       │         │
       │         ▼
       │    RRF Fusion
       │         │
       │         ▼
       │    LLM Synthesis (Qwen3)
       │         │
       │         ▼
       │    Zettelkasten Note
       │
       └──► Frontier Judge (Claude/Grok/GPT-4)
            │
            ├── Factual Accuracy (2.0x)
            ├── Citation Quality (1.5x)
            ├── Synthesis Coherence (2.0x)
            ├── Wiki-Link Relevance (1.0x)
            ├── Query Completeness (1.5x)
            └── Conciseness (1.0x)
                  │
                  ▼
            ┌──────────────────────────┐
            │  EvaluationResult        │
            │  ─────────────────       │
            │  - Dimension scores      │
            │  - Overall weighted      │
            │  - Strengths/weaknesses  │
            │  - Improvement hints     │
            └──────────────────────────┘
                  │
                  ▼
            build/dev/evaluations/
            (JSON for APO training)
```

## Evaluation Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| factual_accuracy | 2.0 | Claims supported by sources; no hallucinations |
| citation_quality | 1.5 | Citations relevant, correctly attributed |
| synthesis_coherence | 2.0 | Integrates sources vs mere summarization |
| wiki_link_relevance | 1.0 | [[links]] point to appropriate concepts |
| query_completeness | 1.5 | Thoroughly addresses query intent |
| conciseness | 1.0 | Brief without sacrificing depth |

## Implementation

### New Module: `gaius.inference.evaluation`

```python
from gaius.inference import SynthesisEvaluator, EvaluationResult

# Auto-detects API based on available keys
# Priority: ANTHROPIC_API_KEY > XAI_API_KEY > OPENAI_API_KEY
evaluator = SynthesisEvaluator()

# Or specify backend explicitly
evaluator = SynthesisEvaluator(backend="anthropic")  # Claude
evaluator = SynthesisEvaluator(backend="xai")        # Grok
evaluator = SynthesisEvaluator(backend="openai")     # GPT-4

# Custom model
evaluator = SynthesisEvaluator(backend="xai", judge_model="grok-3-beta")

# Evaluate
result = await evaluator.evaluate(note, sources)
print(f"Overall: {result.overall_score:.2f}/5")
print(f"Judge: {result.judge_model}")

# Save for APO training
result.save()
```

### Key Classes

- `EvaluationDimension`: Name, description, weight for scoring
- `DimensionScore`: Individual dimension score with reasoning
- `EvaluationResult`: Complete evaluation with aggregates
- `SynthesisEvaluator`: Orchestrates judge model evaluation

### Evaluation Storage

Evaluations stored as JSON in `build/dev/evaluations/`:

```json
{
  "note_path": "build/dev/scratch/2025-11-30/053419_byzantine-fault-tolerance.md",
  "query": "Byzantine fault tolerance",
  "evaluated_at": "2025-11-30T05:35:00",
  "dimension_scores": [
    {"dimension": "factual_accuracy", "score": 4, "reasoning": "..."},
    ...
  ],
  "overall_score": 4.2,
  "judge_model": "gpt-4o",
  "strengths": ["Well-integrated sources", "..."],
  "weaknesses": ["Could expand on practical examples"],
  "improvement_suggestions": ["Add more specific use cases"]
}
```

## CLI Commands

```bash
# Research + evaluate in one step (auto-detects backend)
uv run gaius-cli --cmd "/research-eval distributed consensus"

# Specify backend via domain hint
uv run gaius-cli --cmd "/domain eval:anthropic" --cmd "/research-eval topic"
uv run gaius-cli --cmd "/domain eval:xai" --cmd "/research-eval topic"
uv run gaius-cli --cmd "/domain eval:openai" --cmd "/research-eval topic"

# Evaluate existing note
uv run gaius-cli --cmd "/eval scratch/2025-11-30/053419_byzantine-fault-tolerance.md"

# View aggregate statistics
uv run gaius-cli --cmd "/eval-stats"
```

### Environment Variables

| Variable | Backend | Default Model |
|----------|---------|---------------|
| `ANTHROPIC_API_KEY` | Anthropic | `claude-sonnet-4-20250514` |
| `XAI_API_KEY` | XAI | `grok-3-mini-beta` |
| `OPENAI_API_KEY` | OpenAI | `gpt-4o` |

**Auto-detection priority:** Anthropic → XAI → OpenAI

## Files

```
src/gaius/inference/
├── __init__.py      # Added evaluation exports
├── evaluation.py    # NEW: Evaluation framework
├── synthesis.py     # Unchanged
└── client.py        # Unchanged

src/gaius/cli.py     # Added /research-eval, /eval, /eval-stats

pyproject.toml       # Added [eval] dependency group
```

## APO Integration (Next Steps)

The evaluation storage enables future APO:

1. **Collect evaluations**: Run `/research-eval` on diverse queries
2. **Identify patterns**: Analyze dimension scores across evaluations
3. **Optimize prompts**: Use improvement suggestions to refine SYNTHESIS_PROMPT
4. **Iterate**: Re-evaluate with new prompts, compare scores

```python
from gaius.inference import load_evaluations, compute_aggregate_scores

# Load all evaluations
results = load_evaluations()

# Get aggregate scores
agg = compute_aggregate_scores(results)
print(f"Overall avg: {agg['overall']:.2f}")
print(f"Synthesis coherence avg: {agg['synthesis_coherence']:.2f}")

# Identify weak dimensions for prompt improvement
weakest = min(agg.items(), key=lambda x: x[1] if x[0] != 'overall' else 999)
print(f"Weakest: {weakest[0]} ({weakest[1]:.2f})")
```

## Test Results

| Query | Note Created | Wiki Links | Citations | Backend Tested |
|-------|-------------|------------|-----------|----------------|
| Byzantine fault tolerance | ✅ | 7 | 15 | Anthropic (needs credits) |
| machine learning optimization | ✅ | 10 | 15 | OpenAI (needs credits) |
| Raft consensus algorithm | ✅ | 3 | 15 | Anthropic (needs credits) |
| distributed systems consensus | ✅ | 10 | 15 | XAI (needs credits) |

**Knowledge Graph Emergence:** The synthesis pipeline now cites *previous Zettelkasten notes* as sources! For example, "distributed systems consensus" cites:
- `scratch/2025-11-30/052745_raft-consensus-protocol.md`
- `scratch/2025-11-30/051958_distributed-consensus-algorithms.md`
- `scratch/2025-11-30/053419_byzantine-fault-tolerance.md`

This creates an emergent knowledge graph where each new note builds on previous research.

Note: Evaluation requires API credits for the chosen backend.

## Dependencies

```toml
[project.optional-dependencies]
eval = [
    "gaius[search]",
    "anthropic>=0.40.0",
]
```

Install: `uv sync --extra eval`
