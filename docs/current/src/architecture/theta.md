# Theta Consolidation

ThetaAgent executes a deterministic consolidation pipeline for cross-temporal knowledge linking. Named after theta rhythms in hippocampal replay, it compresses temporal experience into durable knowledge connections.

## Pipeline Stages

```
Temporal Slicing → NVAR Signal → BERTSubs Inference → KG Selection → Augmentation
```

### 1. Temporal Slicing

Documents are organized into weekly slices (`YYYY-WNN` format). Each slice represents a temporal context for consolidation.

### 2. NVAR Dynamics

Nonlinear Vector AutoRegression using reservoir computing computes a consolidation signal from embedding centroid trajectories. High "urgency" indicates rapid semantic drift requiring consolidation attention.

### 3. BERTSubs Inference

Subsumption relationships between concepts are inferred using BERTSubs from DeepOnto. The inferencer identifies "A is-a B" relationships via fine-tuned BERT classification on ontology subsumptions.

### 4. Knowledge Gradient Selection

Candidate relationships are filtered using the Knowledge Gradient policy, balancing exploration (learning about uncertain candidates) against exploitation (selecting high-confidence relationships).

### 5. Document Augmentation

Selected relationships are injected into source documents as wikilinks and action links for navigation.

## Usage

```bash
# Run consolidation
uv run gaius-cli --cmd "/theta consolidate" --format json

# View consolidation stats
uv run gaius-cli --cmd "/theta stats" --format json

# Check situational report
uv run gaius-cli --cmd "/sitrep" --format json
```

## Dependencies

- **DeepOnto** with JVM (via JPype) for BERTSubs
- **OWL domain ontology** with `rdfs:subClassOf` axioms
- Sufficient class count (~50+ classes) for training data
