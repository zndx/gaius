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

Documents are organized into weekly slices (`YYYY-WNN`). The Monday 06:00 cycle consolidates the **previous** ISO week *for that run's logical date* (the week that closed relative to that Monday), not the empty week that starts that morning, and not "everything since the last success."

DAG `gaius_theta_cycle` stays `catchup=False`: unpausing must not dump every missed Monday onto the LIGHT token (that window grows until Theta starves other Airflow workloads). Missed weeks are a persistent failure.

Remediate from the Signals tree with daily LIGHT increments (`just theta-backfill --from-date … --to-date …`). Each UTC day encodes that day's thoughts and merges centroid, CLT, and groundings into one `theta_consolidation_runs` **ledger** row for the containing ISO week. Completing that row is LIGHT coverage, not the cortical product. `max_active_runs=1` serializes the days. `--weekly` is the coarse one-Monday-run path.

The authentic Signals data product (`gaius.theta.consolidation`) has **not** been published. Intended product split and evidence planes (booked Gaius/Theta session + rustfs materials, week \(X_i\), CLT/MaxSim week binding, replaceable KB week-block, ShadowStrategy aperture delta, sealed transcript, History) are considered in `docs/scratch/2026-09-20/160356_theta_consolidation_data_product_aspects.md`. AgentRTC wiki `current/design/data-product-aspects.md` is **non-normative** vocabulary (Aspect = contract, not the blob; session series is a distinct product). The ledger remains for Nautilus / sitrep.

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

## ShadowStrategy

Gaius consumes `external/sdg-strategy` (`SdgAperture`). **ShadowStrategy** there means a
**branch of the strategy repo** (lens / voices / knobs / targets), not a Theta time grain.
See `external/sdg-strategy/README.md` (Shadows are branches).

| Coordinate | Theta |
|---|---|
| **window** | ISO week (`YYYY-WNN`) of the consolidation Aspects |
| **strategy** | pinned `strategy_id` / aperture |
| **code** | Gaius + `ThetaCycleFlow` |
| **work unit** | on-time: one Monday run for the closed week; backfill: one UTC day of LIGHT that *refines* the week Aspects (ledger row is coverage) |
| **shadow** | a different strategy branch. Compare week Aspects, never day windows |
| **promotion** | cherry-pick/merge of the strategy delta, **gated by** a booked Gaius/Theta agenda session. Discourse elevates the shadow into the live ColBERT-Zero/Qdrant admission membrane when appropriate; the claim is supported by the **sealed** transcript, not the in-force call and not week close. |

Daily increments (`zndx.window_date`) are not shadows and not day-bounded releases. The ledger row completes when Monday–Sunday of that slice are incorporated. DAG `catchup=False`; `just theta-backfill` (Signals) serializes days with `max_active_runs=1`.

A shadow Theta comparison is: same ISO week, two `strategy_id`s, two week-level Aspect sets (B–E), not two SQL rows.

## CLI Commands

```bash
# Situational report
uv run gaius-cli --cmd "/sitrep" --format json

# Enqueue ThetaCycleFlow (same vessel as Airflow Monday 06:00)
uv run gaius-cli --cmd "/theta consolidate" --format json

# View consolidation stats
uv run gaius-cli --cmd "/theta stats" --format json
```
