# RASE Go-Forward Strategy: Ontology-Grounded Dataset Generation

**Date**: 2025-12-21
**Status**: Implementation Ready
**Related**:
- [RASE MBSE Framework](../2025-12-19/150000_rase_mbse_framework.md)
- [MetaAgent Formal Design](../2025-12-19/144500_metaagent_formal_design.md)

---

## Executive Summary

RASE (Rapid Agent Systems Engineering) generates ontology-grounded training datasets for model fine-tuning and training. The core innovation combines:

1. **DeepOnto Verbalization** - Complex OWL class expressions → natural language training pairs
2. **BERTopic Discovery** - Unsupervised topic structure from KB content
3. **Intrinsic Verification** - Verifiable training examples with reward signals
4. **Calibration Loop** - Frontier model validation of local evaluations

**The Goal**: Create semantically-rich, verified datasets for:
- Fine-tuning existing models on domain-specific knowledge
- Ground-up training with curriculum learning
- Self-improving agent systems

---

## Architecture: Ontology-to-Training Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ONTOLOGY-GROUNDED TRAINING PIPELINE                       │
│                                                                              │
│  ┌─────────────────────┐                                                    │
│  │   OWL Ontology      │  ← Domain knowledge structure                      │
│  │   (Domain-Specific) │    BFO upper ontology, domain axioms               │
│  └──────────┬──────────┘                                                    │
│             │                                                               │
│             ▼                                                               │
│  ┌─────────────────────┐                                                    │
│  │   DeepOnto          │  ← Complex class verbalization                     │
│  │   Verbaliser        │    "SubClassOf(A, B and C)" → natural language     │
│  └──────────┬──────────┘                                                    │
│             │                                                               │
│             ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    KB CONTENT LAYER                                   │   │
│  │                                                                       │   │
│  │   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐         │   │
│  │   │  Topics       │   │  Objectives   │   │  Evidence     │         │   │
│  │   │  (BERTopic)   │   │  (RASE)       │   │  (HX)         │         │   │
│  │   └───────┬───────┘   └───────┬───────┘   └───────┬───────┘         │   │
│  │           │                   │                   │                  │   │
│  │           └───────────────────┼───────────────────┘                  │   │
│  │                               │                                       │   │
│  └───────────────────────────────┼───────────────────────────────────────┘   │
│                                  │                                           │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    VERIFICATION LAYER                                │    │
│  │                                                                      │    │
│  │   Syntactic Gates → Semantic Gates → Empirical Gates                │    │
│  │        ↓                   ↓                  ↓                     │    │
│  │   Document Valid    Claims Grounded    LLM Verification            │    │
│  │   Wikilinks OK      Citations Fresh    No Hallucinations           │    │
│  │                                                                      │    │
│  └──────────────────────────────┬───────────────────────────────────────┘    │
│                                 │                                            │
│                                 ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    TRAINING DATA OUTPUT                              │    │
│  │                                                                      │    │
│  │   { "input": verbalized_class_expression,                           │    │
│  │     "output": verified_kb_content,                                  │    │
│  │     "reward": gate_weighted_score,                                  │    │
│  │     "topics": [bertopic_assignments],                               │    │
│  │     "lineage": digital_thread_id }                                  │    │
│  │                                                                      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## DeepOnto Integration: Verbalized Class Expressions

The `objsrv` example shows the core pattern:

```python
from deeponto.onto import Ontology, OntologyVerbaliser

# Load domain ontology
onto = Ontology("domain.owl")
verbaliser = OntologyVerbaliser(onto)

# Verbalize complex asserted classes
complex_concepts = list(onto.get_asserted_complex_classes())
for concept in complex_concepts:
    v_concept = verbaliser.verbalise_class_expression(concept)
    # v_concept.verbal is natural language description
    training_pairs.append({
        "owl_expression": str(concept),
        "verbalization": v_concept.verbal,
        "class_iri": str(concept.getIRI()),
    })
```

### Training Data Structure

Each training example links:

| Field | Source | Purpose |
|-------|--------|---------|
| `owl_expression` | Ontology | Formal semantics |
| `verbalization` | DeepOnto | Natural language target |
| `kb_document` | KB State | Grounded content |
| `topic_ids` | BERTopic | Semantic clustering |
| `reward` | RASE Verification | Training signal |
| `thread_id` | Digital Thread | Lineage tracking |

---

## BERTopic: Unsupervised Topic Discovery

The existing `gaius.flows.topics` module provides topic extraction:

```python
from gaius.flows.topics.models import train_topic_model, get_document_topics

# Train on KB corpus
topic_model = train_topic_model(
    documents=kb_documents,
    model_type="bertopic",
    embedding_model="nomic-ai/nomic-embed-text-v1.5",  # Unified with ColNomic
)

# Assign topics to each document
for doc in kb_documents:
    result = get_document_topics(topic_model, doc.content)
    # result.topics: [(topic_id, weight), ...]
    # result.top_words: {topic_id: [words, ...]}
```

### Topic-Ontology Alignment

Discovered topics should map to ontology classes:

```
┌─────────────────────────────────────────────────────────────────┐
│              TOPIC-ONTOLOGY ALIGNMENT                            │
│                                                                  │
│  BERTopic Cluster 0        ←→   bfo:Process subclasses          │
│  Keywords: pipeline, flow        "Process that transforms..."   │
│                                                                  │
│  BERTopic Cluster 1        ←→   bfo:Quality instances           │
│  Keywords: metric, score         "Quality inhering in..."       │
│                                                                  │
│  BERTopic Cluster 2        ←→   Domain-specific classes         │
│  Keywords: pension, benefit      "Pension benefit is a..."      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## RASE Objectives: Current State

### Implemented Objectives (4)

| Objective | Gates | Training Value |
|-----------|-------|----------------|
| **RSV** | 5 | Document structure, citation presence |
| **Wikilink-Integrity** | 5 | KB graph structure validation |
| **Citation-Freshness** | 5 | External source quality |
| **Semantic-Grounding** | 5 | Claim-source alignment |

### Constraint Library (15)

```
Syntactic:
  - DocumentParses, FrontmatterValid, HasWikilinks, HasCitations

Semantic:
  - WikilinksResolve, CitationsAccessible, NoOrphanLinks
  - ClaimsIdentified, SourcesAuthoritative, LinkDensity

Empirical:
  - CitationsNotStale, ClaimsGrounded, NoHallucinations
  - SemanticCoherence, OutputStructureValid
```

---

## The Full Training Pipeline

### Phase 1: Ontology Verbalization

```python
# Generate ontology-grounded training pairs
async def generate_ontology_training_data(
    ontology_path: Path,
    kb_root: Path,
) -> list[TrainingPair]:
    """Verbalize ontology classes and align with KB content."""

    from deeponto.onto import Ontology, OntologyVerbaliser

    onto = Ontology(str(ontology_path))
    verbaliser = OntologyVerbaliser(onto)

    pairs = []
    for concept in onto.get_asserted_complex_classes():
        try:
            verbalized = verbaliser.verbalise_class_expression(concept)

            # Find KB documents that instantiate this class
            matching_docs = await find_documents_for_class(
                concept, kb_root
            )

            for doc in matching_docs:
                pairs.append(TrainingPair(
                    owl_expression=str(concept),
                    verbalization=verbalized.verbal,
                    kb_content=doc.content,
                    class_iri=str(concept.getIRI()),
                ))
        except Exception:
            continue

    return pairs
```

### Phase 2: Topic Enrichment

```python
async def enrich_with_topics(
    pairs: list[TrainingPair],
    topic_model: TopicModel,
) -> list[TrainingPair]:
    """Add topic assignments to training pairs."""

    for pair in pairs:
        result = get_document_topics(topic_model, pair.kb_content)
        pair.topic_ids = [tid for tid, _ in result.topics]
        pair.topic_words = result.top_words

    return pairs
```

### Phase 3: RASE Verification

```python
async def verify_training_pairs(
    pairs: list[TrainingPair],
    objective: Objective,
    oracle: KBOracle,
) -> list[VerifiedTrainingPair]:
    """Run verification and assign rewards."""

    state = oracle.get_current_state()
    verified = []

    for pair in pairs:
        case = objective_to_verification_case(objective, pair.kb_path)
        result = case.evaluate(state)

        verified.append(VerifiedTrainingPair(
            **pair.__dict__,
            verdict=result.verdict.name,
            accuracy=result.accuracy,
            reward=result.to_reward(),
            gate_results=[
                {"gate": cr.constraint_name, "passed": cr.satisfied}
                for cr in result.constraint_results
            ],
            thread_id=create_digital_thread(objective, case, result).thread_id,
        ))

    return verified
```

### Phase 4: Calibration

```python
async def calibrate_training_data(
    verified: list[VerifiedTrainingPair],
    calibration_oracle: CalibrationOracle,
    sample_rate: float = 0.1,
) -> list[CalibratedTrainingPair]:
    """Validate local scores with frontier model."""

    # Sample for calibration (budget-aware)
    sample = random.sample(verified, int(len(verified) * sample_rate))

    calibrated = []
    for pair in sample:
        result = await calibration_oracle.run_calibration_cycle(
            input_text=pair.verbalization,
            output_text=pair.kb_content,
            local_score=pair.reward,
        )

        pair.calibration_score = result.external_scores[0]
        pair.drift_detected = result.drift_detected
        calibrated.append(pair)

    return verified  # Return all, with calibration on sample
```

---

## Training Output Formats

### Nous Research Format

```jsonl
{"input": "A pension benefit is a quality that inheres in a retirement account and is measured by monthly payment amount.", "output": "The pension benefit calculation uses the formula: (years_of_service * final_average_salary * accrual_rate). This quality is instantiated when...", "reasoning": ["The ontology defines PensionBenefit as subclass of bfo:Quality", "The KB document correctly implements this definition", "All claims are grounded in cited actuarial sources"], "reward": 0.95}
```

### LLaVA/Magma Format (for vision-language)

```jsonl
{"image": "path/to/nifi_canvas.png", "conversations": [{"from": "human", "value": "<image>\nCreate a data flow that processes pension benefit calculations"}, {"from": "gpt", "value": "I'll create a flow with GetFile → EvaluateJsonPath → UpdateAttribute → PutS3..."}], "metadata": {"source": "bdd_grounded", "ontology_class": "pension:BenefitCalculationProcess", "semantic_accuracy": 0.92}}
```

### RLVR Format (for reinforcement learning)

```jsonl
{"prompt": "Given the ontology class 'DataProcessingPipeline subClassOf (hasInput some RawData) and (hasOutput some ProcessedData)', generate a KB document that...", "completion": "# Data Processing Pipeline\n\nA data processing pipeline transforms raw data...", "reward": 1.0, "verification": {"gates_passed": 5, "gates_total": 5}, "lineage": "rase://threads/abc123"}
```

---

## Implementation Roadmap

### Immediate (This Week)

1. **Integrate DeepOnto**
   ```python
   # Add to gaius.rase.domains.kb
   from gaius.ontology import load_domain_ontology, verbalize_classes
   ```

2. **Create Domain Ontology**
   - Start with BFO upper ontology
   - Add domain-specific classes (pension, kudu, etc.)
   - Define complex class expressions

3. **Connect BERTopic to RASE**
   - Topic model on KB corpus
   - Align topics with ontology classes

### Short-Term (This Month)

1. **Export Pipeline**
   ```bash
   uv run gaius-cli --cmd "/rase export --format nous --ontology domain.owl"
   ```

2. **First Training Run**
   - Export 1K+ verified pairs
   - Fine-tune on small model (3B params)
   - Evaluate on held-out set

### Medium-Term (Q1 2026)

1. **Curriculum Design**
   - Syntactic → Semantic → Empirical progression
   - Topic-based difficulty scaling
   - Ontology complexity levels

2. **Ground-Up Training**
   - 100K+ verified examples
   - Full curriculum training
   - Multi-domain generalization

---

## Metrics

### Dataset Quality

| Metric | Target | Measure |
|--------|--------|---------|
| Ontology coverage | > 80% | Classes with verbalization |
| Topic coherence | > 0.5 | BERTopic C_v score |
| Verification accuracy | > 85% | Passing rate on objectives |
| Calibration correlation | > 0.9 | Local vs frontier |

### Training Outcomes

| Metric | Target | Measure |
|--------|--------|---------|
| Held-out accuracy | > 75% | On reserved evaluation set |
| Ontology alignment | > 70% | Generated content matches class semantics |
| Citation grounding | > 90% | Claims traceable to sources |

---

## Database Schema

The calibration migration (`20251221000001_evolution_calibrations.sql`) provides:

```sql
-- Calibration tracking
evolution_calibrations
  - local_score, calibration_score, delta
  - drift_detected, drift_magnitude

-- Verification runs with lineage
objective_verifications
  - run_id, objective_name, verdict, accuracy, reward
  - thread_id (links to rase:// traceability)
  - eligible_for_training

-- Views for analysis
calibration_health
objective_verification_summary
```

---

## MCP Tools Available

```bash
# Objectives
mcp__gaius__list_objectives()
mcp__gaius__verify_objective(objective_name, document_path)
mcp__gaius__verification_history(objective_name, limit)

# Calibration
mcp__gaius__calibration_status(agent_id)
mcp__gaius__trigger_calibration(agent_id, objective_name, provider)
mcp__gaius__calibration_history(agent_id, limit)

# Topics (existing)
# Via fetch_paper flow with enable_topics=True
```

---

## Key Insight

The power of this approach is the **ontology-grounding**:

1. **DeepOnto** verbalizes formal OWL semantics into natural language
2. **KB content** provides grounded examples of those concepts
3. **RASE verification** ensures the examples are correct
4. **BERTopic** discovers latent structure for curriculum design
5. **Calibration** validates the training signal quality

This creates a closed loop where:
- The ontology defines what the model should "know"
- The KB provides examples of that knowledge
- Verification ensures the examples are correct
- Topic models organize the curriculum
- The trained model can then generate new KB content
- Which is verified and added to training data

**Self-improvement through ontological grounding.**

---

## References

- `~/local/src/rch/objsrv/src/main.py` - DeepOnto verbalization example
- `src/gaius/flows/topics/models.py` - BERTopic/Gensim integration
- `src/gaius/rase/domains/kb/` - KB domain package
- `db/migrations/20251221000001_evolution_calibrations.sql` - Calibration schema
