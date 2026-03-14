# ThetaAgent - Neuromorphic Situational Awareness

ThetaAgent provides Gaius's single pane of glass for daily situational awareness via `/sitrep`. Grounded in Attention Schema Theory (AST), it models attention as an oscillatory process using theta rhythm dynamics to detect when cross-temporal knowledge linking is needed.

## Purpose

ThetaAgent serves two complementary functions:

| Function | Command | Description |
|----------|---------|-------------|
| **SITREP** | `/sitrep [day\|week\|quarter\|open]` | Synthesize objectives, thoughts, agenda, health, evolution |
| **Consolidation** | `/theta consolidate` | NVAR-mediated KB augmentation with wikilinks and action links |

The core insight: the brain consolidates memories during theta oscillations (4-8Hz). ThetaAgent uses NVAR dynamics to detect "semantic drift" in the KB embedding space, triggering consolidation when predicted and actual temporal centroids diverge.

## Architecture

ThetaAgent follows the Engine-First pattern where gRPC is the primary transport:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MCP Tools                                      │
│                                                                          │
│     theta_sitrep          theta_consolidate      theta_consolidation_stats│
│           │                      │                        │              │
└───────────┼──────────────────────┼────────────────────────┼──────────────┘
            │                      │                        │
            ▼                      ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        GaiusServicer (gRPC)                              │
│                                                                          │
│   ThetaSitrep()        ThetaConsolidate()      ThetaConsolidationStats() │
│         │                      │                        │                │
│         └──────────────────────┼────────────────────────┘                │
│                                ▼                                         │
│                  ┌────────────────────────┐                              │
│                  │     ThetaService       │ ← BaseDaemon protocol        │
│                  │   (Engine-First)       │                              │
│                  └───────────┬────────────┘                              │
│                              │                                           │
│                              ▼                                           │
│                  ┌────────────────────────┐                              │
│                  │     ThetaAgent         │ ← Implementation             │
│                  │  (Lazy-initialized)    │                              │
│                  └───────────┬────────────┘                              │
│                              │                                           │
│         ┌────────────────────┼────────────────────┐                     │
│         ▼                    ▼                    ▼                     │
│  ┌─────────────┐    ┌─────────────────┐   ┌──────────────┐             │
│  │ThetaDynamics│    │SubsumptionInfer │   │KnowledgeGrad │             │
│  │   (NVAR)    │    │   (BERTSubs)    │   │   Policy     │             │
│  └─────────────┘    └─────────────────┘   └──────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
```

## gRPC Service Definition

```protobuf
// ThetaAgent situational awareness
rpc ThetaSitrep(ThetaSitrepRequest) returns (ThetaSitrepResponse);
rpc ThetaConsolidate(ThetaConsolidateRequest) returns (ThetaConsolidateResponse);
rpc ThetaConsolidationStats(ThetaConsolidationStatsRequest) returns (ThetaConsolidationStatsResponse);
```

## SITREP Generation

The `/sitrep` command generates a situational awareness report synthesizing:

1. **System Health** - GPU count, endpoint status, overall health
2. **Priorities** - Agenda items aggregated from projects, filtered by horizon
3. **Thoughts** - Recent cognition outputs with action link detection
4. **Objectives** - RASE verification status and progress
5. **Evolution** - Daemon status, next agent, improvement metrics
6. **Quick Actions** - Context-sensitive suggested commands

### Temporal Horizons

| Horizon | Scope | Typical Use |
|---------|-------|-------------|
| `day` | Today's agenda, immediate priorities | Daily standup |
| `week` | Week's objectives, near-term goals | Sprint planning |
| `quarter` | Quarterly OKRs, strategic initiatives | Roadmap review |
| `open` | All tracked items, unbounded view | Comprehensive audit |

### Usage

```bash
# CLI
uv run gaius-cli --cmd "/sitrep day" --format json

# MCP Tool
result = await theta_sitrep(horizon="day")
```

## NVAR Dynamics

ThetaAgent uses Next Generation Reservoir Computing (NGRC) via ReservoirPy NVAR to compute consolidation signals from KB embedding time series.

### Academic Foundation (Gauthier et al. 2021)

NVAR extracts nonlinear features via delay embedding + polynomial expansion:

```
Features: [x_{t-k}, ..., x_{t-1}, x_t, x_{t-k}*x_{t-k+1}, ...]

Training: W_out = (X^T X + αI)^{-1} X^T Y  (ridge regression)
Prediction: y_pred = features @ W_out
```

### Consolidation Signal

The signal measures semantic drift between predicted and actual embedding centroids:

```python
drift = ||predicted_centroid - actual_centroid||_2
urgency = tanh(drift * scale)  # Bounded [0, 1]
```

When `urgency > 0.5`, consolidation is triggered to strengthen cross-temporal links.

### Dimensionality Reduction

Full 768-dim embeddings with polynomial features would be intractable. ThetaDynamics uses incremental PCA to reduce to 32 components before NVAR processing:

```
768-dim centroid → PCA → 32-dim → NVAR → prediction → PCA^{-1} → 768-dim
```

### Configuration

```python
ThetaDynamics(
    k=4,                    # Delay (number of historical slices)
    polynomial_order=2,     # Feature expansion order
    drift_scale=1.0,        # Scaling for drift → urgency
    ridge_alpha=1e-6,       # Regularization strength
    reduced_dim=32,         # PCA dimensionality
)
```

**Reference**: Gauthier, D.J., Bollt, E., Griffith, A., Barbosa, W.A.S. (2021). Next Generation Reservoir Computing. *Nature Communications*, DOI: 10.1038/s41467-021-25801-2

## Knowledge Gradient Policy

ThetaAgent uses the Knowledge Gradient (KG) from Optimal Learning (Powell & Ryzhov, 2012) to provide economic justification for subsumption verification decisions.

### The KG Formula

```
KG(x) = E[max_{x'} μ^{n+1}_{x'} | x^n = x] - max_{x'} μ^n_{x'}
```

Where:
- `μ^n_x` = Current belief about value of alternative x
- `μ^{n+1}_x` = Updated belief after measuring x

### Implementation

```python
KG(x) = σ_tilde(x) * f(z(x))

where:
    σ_tilde = sqrt(σ²_x * σ²_ε / (σ²_x + σ²_ε))  # Variance reduction
    z = (μ_x - μ*) / σ_tilde                       # Normalized improvement
    f(z) = z*Φ(z) + φ(z)                          # KG factor (Frazier et al. 2009)
```

### Candidate Selection

The policy selects candidates in order of decreasing KG value:

```python
kg_policy.select_candidates(
    candidates=subsumption_candidates,
    max_candidates=10,
    budget=None,  # Or limit by measurement cost
)
```

### Research Mode

During initial development, `research_mode=True` bypasses the cost threshold to:
1. Build measurement infrastructure (SHAP, holdout testing)
2. Calibrate belief state against empirical retrieval quality
3. Characterize cost function (GPU cycles, latency, tokens)

**References**:
- Powell, W.B. & Ryzhov, I.O. (2012). *Optimal Learning*. Wiley.
- Frazier, P., Powell, W., Dayanik, S. (2009). The Knowledge-Gradient Policy for Correlated Normal Beliefs. *INFORMS Journal on Computing*.

## BERTSubs Subsumption Inference

ThetaAgent uses DeepOnto's BERTSubs for ontology-aware subsumption inference.

### Pipeline

1. **Generate OWL Ontology** - Extract concepts from KB frontmatter, wikilinks, entities
2. **Load into DeepOnto** - Validate with owlready2 and deeponto loaders
3. **Infer Subsumptions** - BERTSubs predicts `SubClass ⊑ SuperClass` relationships
4. **Filter by Confidence** - Default threshold 0.8

### Ontology Generation

```python
path, validation = generate_ontology_from_kb(
    kb_root=Path("build/dev"),
    output_path=Path(".cache/ontology/kb_current.owl"),
    slice_id="2025-W52",  # Optional temporal filter
    validate=True,        # Enforce validation feedback loop
)
```

### Usage

```python
inferencer = agent.get_subsumption_inferencer(slice_id="2025-W52")
candidates = await inferencer.infer_subsumptions(
    candidates=[("kudu", "database"), ("flink", "streaming")],
    consolidation_signal=0.7,
    source_slice="2025-W52",
    target_slice="2025-W52",
)
```

### DeepOnto Availability

BERTSubs requires DeepOnto with a functional JVM. If unavailable, consolidation fails fast with `#THETA.00000001.DEEPONTO`.

## SHAP Effectiveness Measurement

Consolidation effectiveness is measured using SHAP (SHapley Additive exPlanations) to attribute retrieval improvement to specific augmentations.

### Measurement Pipeline

1. **Pre-augmentation**: Embed holdout queries and compute retrieval scores
2. **Augmentation**: Inject wikilinks and action links into KB documents
3. **Post-augmentation**: Re-embed documents, re-compute retrieval scores
4. **Attribution**: SHAP decomposition of score improvement per augmentation

### Effectiveness Result

```python
{
    "retrieval_improvement": 0.12,  # Δ in retrieval quality
    "attribution": {
        "kudu→database": 0.05,
        "flink→streaming": 0.03,
        ...
    },
    "holdout_queries_used": 10,
}
```

## Response Format

### SITREP Response

```json
{
  "success": true,
  "horizon": "day",
  "generated_at": "2025-01-20T10:30:00",
  "report": {
    "system_status": {
      "healthy": true,
      "status_text": "HEALTHY",
      "gpu_count": 4,
      "endpoint_count": 3
    },
    "priorities": [
      {"description": "Review PR #123", "priority": "P0", "source": "gaius-dev"}
    ],
    "thoughts": [
      {"title": "Kudu compaction", "has_action_link": true}
    ],
    "objectives": [
      {"name": "rsv", "progress_pct": 85, "status": "PASS"}
    ],
    "evolution": {
      "running": true,
      "next_agent": "leader",
      "mode": "APO"
    },
    "quick_actions": [
      {"/research <topic>": "Start research on topic"}
    ]
  },
  "ascii_format": "..." // Terminal-friendly output
}
```

### Consolidation Response

```json
{
  "success": true,
  "slice_id": "2025-W03",
  "signal": {
    "urgency": 0.72,
    "drift": 0.85,
    "should_consolidate": true
  },
  "candidates_evaluated": 15,
  "candidates_selected": 8,
  "documents_augmented": 6,
  "effectiveness": {
    "retrieval_improvement": 0.08
  }
}
```

## Future Work

| Phase | Description | Status |
|-------|-------------|--------|
| **KB Metadata** | PostgreSQL tables for document metadata, temporal slices | Planned |
| **Subjective Logic** | Opinion fusion for consolidation decisions | Planned |
| **Weekly Audits** | 5-phase debate with Grok/Cerebras oversight | Planned |
| **BFO Ontology** | Basic Formal Ontology generation from KB | Planned |
| **Apache AGE KG** | Cypher queries for knowledge graph relationships | Deferred |
| **Textbook Quality** | Quality metrics for synthetic data | Future |
| **Atropos RL** | Evolution environment using audit rewards | Future |

### Subjective Logic Integration

Future consolidation decisions will use Subjective Logic opinion fusion:

```python
opinion = (belief, disbelief, uncertainty, base_rate)
fused = cumulative_fusion([kg_opinion, nvar_opinion, bertsubs_opinion])
```

This provides principled uncertainty quantification for subsumption confidence.

## Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#THETA.00000001.DEEPONTO` | DeepOnto/owlready2 not available for BERTSubs |
| `#THETA.00000002.STARTFAIL` | ThetaService failed to start |
| `#THETA.00000003.INITFAIL` | ThetaAgent initialization failed |
| `#THETA.00000004.SITREPFAIL` | SITREP generation failed |
| `#THETA.00000005.CONSFAIL` | Consolidation cycle failed |
| `#THETA.00000002.RESERVOIRPY` | ReservoirPy not available for NVAR dynamics |

## Service Configuration

```python
from gaius.engine.services.theta_service import ThetaService, ThetaConfig

theta_service = ThetaService(
    config=ThetaConfig(
        kb_root="build/dev",
        research_mode=True,       # Bypass KG cost threshold
        default_max_candidates=10,
        profile="default",
    ),
    db_pool=db_pool,  # Optional asyncpg pool
)
```

## Attention Schema Theory (AST)

ThetaAgent's design is grounded in Attention Schema Theory (Graziano, 2013):

| AST Component | ThetaAgent Implementation |
|---------------|---------------------------|
| **S (Stimulus)** | KB embeddings, document content |
| **A (Attention)** | AttentionSchema tracking targets, salience |
| **V (Model)** | NVAR prediction of expected semantic state |

The consolidation signal arises when V (predicted) diverges from A (actual), indicating the need to update the attention model via cross-temporal linking.

**Reference**: Graziano, M.S.A. (2013). *Consciousness and the Social Brain*. Oxford University Press.
