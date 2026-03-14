# FMEA Framework

FMEA (Failure Mode and Effects Analysis) replaces simple severity classification with quantitative risk assessment. Originally from manufacturing engineering, Gaius adapts it for software systems.

## Risk Priority Number

Each failure mode is scored on three dimensions:

**RPN = S x O x D** (range 1-1000)

| Dimension | Meaning | Scale |
|-----------|---------|-------|
| **S** (Severity) | Impact on system availability | 1 (negligible) to 10 (total failure) |
| **O** (Occurrence) | Probability of recurrence | 1 (rare) to 10 (frequent) |
| **D** (Detection) | Ability to detect before impact | 1 (always caught) to 10 (invisible) |

Higher RPN means higher risk. The worst possible score (10 x 10 x 10 = 1000) indicates a severe, frequent, and invisible failure.

## Action Thresholds

| RPN Range | Tier | Action |
|-----------|------|--------|
| 1-100 | Tier 0 | Automatic procedural remediation |
| 101-200 | Tier 1 | Agent-assisted remediation |
| 201-400 | Tier 2 | Requires user approval |
| 401-1000 | Manual | Human intervention required |

### Conservative Overrides

Certain conditions always escalate regardless of RPN:
- **Detection >= 8**: Poor observability requires approval
- **Safety level DESTRUCTIVE**: Data-modifying actions require approval
- **Multiple correlated failures**: Escalate to next tier

## Failure Mode Catalog

34 failure modes across 7 categories:

### GPU (6 modes)

| ID | Failure Mode | S | O | D | RPN |
|----|-------------|---|---|---|-----|
| GPU_001 | Memory Exhaustion | 8 | 6 | 4 | 192 |
| GPU_002 | Temperature Critical | 9 | 3 | 2 | 54 |
| GPU_003 | Hardware Error | 10 | 2 | 3 | 60 |
| GPU_004 | Driver Crash | 8 | 3 | 4 | 96 |
| GPU_005 | Memory Fragmentation | 7 | 5 | 4 | 140 |
| GPU_006 | Power Throttling | 5 | 4 | 3 | 60 |

### vLLM Endpoint (6 modes)

| ID | Failure Mode | S | O | D | RPN |
|----|-------------|---|---|---|-----|
| VLLM_001 | Stuck Starting | 6 | 5 | 5 | 150 |
| VLLM_002 | Stuck Stopping | 4 | 4 | 4 | 64 |
| VLLM_003 | Health Check Failure | 7 | 6 | 3 | 126 |
| VLLM_004 | Orphan Process | 5 | 5 | 4 | 100 |
| VLLM_005 | OOM Crash | 8 | 5 | 3 | 120 |
| VLLM_006 | KV-Cache Exhaustion | 5 | 6 | 5 | 150 |

### Model Quality (5 modes)

| ID | Failure Mode | S | O | D | RPN |
|----|-------------|---|---|---|-----|
| MQ_001 | Hallucination Increase | 7 | 4 | 6 | 168 |
| MQ_002 | Latency Degradation | 4 | 5 | 3 | 60 |
| MQ_003 | Output Quality Drift | 5 | 6 | 7 | 210 |
| MQ_004 | Semantic Drift | 6 | 4 | 8 | 192 |
| MQ_005 | Context Exhaustion | 6 | 5 | 4 | 120 |

### Emergent Behavior (4 modes)

| ID | Failure Mode | S | O | D | RPN |
|----|-------------|---|---|---|-----|
| EB_001 | Swarm Consensus Failure | 6 | 4 | 6 | 144 |
| EB_002 | Cognition Loop | 5 | 4 | 7 | 140 |
| EB_003 | Embedding Drift | 6 | 5 | 8 | 240 |
| EB_004 | Self-Observation Bias | 6 | 5 | 9 | 270 |

Note: Emergent behavior modes have high Detection scores (poor observability), reflecting the inherent difficulty of detecting these failure modes automatically.

## Adaptive Learning

The system adjusts S/O/D scores based on remediation outcomes using exponential moving average (alpha = 0.2):

- **Successful fast fix**: Occurrence decreases (problem is manageable)
- **Failed fix**: Occurrence increases (problem is more persistent than estimated)
- **User-reported**: Detection increases (automated checks missed it)
- **Early detection**: Detection decreases (automated checks caught it)

## CLI Commands

```bash
# FMEA summary with current RPN scores
uv run gaius-cli --cmd "/fmea" --format json

# Failure mode catalog
uv run gaius-cli --cmd "/fmea catalog" --format json

# Detail for specific failure mode
uv run gaius-cli --cmd "/fmea detail GPU_001" --format json

# Recent incidents
uv run gaius-cli --cmd "/fmea history" --format json
```
