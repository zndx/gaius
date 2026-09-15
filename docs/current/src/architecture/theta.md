# Theta Consolidation

ThetaAgent executes a deterministic consolidation pipeline for cross-temporal knowledge linking. Named after theta rhythms in hippocampal replay (Zhang et al., 2015), it compresses temporal experience into durable knowledge connections.

The agent operates in two phases: **SITREP** (situational awareness) and **Consolidation** (cross-temporal linking).

## Phase 1: SITREP

The `/sitrep` command generates a structured `SituationReport` through three components:

**Horizons** — Time-based attention windows inspired by hippocampal theta waves:

| Horizon | Window | Purpose |
|---------|--------|---------|
| EMPHASIS | 1 day | Today's focus |
| TACTICAL | 7 days | This week |
| STRATEGIC | 30 days | This month |
| SECULAR | 90 days | This quarter |
| OPEN | Unbounded | All time |

**AttentionSchema** — Models what information is currently attended to. Targets have priority (0.0–1.0) and decay rates. Active targets above a threshold are included in the report.

**SituationReport** — Aggregates objectives, recent thoughts, agenda items, current events, and capability notes into a single markdown-formatted output.

## Phase 2: Consolidation

### Stage 1: Temporal Slicing

Documents are organized into weekly slices (`YYYY-WNN`). The Monday 06:00 cycle consolidates the **previous** ISO week (the week that just closed), not the empty week that starts that morning.

### Stage 2: NVAR Dynamics

Nonlinear Vector AutoRegression via reservoir computing (Gauthier et al., 2021) computes a consolidation urgency signal from embedding centroid trajectories.

Given slice centroids **c**_1,...,**c**_t in R^128 (ColBERT-Zero `agg` centroids):
- NVAR predicts **c_hat**_{t+1} using a polynomial basis over delayed embeddings
- Drift = ||**c_hat**_{t+1} - **c**_t||_2
- Urgency = sigmoid(alpha * drift)

High urgency indicates rapid semantic drift — the knowledge base is changing faster than consolidation is linking it.

### Stage 3: Subsumption Inference

Candidate `A ⊑ B` hypotheses are scored by BERTSubs Intra (Chen et al., 2023, via DeepOnto) against one TBox. The layers are fixed and none is minted at run time:

| Layer | Role |
|-------|------|
| **OWL** | `external/sdg-corpora/ontology/sdg-ontology.owl` — the HermiT-certified TBox (`ontology/HERMIT_CERTIFICATE.md`), the only ontology the pipeline may load |
| **SKOS** | aperture codes resolve to those OWL IRIs (`SdgAperture.resolve`) |
| **CLT** | discrete co-activation over `admitted_item × activation` for the slice; items sharing a feature link their codes; distinct grounded IRIs on one feature form a candidate pair (`agents/theta/clt_incidence.py`) |
| **Thoughts** | `cognition_thoughts` feed the encode step and the NVAR signal only; no classes are derived from thought text |

The generated `kb_current.owl` and `gaius_domain.owl` of the 2025 pipeline are retired: minting `owl:Class` from markdown or thought tokens was a category error. Requires the JVM (JPype) that DeepOnto starts.

### Stage 4: Knowledge Gradient Selection

Candidate relationships are filtered using the Knowledge Gradient policy (Powell & Ryzhov, 2012). KG balances exploration (uncertain candidates) against exploitation (high-confidence relationships):

KG(x | S) = E[max_{x'} mu_{n+1}(x') | S_n=S, x_n=x] - max_{x'} mu_n(x')

Only candidates whose expected improvement exceeds a cost threshold are selected. The `BeliefState` tracks prior value and observation variance for each candidate.

### Stage 5: Document Augmentation

Selected relationships are injected into source documents as:
- **Wikilinks**: `[[Target Document]]` for navigation
- **Action links**: `[action:search "query"]` for deferred execution

### Effectiveness Tracking

The `EffectivenessTracker` measures augmentation impact by recording whether users follow injected links. When SHAP is available, feature attribution analysis identifies which augmentation types and document characteristics predict user engagement.

## CLI Commands

```bash
# Situational report
uv run gaius-cli --cmd "/sitrep" --format json

# Enqueue ThetaCycleFlow (same vessel as Airflow Monday 06:00)
uv run gaius-cli --cmd "/theta consolidate" --format json

# View consolidation stats
uv run gaius-cli --cmd "/theta stats" --format json
```
