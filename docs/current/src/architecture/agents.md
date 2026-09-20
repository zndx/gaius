# Agent System

The agent system provides LLM orchestration patterns for domain analysis: role-based prompt execution, parallel inference coordination, temporal consolidation, and background evolution.

> **Terminology note**: Components here are labeled "agents" following pre-2024 conventions (cf. LangChain, AutoGPT). They are *orchestrated pipelines* — they lack observe-reason-act loops and self-directed goal pursuit.

## Swarm Execution

The primary pattern executes multiple LLM calls with distinct role-based system prompts in parallel:

| Role | Perspective | Temperature |
|------|-------------|-------------|
| Leader | Strategic synthesis | 0.7 |
| Risk | Threat identification | 0.6 |
| Optimizer | Efficiency analysis | 0.7 |
| Planner | Roadmap development | 0.7 |
| Critic | Adversarial review | 0.8 |
| Executor | Implementation assessment | 0.6 |
| Adversary | Stress testing | 0.8 |

Execution is parallel (`asyncio.gather` over `parallel_inference()`) but not agentic — roles do not observe each other's outputs or iterate. Each role has lattice positioning behaviors: Leader seeks cluster centroids, Risk positions at boundaries (negative curvature regions), Adversary samples uniformly.

## Latent Swarm (LatentMAS)

Reduces inter-agent token transfer by sharing embeddings instead of text via Qdrant (Guo et al., 2024). Each agent stores its output as a ColBERT-Zero `agg` embedding (128-dim) in the `gaius_latent_memory` collection. Subsequent agents retrieve relevant context via semantic search rather than receiving full text.

Token reduction: 70–90% compared to text-based coordination. The collection schema includes domain, agent_id, session_id, and timestamp — enabling both cross-agent retrieval within a session and longitudinal analysis across sessions.

## ThetaAgent: Temporal Consolidation

ThetaAgent (`agents/theta/agent.py`) plus `ThetaCycleFlow` (`gaius_theta_cycle`) execute a five-stage pipeline. Vessel: Metaflow on LIGHT (ColBERT-Zero); BERTSubs is CPU/JVM. `theta_consolidation_runs` is the **job ledger** (Nautilus coverage). The authentic Signals product has not been published; intended Aspects live in `docs/scratch/2026-09-20/160356_theta_consolidation_data_product_aspects.md` and [Theta Consolidation](./theta.md).

1. **Temporal slicing** — The window is the ISO week (`YYYY-WNN`). On-time Monday 06:00 consolidates the previous closed week. A miss remediates with daily LIGHT increments (`zndx.window_date`) that refine the **same week** (ledger coverage + in-place Aspects). That finer grain is a work unit, not a [ShadowStrategy](./theta.md#shadowstrategy).

2. **NVAR dynamics** — Nonlinear Vector AutoRegression (Gauthier et al., 2021) on ColBERT-Zero `agg` centroids (ℝ¹²⁸). Same `slice_id` replaces the week centroid (refinement), it does not append a new temporal product. Drift = ‖ĉₜ₊₁ − **c**ₜ‖₂.

3. **BERTSubs inference** — `A ⊑ B` on CLT-linked, MaxSim-grounded pairs against the HermiT-certified SDG TBox (`sdg-ontology.owl`). Pairing uses the week's activations and accumulated groundings.

4. **Knowledge Gradient selection** — KG policy (Powell & Ryzhov, 2012) keeps candidates whose expected improvement exceeds cost.

5. **Document augmentation** — Wikilinks (`[[Target]]`) and action links (`[action:search "query"]`) on the week's documents.

## MetaAgent Coordination

`MetaAgentManager` (`agents/metaagent_swarm.py`) coordinates specialist analysts to answer natural language questions by querying structured data sources:

- **Lineage analyst** — Translates questions to Cypher queries against the lineage graph
- **Ops analyst** — Translates to SQL queries against operational metrics
- **Resource analyst** — Queries infrastructure state
- **Topology analyst** — Queries embedding space structure

Results are synthesized by a Correlator (single LLM call). This is parallel execution with synthesis, not autonomous multi-agent reasoning.

## Background Processes

Two daemons run within the engine:

- **Evolution Daemon** — Optimizes agent prompts during GPU idle periods (<30% utilization). Methods include APO (Zhou et al., 2023) and GEPA (Guo et al., 2024). Agent versions can be merged via TIES (Yadav et al., 2023) or DARE (Yu et al., 2024) in parameter space.
- **Cognition Agent** — Generates "thoughts" about patterns in KB activity (every 4–8h). Thought types: PATTERN, CONNECTION, CURIOSITY, SELF_OBSERVATION.

## Subchapters

- [Evolution](./evolution.md) — RLVR-based prompt optimization
- [Cognition](./cognition.md) — Autonomous thought generation
- [Theta Consolidation](./theta.md) — Temporal knowledge linking
- [CLT Memory](./clt.md) — Cross-Layer Transcoder features
