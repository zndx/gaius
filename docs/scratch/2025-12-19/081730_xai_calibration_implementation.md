# XAI Calibration Integration for NiFi SoM/ToM Dataset Pipeline

## Summary

Implemented XAI frontier calibration with a 6-dimension anchored rubric for the NiFi SoM/ToM dataset generation pipeline. This enables quality assurance and calibration of local LLM-generated instructions against a frontier model (XAI Grok).

## Architecture

### 6-Dimension Rubric

The calibration system uses a weighted rubric with ordinal scores (0-4):

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Intent Understanding | 15% | Does instruction convey clear user intent? |
| SoM Grounding | 20% | Does instruction unambiguously identify target element? |
| Action Semantics | 20% | Is the action type correctly specified? |
| ToM Trace | 15% | Does instruction show awareness of UI state? (4/4 for single actions) |
| Constraints | 15% | Are valid constraints/conditions specified? |
| Outcome | 15% | Does instruction have clear success criteria? |

### Key Components

1. **rubric.py** - Core data structures
   - `RubricDimension` enum
   - `DimensionScore` dataclass with score, evidence, and error_type
   - `RubricScore` with weighted reward calculation
   - Factory functions for single actions and trajectories

2. **prompts/rubric.py** - XAI prompt template
   - System prompt with anchored score descriptions
   - JSON-structured response format
   - Parser for extracting dimension scores

3. **calibration.py** - Orchestration
   - `CalibrationOrchestrator` - Main coordinator
   - `UncertaintySampler` - Stratified sampling with uncertainty weighting
   - `CalibrationRegistry` - Per-dimension and per-type calibration factors
   - Cold start handling (80% budget, uniform sampling until thresholds met)
   - EMA smoothing (α=0.1) for stable factor updates

4. **calibration_store.py** - Iceberg persistence
   - Follows `hx.writer.IcebergContentStore` pattern
   - Storage path: `s3://zndx-gaius/datasets/{dataset_id}/hx/calibration/`
   - Local JSON fallback when Iceberg unavailable
   - Query methods for analysis

### Budget Management

Integrates with existing `EvalBudget` from `tiered_evaluation.py`:
- 50 evaluations/day
- 200 evaluations/week
- Inline sampling: 5% rate with 5/day cap
- Batch calibration: 30 samples per run

### Pipeline Integration

The calibration system integrates at two points:

1. **Inline Calibration** (during generation)
   - InstructionPipeline may call XAI for sampled instructions
   - Results stored in `InstructionCandidate.xai_score`
   - Calibration delta computed and logged

2. **Batch Calibration** (post-generation)
   - `NiFiSoMGenerator._run_batch_calibration()`
   - Stratified sampling across score ranges
   - Bulk XAI evaluation of selected samples

### CLI Flags

```bash
# Enable XAI calibration with 6-dimension rubric
--enable-calibration

# Sample rate for XAI calibration (default: 0.1 = 10%)
--calibration-sample-rate 0.1

# Export calibration history to Iceberg in S3
--export-calibration
```

## Files Created

- `src/gaius/datasets/nifi_som/rubric.py`
- `src/gaius/datasets/nifi_som/prompts/rubric.py`
- `src/gaius/datasets/nifi_som/calibration.py`
- `src/gaius/datasets/nifi_som/calibration_store.py`

## Files Modified

- `src/gaius/datasets/nifi_som/quality.py` - Updated to use EvalBudget
- `src/gaius/datasets/nifi_som/llm_instructions.py` - Added inline calibration
- `src/gaius/datasets/nifi_som/generator.py` - Added calibration CLI flags and metadata flow
- `src/gaius/datasets/nifi_som/prompts/__init__.py` - Added rubric exports

## Testing

End-to-end pipeline verified:
- Generator initialization with calibration enabled ✓
- CalibrationOrchestrator creates correctly ✓
- CalibrationStore works with local fallback ✓
- Metadata flows through to Magma export ✓

## Usage Example

```python
from gaius.datasets.nifi_som.generator import NiFiSoMGenerator

gen = NiFiSoMGenerator(
    use_llm=True,                    # LLM-powered instruction generation
    enable_calibration=True,         # XAI calibration enabled
    calibration_sample_rate=0.1,     # 10% sample rate
    export_calibration=True,         # Export to Iceberg
)

examples = await gen.run(export=True)
```

## Next Steps

1. Integration testing with actual XAI Grok endpoint
2. Calibration factor training from accumulated samples
3. Local verifier fine-tuning using calibration data
