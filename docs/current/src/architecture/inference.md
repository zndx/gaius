# Inference

The inference layer routes requests across multiple backends: vLLM for local GPU models, optillm for reasoning enhancement, and external APIs (xAI, Cerebras) for cloud-based inference. All requests flow through a priority scheduler backed by OR-Tools CP-SAT.

## Backend Router

The `BackendRouter` (`inference/router.py`) selects backends based on capability requirements — model availability, GPU allocation, and whether reasoning enhancement is requested. Routing decisions are logged to `routing_analytics.py` for offline analysis of backend utilization patterns.

| Backend | Purpose | Hardware |
|---------|---------|----------|
| vLLM | Local model inference | 6x NVIDIA GPUs |
| optillm | Reasoning enhancement (CoT, BoN, MoA) | Proxies to vLLM |
| xAI (Grok) | External API inference | Cloud |
| Cerebras | External API inference | Cloud |
| Nomic | Text embeddings (768-dim) | 1 GPU |

## Scheduler

The scheduler (`inference/scheduler.py`) implements priority-based job assignment using OR-Tools CP-SAT (Google, 2024) for constraint satisfaction:

| Priority | Level | Use Case |
|----------|-------|----------|
| CRITICAL (0) | User-facing requests, leader synthesis | Preempts lower priorities |
| HIGH (1) | Swarm agent calls | Parallel execution |
| NORMAL (2) | Background tasks | Queue-ordered |
| LOW (3) | Speculative inference | Fills idle capacity |

The CP-SAT solver minimizes weighted completion time subject to endpoint capacity, GPU memory limits, and tensor parallelism requirements. Preemption is enabled by default — a CRITICAL job can interrupt LOW work.

## Synthesis Pipeline

The `ZettelkastenSynthesizer` (`inference/synthesis.py`) generates structured notes from multi-source retrieval:

1. **Query** — Input question or topic
2. **KB search** — Vector similarity search over existing knowledge base entries
3. **Web search** — Brave API retrieval for external sources
4. **Source ranking** — Citations scored by relevance (0.0–1.0) and deduplicated
5. **LLM synthesis** — Generates a Zettelkasten note with inline citations
6. **Persistence** — Note saved to KB with full citation provenance

Each note carries structured `Citation` objects (source path/URL, quote excerpt, relevance score), enabling downstream traceability.

## Evaluation System

Output quality is assessed via a tiered evaluation pipeline (`inference/evaluation.py`):

| Tier | Model | Use Case |
|------|-------|----------|
| Local | Orchestrator-8B (vLLM) | Quick filtering, high-volume |
| XAI | Grok 4.1 Fast | Promotion decisions, high-stakes |

Five quality dimensions are scored: accuracy, coherence, relevance, completeness, and clarity. Budget controls limit XAI evaluations to high-stakes decisions (configurable daily/weekly caps). Local evaluation runs on the same vLLM infrastructure as inference, using a lightweight model that doesn't compete for GPU resources with the primary reasoning endpoints.

## optillm Techniques

Reasoning enhancement via optillm (Maheshwari, 2024), which proxies to vLLM and applies inference-time techniques:

| Technique | Description |
|-----------|-------------|
| `cot_reflection` | Chain-of-thought with self-reflection |
| `bon` | Best-of-N sampling |
| `moa` | Mixture of Agents |
| `rto` | Round-trip optimization |
| `z3` | Z3 solver integration |
| `leap` | Learn from examples |

## Request Flow

```
Client → gRPC → Scheduler (priority queue) → BackendRouter → Backend
                                                             ↗ vLLM (local GPU)
                                                            ↗ optillm → vLLM
                                                           ↗ xAI API (cloud)
```

All inference requests route through the gRPC engine (port 50051) for centralized scheduling, audit logging, and resource management. The scheduler enforces job priorities and endpoint capacity limits before dispatching to the router.

## Subchapters

- [vLLM Controller](./vllm.md) — GPU process management
- [Makespan Scheduling](./makespan.md) — Multi-workload optimization
- [XAI Budget](./xai-budget.md) — External API rate limiting
