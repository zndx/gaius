# ThetaAgent Consolidation Architecture

## Design Objective

An effective ThetaAgent implementation demonstrates that post-encoding (Zettelkasten → embeddings → Qdrant), allocating compute for ThetaAgent upregulation has a **positive effect on episodic memory consolidation** such that meaningful improvements in Gaius information recall capabilities can be consistently demonstrated.

The allocation of compute cycles to ThetaAgent behavior must be **economically justified** by enhanced information retrieval quality.

## Biological Analog: Sleep Replay

Hippocampal theta during sleep consolidates episodic memories into cortical representations through:
1. **Temporal compression** - Experiences replayed at accelerated rates
2. **Synaptic plasticity** - Repeated activation strengthens connections
3. **Cross-temporal binding** - Distant events linked by shared features

## Gaius Implementation: NVAR-Mediated Consolidation

### Next Generation Reservoir Computing (NGRC)

From [Gauthier et al. 2021](https://www.nature.com/articles/s41467-021-25801-2):

> Reservoir computing is mathematically identical to a nonlinear vector autoregression (NVAR) machine. No reservoir is required: the feature vector consists of k time-delay observations and nonlinear functions of these observations.

**Key insight**: NVAR eliminates random matrices by constructing features directly from time-delayed observations. This maps naturally to temporal slices of a knowledge base.

### Feature Vector Construction

```
O_total = c ⊕ O_lin ⊕ O_nonlin(p)

where:
  O_lin = X_i ⊕ X_{i-s} ⊕ X_{i-2s} ⊕ ... ⊕ X_{i-(k-1)s}
  O_nonlin = polynomial functionals (typically quadratic)
```

For Gaius KB consolidation:
- **X_i** = Embedding centroid for temporal slice i (week/month)
- **s** = Temporal stride (e.g., 1 week)
- **k** = Number of historical slices to consider

### Architecture Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ThetaAgent Consolidation Loop                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐         │
│  │   Qdrant     │     │  ReservoirPy │     │   BERTSubs   │         │
│  │   (KB +      │────▶│    NVAR      │────▶│  Subsumption │         │
│  │   Latent)    │     │   Dynamics   │     │  Inference   │         │
│  └──────────────┘     └──────────────┘     └──────────────┘         │
│        │                    │                     │                  │
│        │                    │                     │                  │
│        ▼                    ▼                     ▼                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐         │
│  │  Temporal    │     │   Theta      │     │  DeepOnto    │         │
│  │  Slicing     │     │  Oscillator  │     │  Verbalizer  │         │
│  └──────────────┘     └──────────────┘     └──────────────┘         │
│        │                    │                     │                  │
│        └────────────────────┴─────────────────────┘                  │
│                             │                                        │
│                             ▼                                        │
│                    ┌──────────────────┐                              │
│                    │  KB Augmentation │                              │
│                    │  (wikilinks,     │                              │
│                    │  action:search)  │                              │
│                    └──────────────────┘                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## NVAR Dynamics for Swarm Mediation

The NVAR doesn't just predict - it mediates swarm activity:

```python
class ThetaDynamics:
    """NVAR-based theta oscillator for consolidation scheduling."""

    def __init__(
        self,
        k: int = 4,           # Historical slices
        s: int = 7,           # Stride (days)
        polynomial_order: int = 2,
    ):
        from reservoirpy.nodes import NVAR

        self.nvar = NVAR(
            delay=k,
            order=polynomial_order,
            strides=s,
        )

    def compute_consolidation_signal(
        self,
        temporal_embeddings: list[np.ndarray],
    ) -> float:
        """Compute theta-like consolidation signal.

        Returns value in [0, 1] indicating consolidation urgency.
        High values → more BERTSubs speculative activity.
        """
        # NVAR predicts next embedding based on history
        features = self.nvar.run(temporal_embeddings)

        # Consolidation signal = deviation from prediction
        # (high deviation = knowledge drift = consolidation needed)
        predicted = self.nvar.readout(features)
        actual = temporal_embeddings[-1]

        drift = np.linalg.norm(predicted - actual)
        return np.tanh(drift)  # Bounded [0, 1]
```

## LatentMAS Integration

### Current State

The `LatentWorkingMemory` class in `src/gaius/agents/latent/memory.py` provides:
- Qdrant-backed embedding storage
- Semantic similarity retrieval
- Consensus computation via mean embedding
- Domain-scoped clearing

### Required Extensions for Consolidation

1. **Temporal Indexing**
   - Add `temporal_slice` field to LatentThought
   - Enable retrieval by time range
   - Support historical embedding aggregation

2. **Iceberg Archival**
   - Archive latent messages to S3/MinIO
   - Apache Iceberg tables for scientific reproducibility
   - Full HX (history) retention

3. **NVAR Feature Store**
   - Pre-computed temporal slice centroids
   - Polynomial feature expansion
   - Cached NVAR predictions

```python
@dataclass
class LatentThought:
    # ... existing fields ...
    temporal_slice: str = ""  # e.g., "2025-W52", "2025-Q4"

    # For Iceberg archival
    archived: bool = False
    archive_path: str | None = None
```

## BERTSubs Speculative Activity

### Depth-Mediated Processing

The consolidation signal from NVAR mediates BERTSubs activity:

```python
async def consolidation_pass(
    self,
    consolidation_signal: float,
    max_candidates: int = 100,
) -> list[SubsumptionCandidate]:
    """Run BERTSubs with depth mediated by theta signal.

    Higher consolidation signal → more aggressive subsumption inference.
    """
    # Scale candidates by signal (0.0 → 10%, 1.0 → 100%)
    depth = int(max_candidates * (0.1 + 0.9 * consolidation_signal))

    # Sample candidate pairs from temporal slices
    candidates = await self._sample_cross_temporal_pairs(depth)

    # BERTSubs inference
    results = []
    for subclass, superclass in candidates:
        # Verbalize via DeepOnto
        sentence_pair = self.verbalizer.verbalize_subsumption(
            subclass, superclass
        )

        # BERTSubs prediction
        prob = await self.bertsubs.predict(sentence_pair)

        if prob > self.threshold:
            results.append(SubsumptionCandidate(
                subclass=subclass,
                superclass=superclass,
                confidence=prob,
            ))

    return results
```

### KB Augmentation Strategies

Discovered subsumptions materialize as:

1. **Wikilinks** - Direct `[[concept]]` links in documents
2. **action:search links** - Soft semantic links: `[action:search "related concept"]`
3. **Frontmatter relations** - YAML `relates_to:` fields

```markdown
---
title: Atlas Advanced Search
relates_to:
  - hasTerm (since: 7.1.6)
  - Apache Atlas
temporal_slice: 2025-Q4
---

# Atlas Advanced Search

The `hasTerm` keyword enables glossary-based entity search.
[action:search "glossary term search CDP"]

## Version Compatibility

- Available in CDP 7.1.6+ [action:verify "cdp-version-compatibility"]
```

## SHAP-Based Effectiveness Measurement

### Holdout Structure

Augmented sections must be structurally identifiable for holdout:

```markdown
<!-- BEGIN THETA_AUGMENTATION slice=2025-W52 -->
## Related Concepts (Auto-generated)

Subsumption-inferred relationships:
- [[SparkVersion]] ⊑ ∃supports.[[CDP]]
- [[hasTerm]] ⊑ [[AtlasAdvancedSearch]]

<!-- END THETA_AUGMENTATION -->
```

### SHAP Evaluation

```python
import shap

def evaluate_augmentation_contribution(
    retriever,
    queries: list[str],
    with_augmentation: bool,
) -> np.ndarray:
    """Measure retrieval quality with/without augmentations."""

    def retrieval_fn(docs):
        # Mask augmentation sections if with_augmentation=False
        if not with_augmentation:
            docs = [mask_theta_sections(d) for d in docs]
        return retriever.score(docs, queries)

    explainer = shap.Explainer(retrieval_fn)
    shap_values = explainer(docs)

    return shap_values
```

### Knowledge Gradient Policy (Optimal Learning)

The **Knowledge Gradient (KG)** from Optimal Learning (Powell & Ryzhov) provides the principled framework for deciding which subsumptions to verify:

> KG = E[max_{x'} μ^{n+1}_{x'} | x^n = x] - max_{x'} μ^n_{x'}

Where:
- μ^n_x = Current belief about value of alternative x
- μ^{n+1}_x = Updated belief after observing outcome of measuring x

For consolidation, the KG policy selects the subsumption candidate that maximizes expected improvement in downstream retrieval quality:

```python
def knowledge_gradient(
    candidate: SubsumptionCandidate,
    belief_state: BeliefState,  # Current retrieval quality distribution
    measurement_cost: float,     # GPU cycles for BERTSubs
) -> float:
    """Compute Knowledge Gradient for subsumption verification.

    KG measures the expected value of information from verifying
    this subsumption relationship.

    Returns:
        KG value (higher = more valuable to verify)
    """
    # Prior belief about retrieval improvement
    prior_mean = belief_state.mean(candidate.subclass)
    prior_var = belief_state.variance(candidate.subclass)

    # Expected posterior after verification
    # (Bayesian update with BERTSubs confidence as signal)
    posterior_mean, posterior_var = bayesian_update(
        prior_mean, prior_var,
        candidate.confidence,
        measurement_noise=0.1,  # BERTSubs uncertainty
    )

    # KG = expected improvement in best alternative
    # Approximated via normal CDF (Frazier et al. 2009)
    sigma = np.sqrt(prior_var - posterior_var)
    z = (posterior_mean - belief_state.current_best()) / sigma

    kg_value = sigma * (z * norm.cdf(z) + norm.pdf(z))

    # Cost-adjusted KG
    return kg_value / measurement_cost
```

This provides **economic justification** for consolidation compute in production: we only verify subsumptions where the KG exceeds the cost threshold.

**Research Phase Note**: During theory development, subsumption verification costs are expected to exceed the KG threshold. This is warranted as we:
1. Build the measurement infrastructure (SHAP, holdout testing)
2. Calibrate the belief state model against empirical retrieval quality
3. Characterize the cost function (GPU cycles, latency, token consumption)
4. Validate that the KG formulation correctly predicts retrieval improvement

The research investment establishes the theoretical foundation; the KG policy provides the operational constraint once the system is characterized.

## Cloudera-Docs_2025Q4 Test Domain

### Logical Tasks

1. **Version compatibility** (transitive)
   - Q: "Does CDP 7.3.1 support Spark 2.4?"
   - Requires: SparkVersion ⊑ ∃deprecatedIn.CDP7.3.1

2. **Feature availability** (existential)
   - Q: "How do I search Atlas by glossary term in CDP 7.1.4?"
   - Answer: Cannot (hasTerm requires 7.1.6+)

3. **Dependency chains**
   - Requires traversing subsumption hierarchies
   - Trivial with ontology, hard with flat KB

### External Oracle

Support Matrix (https://supportmatrix.cloudera.com/) provides ground truth for:
- Version compatibility assertions
- Feature/component relationships
- Deprecation timelines

## Implementation Phases

### Phase 1: Temporal Slicing + Archival
- Add `temporal_slice` to LatentThought
- Implement Iceberg archival for HX retention
- Build temporal embedding aggregation

### Phase 2: NVAR Integration
- ReservoirPy NVAR node for consolidation signal
- Theta oscillator class
- Signal-mediated depth control

### Phase 3: BERTSubs Consolidation
- DeepOnto verbalizer integration
- Cross-temporal subsumption inference
- KB augmentation with structured markers

### Phase 4: SHAP Evaluation
- Holdout testing infrastructure
- Retrieval quality measurement
- Knowledge gradient optimization

## References

- [Gauthier et al. 2021](https://www.nature.com/articles/s41467-021-25801-2) - Next Generation Reservoir Computing
- [ReservoirPy](https://github.com/reservoirpy/reservoirpy) - Python RC library
- DeepOnto - OWL verbalization and BERTSubs
- Optimal Learning (Powell & Ryzhov) - Sequential decision framework
