# Multi-Agent Swarms

Gaius deploys specialized agents to explore complex domains from multiple perspectives. This isn't a chatbot—it's a cognitive swarm that maps understanding onto the grid.

## Agent Architecture

Each agent is constructed via LangChain's DeepAgents framework with APO (Automatic Prompt Optimization) middleware:

```python
from deepagents import create_deep_agent
from agentlightning import APO

agent = create_deep_agent(
    model=llm,
    tools=[plan_tool, spawn_tool],
    system_prompt=role_description,
    middleware=[apo.middleware]
)
```

### DeepAgents Capabilities
- **Sub-agent spawning**: Agents can spawn specialized sub-agents for detailed analysis
- **Planning tools**: Structured multi-step reasoning
- **Memory access**: Query the shared vector store

### APO Middleware
Automatic Prompt Optimization tunes prompts dynamically:
- **Beam search**: Explores multiple prompt variants per round
- **Reward signal**: Domain-agnostic or custom reward functions
- **Live tuning**: Prompts improve over successive rounds

## The Seven Roles

| Agent | Perspective | Grid Projection |
|-------|-------------|-----------------|
| **Leader** | Strategic synthesis | Center-seeking |
| **Risk** | Threat identification | Peripheral scanning |
| **Optimizer** | Opportunity finding | Cluster-seeking |
| **Planner** | Long-term trajectory | Diagonal movement |
| **Critic** | Assumption challenging | Contrarian positioning |
| **Executor** | Action simulation | Edge-following |
| **Adversary** | Plan breaking | Chaos injection |

These roles are domain-agnostic templates. When instantiated with a domain:

```python
{"name": "Risk", "role": f"Identify threats in {domain}"}
```

## Swarm Round Execution

A swarm round proceeds as follows:

```
1. Task Construction
   └── User domain + scenario → task prompt

2. Parallel Agent Invocation
   ├── Leader.analyze(task)
   ├── Risk.analyze(task)
   ├── Optimizer.analyze(task)
   └── ... (concurrent)

3. Response Embedding
   └── Each response → 1536-dim vector

4. Memory Storage
   └── (agent_id, text, embedding) → Vector Memory

5. Scene Graph Construction
   └── Cosine similarity + domain boosting → edges

6. Point Cloud Update
   └── Embeddings → PCA → 2D coordinates

7. TDA Computation
   └── Point cloud → persistence diagrams → H1 features

8. Grid Projection
   └── 2D coordinates → [0,18] → grid positions

9. Board Refresh
   └── New positions rendered with agent colors
```

## Convergence and Divergence

Watch the swarm's spatial behavior:

**Convergence** (agents cluster):
- Consensus forming on interpretation
- Strong signal in the data
- Potential groupthink—consult Adversary

**Divergence** (agents scatter):
- Genuine ambiguity in the domain
- Multiple valid interpretations
- Rich territory for exploration

**Oscillation** (positions cycle):
- Unstable equilibria
- Ko-like situations
- May indicate missing information

## Domain Adaptation

Pressing `d` opens the domain modal. Entering a new domain:

1. Reconstructs all agent system prompts
2. Clears accumulated memory
3. Resets the point cloud
4. Runs an initial swarm round

The swarm "rewires" to the new domain instantly.

## APO Reward Signals

The APO middleware receives reward signals to guide prompt evolution:

```python
emit_reward("round_complete", 1.0)  # Round finished successfully
emit_reward(response, quality)       # Per-response quality score
```

Custom reward functions can encode domain-specific quality metrics:

```python
reward_fn = lambda output, gold: (
    1.0 if "risk" in output.lower() and mentions_specifics(output) else 0.5
)
```

## Extending the Swarm

Add new roles by extending the base templates:

```python
base_roles.append({
    "name": "Historian",
    "role": f"Identify precedents and patterns in {domain}"
})
```

Or create domain-specific swarms:

```python
pension_roles = [
    {"name": "Actuary", "role": "Model longevity and payout risk"},
    {"name": "Allocator", "role": "Optimize asset class distribution"},
    {"name": "Regulator", "role": "Ensure ERISA/DOL compliance"},
]
```

## Visualization

Agent positions are rendered as colored stones:

```python
colors = ["red", "green", "blue", "yellow", "magenta", "cyan", "white"]
for i, (xx, yy) in enumerate(zip(x_proj, y_proj)):
    grid[yy][xx] = f"[{colors[i]}]●[/{colors[i]}]"
```

The color encoding is fixed by role order. Over time, you'll develop intuition: "red is clustering in the corner—Risk sees something."

## Performance

Agent invocations are the bottleneck:
- 7 agents × ~500ms/call ≈ 3.5s sequential
- With async parallelism: ~500ms total

Always use `async` invocation for swarm rounds. The `@work` decorator handles this.
