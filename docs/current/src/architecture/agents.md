# Agent System

The agent system provides LLM orchestration patterns for domain analysis: role-based prompt execution, parallel inference coordination, temporal consolidation, and background evolution.

## Execution Patterns

### Swarm Execution

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

Execution is parallel but not agentic — roles don't observe each other's outputs or iterate.

### Latent Swarm (LatentMAS)

Reduces inter-agent token transfer by sharing embeddings instead of text via Qdrant. Agents store output embeddings; subsequent agents retrieve relevant context via semantic search.

Token reduction: 70-90% compared to text-based coordination.

### MetaAgent Coordination

Specialist "analysts" answer natural language questions by querying structured data sources (Cypher for lineage, SQL for metrics). Results are synthesized by a correlator.

## Background Processes

Two background processes run within the engine:

- **Evolution Daemon**: Optimizes agent prompts during GPU idle periods
- **Cognition Agent**: Generates "thoughts" about patterns in KB activity (every 4-8h)

## Module Structure

```
agents/
├── swarm.py              # SwarmManager (parallel execution)
├── roles.py              # Role definitions (system prompts)
├── metaagent_swarm.py    # MetaAgentManager
├── cognition.py          # Pattern detection
├── theta/                # Temporal consolidation pipeline
├── latent/               # Qdrant-backed working memory
└── evolution/            # Prompt optimization
```

## Subchapters

- [Evolution](./evolution.md) — RLVR-based prompt optimization
- [Cognition](./cognition.md) — Autonomous thought generation
- [Theta Consolidation](./theta.md) — Temporal knowledge linking
- [CLT Memory](./clt.md) — Cross-Layer Transcoder features
