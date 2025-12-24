# Gaius Domain Ontology Project

**Date**: 2025-12-24
**Status**: ✓ Working with current sketch ontology
**Related**: ThetaAgent subsumption inference, BERTSubs integration

> **Update 2025-12-24**: BERTSubsIntraPipeline now works with the 58-class Gaius domain ontology.
> Three compatibility patches in `subsumption.py` fix DeepOnto 0.9.3 bugs with Python 3.11+,
> datasets 4.x, and transformers 4.46+. The sketch ontology is sufficient for training.

## Context

ThetaAgent's consolidation phase uses BERTSubs (from DeepOnto) for cross-temporal linking via subsumption inference. BERTSubsIntraPipeline requires an OWL ontology with sufficient classes and subsumption relationships to:

1. Extract training data from existing subsumption axioms
2. Split into training/validation sets for fine-tuning
3. Predict new subsumption relationships between concepts

The current sketch ontology (58 classes) successfully loads but is too small for BERTSubsIntraPipeline's training requirements.

## Current State

### Sketch Ontology

Location: `src/gaius/data/ontologies/gaius_domain.owl`
Namespace: `http://gaius.zndx.org/ontology#`
Classes: 58

Domain coverage:
- AI/ML foundations (MachineLearning, DeepLearning, NeuralNetwork)
- Knowledge representation (Ontology, KnowledgeGraph, SemanticWeb)
- Data processing (DataPipeline, ETL, Streaming)
- Agent systems (Agent, MultiAgentSystem, Swarm)
- Topology/TDA (TopologicalDataAnalysis, PersistentHomology)
- Embeddings (Embedding, TextEmbedding, VisionEmbedding)
- Gaius-specific (ThetaAgent, GridProjection, TemporalSlice)

### Test Status

```
tests/agents/theta/test_subsumption.py
├── TestSubsumptionCandidate (3 tests) ✓
├── TestDeepOntoNotAvailableError (2 tests) ✓
├── TestOntologyValidationResult (2 tests) ✓
├── TestSubsumptionInferencer (6 tests) ✓
├── TestOntologyValidationError (1 test) ✓
└── TestDeepOntoIntegration
    ├── test_deeponto_import ✓
    ├── test_ontology_loads_with_deeponto ✓
    ├── test_gaius_ontology_loads ✓
    └── test_predict_subsumption ⏭ (skipped - v1.0 TODO)
```

## Comprehensive Implementation (v1.0)

### Requirements

For BERTSubsIntraPipeline to work:

1. **Minimum class count**: ~200-500 classes for meaningful train/validation split
2. **Subsumption density**: Rich rdfs:subClassOf relationships
3. **rdfs:label annotations**: Every class needs human-readable labels for NLI
4. **Disjointness axioms**: owl:disjointWith for negative training samples

### Proposed Structure

```
gaius_domain.owl (comprehensive)
├── Foundation
│   ├── MathematicalConcept
│   ├── ComputationalMethod
│   └── DataStructure
├── MachineLearning
│   ├── SupervisedLearning (Classification, Regression, ...)
│   ├── UnsupervisedLearning (Clustering, DimensionReduction, ...)
│   └── ReinforcementLearning (PolicyGradient, ValueBased, ...)
├── NeuralArchitectures
│   ├── FeedForward (MLP, ResNet, ...)
│   ├── Recurrent (LSTM, GRU, ...)
│   ├── Attention (Transformer, BERT, GPT, ...)
│   └── Generative (VAE, GAN, Diffusion, ...)
├── KnowledgeRepresentation
│   ├── Ontology (OWL, RDFS, SKOS, ...)
│   ├── KnowledgeGraph (PropertyGraph, RDF, ...)
│   └── SemanticWeb (LinkedData, SPARQL, ...)
├── DataProcessing
│   ├── Streaming (Kafka, Flink, NiFi, ...)
│   ├── Batch (MapReduce, Spark, ...)
│   └── ETL (Extraction, Transform, Load)
├── AgentSystems
│   ├── SingleAgent (ReAct, CoT, ...)
│   ├── MultiAgent (Swarm, Debate, ...)
│   └── Orchestration (Workflow, Pipeline, ...)
├── TopologicalMethods
│   ├── PersistentHomology (VietorisRips, Cubical, ...)
│   ├── Mapper (Nerve, Reeb, ...)
│   └── ManifoldLearning (UMAP, tSNE, ...)
└── GaiusPlatform
    ├── Agents (ThetaAgent, Swarm, Latent, ...)
    ├── Visualization (Grid, MiniGrid, Overlay, ...)
    └── Infrastructure (Engine, Scheduler, Evolution, ...)
```

### Alternative: Pre-trained Checkpoint

Instead of training from scratch, we could:

1. Use a pre-trained BERTSubs checkpoint from a large ontology (e.g., SNOMED-CT subset)
2. Fine-tune on Gaius domain with fewer examples
3. Use the checkpoint for pure inference without retraining

This would allow the 58-class ontology to work for inference-only mode.

### Implementation Steps

1. **Ontology authoring**
   - Use Protege or OWL API for systematic class creation
   - Import relevant upper ontologies (BFO, SUMO subset)
   - Add detailed annotations (rdfs:label, rdfs:comment, skos:definition)

2. **Validation pipeline**
   - OWL consistency checking (HermiT reasoner)
   - Class count and subsumption density metrics
   - BERTSubs training data extraction test

3. **Integration**
   - Package ontology with gaius distribution
   - Add ontology update workflow for new domains
   - Consider ontology modularization (core + domain extensions)

## Technical Notes

### JVM Initialization

DeepOnto requires JVM. Must initialize before importing `deeponto.onto`:

```python
import os
os.environ["JVM_MEMORY"] = "4g"

from deeponto import init_jvm
init_jvm("4g")

# Now safe to import
from deeponto.onto import Ontology
```

See `tests/agents/theta/conftest.py` for pytest integration.

### BERTSubs Configuration

The inferencer uses YACS CfgNode. Must merge settings, not replace:

```python
# Wrong - loses required fields like train_pos_dup
self._config.fine_tune = CN()

# Correct - preserve defaults, override specific
if "fine_tune" not in self._config:
    self._config.fine_tune = CN()
self._config.fine_tune.pretrained = self.bert_checkpoint
```

### Namespace

Use `http://gaius.zndx.org/ontology#` (user owns zndx.org domain).

## References

- DeepOnto BERTSubs: https://krr-oxford.github.io/DeepOnto/
- OWL 2 Primer: https://www.w3.org/TR/owl2-primer/
- Protege: https://protege.stanford.edu/
- BFO (Basic Formal Ontology): https://basic-formal-ontology.org/
