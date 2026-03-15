# Glossary

**ACP** — Agent Client Protocol. Integration layer for Mistral Vibe to perform autonomous health maintenance.

**AgendaTracker** — Tracks scheduled endpoint transitions for makespan operations, preventing false-positive health incidents.

**APO** — Automatic Prompt Optimization. Technique for evolving agent system prompts.

**Bases** — Feature store for entity-centric data with temporal queries.

**CLT** — Cross-Layer Transcoder. Extracts sparse interpretable features from model activations.

**Death Loop** — An H1 topological feature (persistent cycle) in embedding space. Indicates feedback loops, circular dependencies, or systemic risk.

**devenv** — Nix-based development environment providing reproducible builds.

**DQL** — Domain Query Language. Query syntax for the Bases feature store.

**FMEA** — Failure Mode and Effects Analysis. Quantitative risk assessment using RPN scoring.

**Guru Meditation Code** — Unique error identifier (e.g., `#DS.00000001.SVCNOTINIT`). Inspired by the Amiga.

**H0/H1/H2** — Homology dimensions: H0 = connected components, H1 = loops, H2 = voids.

**HOCON** — Human-Optimized Config Object Notation. Configuration file format used by Gaius.

**Just** — Command runner replacing devenv-tasks. Reads recipes from `justfile`.

**KServe OIP** — Open Inference Protocol. Standard gRPC interface for ML inference.

**LuxCore** — Unbiased path tracing renderer used for card visualizations.

**Makespan** — Total time from start to finish of a multi-step workload (eviction, loading, inference, restoration).

**MCP** — Model Context Protocol. Programmatic interface exposing 163 tools to AI assistants.

**optillm** — Inference-time reasoning enhancement (CoT, BoN, MoA techniques).

**PATHOCL** — LuxCore rendering engine using OpenCL/CUDA for GPU acceleration.

**RASE** — Rapid Agentic Systems Engineering. Python-native MBSE metamodel for verifiable agent training.

**RLVR** — Reinforcement Learning with Verifiable Reward. Agent training methodology.

**RPN** — Risk Priority Number. FMEA score: Severity x Occurrence x Detection (range 1-1000).

**Tenuki** — Go term for playing away from the current area. In Gaius, jumps the cursor to a strategic point.

**Theta Consolidation** — Memory compression inspired by hippocampal theta rhythms. Links knowledge across temporal slices.

**TUI** — Terminal User Interface. Interactive Textual application launched with `uv run gaius`.

**vLLM** — High-throughput LLM inference engine. Managed by the Orchestrator across 6 GPUs.
