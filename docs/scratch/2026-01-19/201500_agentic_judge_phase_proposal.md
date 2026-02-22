# Agentic Judge Phase Architecture Proposal

**Date**: 2026-01-19
**Status**: Design Proposal
**Related**: Agent-as-a-Judge Survey (arXiv:2601.05111)

## Problem Statement

The current Judge phase (Phase 5) in MetaAgent's Multi-Agent Debate is a single LLM call that synthesizes debate findings. While effective, it lacks:

1. **Tool Integration**: Cannot verify claims by executing commands or querying systems
2. **Evidence Collection**: Cannot fetch additional context mid-synthesis
3. **Dynamic Evaluation**: Cannot invoke RASE verification cases to test recommendations
4. **Multi-Agent Dynamics**: No sub-deliberation for complex disputes

This limits the Judge to Stage 2 (Reactive) in the Agent-as-a-Judge taxonomy when Stage 3 (Self-Evolving) capabilities are architecturally achievable.

## Proposed Architecture

Transform Phase 5 from a single LLM call into an agentic loop with MCP tool access:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Agentic Judge Phase                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 5a: Initial Synthesis                                                  │
│   XAI Grok analyzes debate transcript, identifies:                          │
│   - Claims requiring verification                                            │
│   - Missing evidence gaps                                                    │
│   - Disputed actionability assertions                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
┌───────────────────────┐ ┌───────────────────┐ ┌───────────────────────┐
│ Phase 5b: Tool Use    │ │ Phase 5c: KB Eval │ │ Phase 5d: Sub-Debate │
│                       │ │                   │ │                       │
│ MCP Tools:            │ │ RASE Verification:│ │ Mini-Debate:          │
│ - gpu_health          │ │ - Load objective  │ │ - Spawn sub-agents    │
│ - orchestrator_status │ │ - Build KBState   │ │ - Focused dispute     │
│ - health_observer_*   │ │ - Evaluate gates  │ │ - Consensus seeking   │
│ - search_kb           │ │ - Return verdict  │ │                       │
│ - read_kb             │ │   + accuracy      │ │ (For high-stakes      │
│                       │ │                   │ │  disagreements only)  │
└───────────────────────┘ └───────────────────┘ └───────────────────────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 5e: Final Verdict                                                      │
│   XAI Grok synthesizes all evidence into final verdict                      │
│   - Tool results inform confidence adjustments                              │
│   - RASE verdicts validate recommendations                                  │
│   - Sub-debate outcomes resolve disputes                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## MCP Tool Integration

### Available Tools for Judge

The Judge agent gains access to a curated subset of MCP operations:

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `gpu_health` | Verify GPU state claims | "GPU 4 is overloaded" |
| `orchestrator_status` | Validate endpoint health | "reasoning endpoint is down" |
| `health_observer_incidents` | Check active incidents | "there's an ongoing issue" |
| `search_kb` | Find related heuristics | "similar incident in past" |
| `read_kb` | Load specific heuristic | Validate remediation approach |
| `verify_objective` | RASE verification | Validate recommendation quality |

### Tool Invocation Pattern

```python
# In metaagent_debate.py

AGENTIC_JUDGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "verify_gpu_state",
            "description": "Check actual GPU health to verify claims about GPU status",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_endpoint_health",
            "description": "Check if an endpoint is actually healthy/unhealthy",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "description": "Endpoint name"}
                },
                "required": ["endpoint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_precedent",
            "description": "Search KB for similar past incidents or heuristics",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_recommendation",
            "description": "Use RASE to verify a recommendation meets quality gates",
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendation": {"type": "string"},
                    "objective": {"type": "string", "description": "Objective name"}
                },
                "required": ["recommendation"]
            }
        }
    }
]
```

## Dynamic KB Evaluation

### RASE Integration

The Judge can invoke RASE verification to validate recommendations:

```python
async def _verify_with_rase(
    self,
    recommendation: str,
    objective_name: str = "audit-recommendation-quality",
) -> dict:
    """Verify recommendation meets RASE quality gates.

    Uses the KB domain's KBVerificationCase to evaluate:
    - Syntactic: Is the recommendation well-formed?
    - Semantic: Does it align with KB heuristics?
    - Empirical: Is the command actually executable?

    Returns:
        Dict with verdict, accuracy, and graded_reward
    """
    from gaius.rase.domains.kb.verification import KBVerificationCase
    from gaius.rase.domains.kb.state import KBState
    from gaius.rase.domains.kb.objective import load_objective

    # Load objective from KB
    objective = load_objective(f"current/objectives/{objective_name}.md")

    # Build verification case
    case = KBVerificationCase(objective=objective)

    # Create state from recommendation
    state = KBState.from_text(recommendation)

    # Evaluate
    result = case.evaluate(state)

    return {
        "verdict": result.verdict.value,
        "accuracy": result.accuracy,
        "graded_reward": result.reward.value if result.reward else 0.0,
        "gate_results": {
            name: r.satisfied
            for name, r in result.constraint_results.items()
        }
    }
```

### Objective for Audit Recommendations

Create a RASE objective specifically for validating audit recommendations:

```markdown
---
name: audit-recommendation-quality
priority: P1
gates:
  - level: syntactic
    name: WellFormedCommand
    constraint: CommandParseable
  - level: semantic
    name: AlignedWithHeuristics
    constraint: ReferencesKBHeuristic
  - level: empirical
    name: ActuallyExecutable
    constraint: CommandExists
---

# Audit Recommendation Quality

Verifies that MetaAgent audit recommendations meet quality standards.

## Syntactic Gate
- Commands parse correctly
- Follows `/health fix` or `devenv tasks run` patterns

## Semantic Gate
- References existing KB heuristics
- Aligns with FMEA failure mode catalog

## Empirical Gate
- Command can be located in codebase
- Prerequisites can be verified
```

## Multi-Agent Sub-Debate

For high-stakes disputes (confidence delta > 0.3), spawn a focused mini-debate:

```python
async def _run_sub_debate(
    self,
    dispute: str,
    analyst_position: str,
    skeptic_position: str,
) -> str:
    """Spawn focused sub-debate for contentious finding.

    Uses two sub-agents to deliberate specifically on the
    disputed claim, returning a consensus or majority verdict.

    Args:
        dispute: The specific claim in dispute
        analyst_position: Why analyst believes the finding
        skeptic_position: Why skeptic challenges it

    Returns:
        Sub-debate verdict with reasoning
    """
    # This could use run_swarm with 2 agents focused on the dispute
    from gaius.mcp.operations import run_swarm

    result = await run_swarm(
        query=f"Resolve this dispute: {dispute}\n\n"
              f"Position A (Analyst): {analyst_position}\n\n"
              f"Position B (Skeptic): {skeptic_position}",
        domain="audit",
        num_agents=2,
    )

    return result.get("synthesis", "")
```

## Implementation Phases

### Phase 1: Tool Integration (Immediate)
- Add `AGENTIC_JUDGE_TOOLS` to debate coordinator
- Implement tool handlers in `_run_judge_synthesis`
- Use XAI's function calling for tool selection

### Phase 2: RASE Verification (Short-term)
- Create `audit-recommendation-quality.md` objective
- Add `_verify_with_rase` method
- Integrate verification results into final verdict

### Phase 3: Sub-Debate (Long-term)
- Implement `_run_sub_debate` for focused disputes
- Add dispute detection logic
- Track sub-debate outcomes in transcript

## Budget Impact

| Component | Calls | Tokens | Cost |
|-----------|-------|--------|------|
| Phase 5a (Initial) | 1 | ~2K | $0.04 |
| Phase 5b (Tools) | 0-3 | ~1K each | $0.06 |
| Phase 5c (RASE) | 0-1 | ~500 | $0.01 |
| Phase 5d (Sub-Debate) | 0-2 | ~3K | $0.06 |
| Phase 5e (Final) | 1 | ~2K | $0.04 |

**Worst case**: ~$0.21 per audit (vs current $0.08)
**Typical case**: ~$0.12 per audit (1 tool call, no sub-debate)

## Benefits

1. **Grounded Verdicts**: Claims verified against actual system state
2. **Quality Gates**: RASE ensures recommendations meet standards
3. **Dispute Resolution**: Sub-debates produce robust consensus
4. **Stage 3 Capability**: Enables self-evolving judge through RASE feedback

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Tool call loops | Budget exhaust | Max 5 tool calls per phase |
| RASE false negatives | Good recs rejected | Human override in KB |
| Sub-debate divergence | No consensus | Timeout + Judge decides |
| Latency increase | Slow audits | Parallel tool calls |

## Conclusion

Augmenting the Judge phase with MCP tools, RASE verification, and optional sub-debates transforms MetaAgent from Stage 2 (Reactive) to Stage 3 (Self-Evolving) in the Agent-as-a-Judge taxonomy. The architecture remains within the existing MetaAgent service while adding targeted agency where it provides the most value.

---
*Architecture proposal informed by arXiv:2601.05111 "A Survey on Agent-as-a-Judge"*
