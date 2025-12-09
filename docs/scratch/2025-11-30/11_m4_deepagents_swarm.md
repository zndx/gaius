# M4: DeepAgents Swarm Implementation

## Summary

Completed Milestone 4 of the Gaius v1.0 roadmap, implementing the multi-agent
swarm orchestration system with role definitions, model routing, and grid integration.

## Deliverables Completed

### 1. Agent Role Definitions (`src/gaius/agents/roles.py`)

**7 Agent Roles:**

| Role | Description | Color | Projection | Temperature |
|------|-------------|-------|------------|-------------|
| Leader | Strategic oversight, consensus | red | center | 0.6 |
| Risk | Threat identification | green | peripheral | 0.5 |
| Optimizer | Opportunity seeking | blue | random | 0.7 |
| Planner | Long-term trajectory | yellow | center | 0.6 |
| Critic | Assumption challenging | magenta | peripheral | 0.8 |
| Executor | Action simulation | cyan | random | 0.5 |
| Adversary | Plan breaking, stress test | white | peripheral | 0.9 |

**RoleDefinition dataclass:**
- System prompts with {domain} and {context} placeholders
- Behavioral parameters (temperature, max_tokens)
- Grid projection behavior (center/peripheral/random)
- Collaboration triggers (responds_to, triggers)

### 2. Swarm Manager (`src/gaius/agents/swarm.py`)

**SwarmManager class:**
- Parallel agent execution with `asyncio.gather`
- Sequential mode for debugging
- Agent position projection to grid
- Result aggregation with consensus from Leader

**SwarmRoundResult dataclass:**
- Tracks all agent responses
- Total tokens and latency
- Success rate calculation
- Consensus extraction

### 3. Model Router (`src/gaius/inference/router.py`)

**WorkflowPhase enum:**
- EXPLORATION: Fast local model (Qwen3 on vLLM)
- SYNTHESIS: Deep reasoning (optillm with COT)
- EVALUATION: Frontier model (Claude)
- SWARM: Balanced parallel agents

**ModelRouter class:**
- Phase-based model selection
- HOCON config overrides
- Convenience methods: explore(), synthesize(), evaluate(), swarm()

### 4. App Integration

**New commands:**
- `/swarm` - Run swarm analysis on current domain
- `/swarm <domain>` - Run on specified domain
- `/agents` - Show agent status and positions

**Auto-trigger:**
- `/domain <name>` triggers swarm if `swarm.auto_trigger_on_domain = true`
- Configurable in HOCON per profile

**Think panel integration:**
- Swarm rounds add ReasoningTrace
- Shows operation summary with token counts

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `src/gaius/agents/roles.py` | NEW | 7 agent role definitions |
| `src/gaius/agents/swarm.py` | NEW | Swarm orchestration manager |
| `src/gaius/inference/router.py` | NEW | Phase-based model router |
| `src/gaius/agents/__init__.py` | Modified | Export agents and swarm |
| `src/gaius/app.py` | Modified | /swarm, /agents, auto-trigger |

## Usage

```bash
# Run swarm on current domain
/swarm

# Run swarm on specific domain
/swarm distributed consensus algorithms

# Show agent status
/agents

# Change domain (auto-triggers swarm if enabled)
/domain pension asset allocation
```

## Configuration

HOCON settings in `config/base.conf`:

```hocon
gaius {
  swarm {
    enabled = true
    auto_trigger_on_domain = true
    roles = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]
  }

  inference {
    phase_models {
      exploration = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
      synthesis = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
      evaluation = "claude-sonnet-4-20250514"
    }
  }
}
```

## Architecture

```
/domain or /swarm command
         ↓
    SwarmManager
         ↓
    ┌────┴────┬────────┬────────┬────────┬─────────┬──────────┐
    ↓         ↓        ↓        ↓        ↓         ↓          ↓
 Leader    Risk   Optimizer Planner  Critic  Executor  Adversary
    │         │        │        │        │         │          │
    └─────────┴────────┴────────┴────────┴─────────┴──────────┘
                              ↓
                    SwarmRoundResult
                              ↓
              ┌───────────────┼───────────────┐
              ↓               ↓               ↓
         Agent positions  Think trace    Result summary
           (grid)         (panel)         (content)
```

## Next Steps (M5)

M5: Situational Awareness + Daily Summary includes:
1. Startup situational awareness report
2. Activity summary (today, yesterday, this week)
3. Daily summary agent
4. Profile-driven behavior switching
