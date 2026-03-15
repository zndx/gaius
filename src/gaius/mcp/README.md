# Gaius MCP

Internal programmatic access to MCP tool operations. Provides a Python API for agents and components to invoke MCP tools without going through the MCP server.

## Architecture

```mermaid
graph TB
    subgraph "External"
        CC[MCP Client]
        MCP_SRV[MCP Server]
    end

    subgraph "Internal"
        AGENTS[Agents]
        THETA[ThetaAgent]
        SWARM[SwarmOrchestrator]
    end

    subgraph "MCP Operations"
        OPS[operations.py]
    end

    subgraph "Engine"
        INF[Inference]
        SCHED[Scheduler]
    end

    CC --> MCP_SRV
    MCP_SRV --> OPS
    AGENTS --> OPS
    THETA --> OPS
    SWARM --> OPS
    OPS --> INF
    OPS --> SCHED
```

## Module Structure

```
mcp/
├── __init__.py       # Module exports
└── operations.py     # ask_reasoning, run_swarm
```

## Operations

### ask_reasoning

Query the reasoning model for complex analysis:

```python
from gaius.mcp import ask_reasoning

result = await ask_reasoning(
    question="Analyze the trade-offs between TIES and DARE model merging.",
    system_prompt="You are an ML researcher.",
    max_tokens=2048,
)

print(result.content)
print(f"Tokens: {result.tokens_used}")
```

### run_swarm

Execute multi-agent swarm analysis:

```python
from gaius.mcp import run_swarm

result = await run_swarm(
    query="What are the implications of Ollivier-Ricci curvature for KB topology?",
    domain="tda",
    num_agents=7,
)

print(result.synthesis)
for agent in result.agent_outputs:
    print(f"{agent.role}: {agent.summary}")
```

## Use Cases

### Agent Internal Calls

Agents can invoke MCP operations programmatically:

```python
class ThetaAgent:
    async def consolidate(self):
        # Use reasoning for complex analysis
        analysis = await ask_reasoning(
            question=f"Analyze drift between temporal slices: {slices}",
        )

        # Use swarm for multi-perspective synthesis
        synthesis = await run_swarm(
            query="Identify cross-temporal patterns",
            domain=self.domain,
        )
```

### Cognition Cycles

Self-observation uses MCP operations:

```python
class CognitionAgent:
    async def self_observe(self):
        reflection = await ask_reasoning(
            question="Analyze recent thought patterns for themes.",
            system_prompt="You are analyzing your own cognitive patterns.",
        )
```

## Interface

### AskReasoningResult

```python
@dataclass
class AskReasoningResult:
    content: str
    tokens_used: int
    model: str
    latency_ms: int
```

### SwarmResult

```python
@dataclass
class SwarmResult:
    synthesis: str
    agent_outputs: list[AgentOutput]
    total_tokens: int
    latency_ms: int

@dataclass
class AgentOutput:
    role: str
    content: str
    summary: str
```

## Relationship to MCP Server

The `mcp_server.py` exposes tools to MCP clients. The `mcp/operations.py` module provides the same functionality as a Python API for internal use:

| MCP Tool | Internal Function |
|----------|-------------------|
| `ask_reasoning` | `mcp.ask_reasoning()` |
| `run_swarm` | `mcp.run_swarm()` |

This avoids code duplication and ensures consistent behavior.

## Call Graph

```
# ask_reasoning Path
agents.theta.ThetaAgent.consolidate()
  └─→ mcp.operations.ask_reasoning(question)
      └─→ inference.client.InferenceClient.complete()
          └─→ client.grpc_client.infer()
              └─→ engine → vLLM

# run_swarm Path
agents.cognition.CognitionAgent.self_observe()
  └─→ mcp.operations.run_swarm(query, domain)
      └─→ agents.swarm.SwarmManager.analyze()
          └─→ [for each role]
              └─→ inference.parallel_inference()
                  └─→ synthesize() → SwarmResult

# MCP Server to Operations
mcp_server.py:@mcp.tool("ask_reasoning")
  └─→ mcp.operations.ask_reasoning(question)
      └─→ ... (same path as above)
```

## Data Flow

```mermaid
graph TB
    subgraph External["External Caller"]
        CC[MCP Client]
        IA[Internal Agent]
        THETA[ThetaAgent]
    end

    subgraph MCP["mcp/operations.py"]
        ASK[ask_reasoning]
        SWARM[run_swarm]
    end

    IC[InferenceClient<br/>.complete]
    SM[SwarmManager<br/>.analyze]

    subgraph Engine["engine"]
        GRPC[gRPC]
        VLLM[vLLM]
        RESP[Response]
    end

    CC --> MCP
    IA --> MCP
    THETA --> MCP
    ASK --> IC
    SWARM --> SM
    IC --> Engine
    SM --> Engine
    GRPC --> VLLM
    VLLM --> RESP
```

## Integration Points

| Component | Uses | Used By | Integration |
|-----------|------|---------|-------------|
| `ask_reasoning()` | inference.client | theta, cognition, mcp_server | Direct call |
| `run_swarm()` | agents.swarm | theta, cognition, mcp_server | Direct call |
| `AskReasoningResult` | — | callers | Return type |
| `SwarmResult` | — | callers | Return type |

## See Also

- [Parent README](../README.md) — Module overview
- [Agents README](../agents/README.md) — Agent integration
- [Inference README](../inference/README.md) — Underlying inference
- [mcp_server.py](../mcp_server.py) — MCP protocol server

---

<!-- GAI:META
module: gaius.mcp
layer: L5-orchestration
key_types: [AskReasoningResult, SwarmResult, AgentOutput]
key_funcs: [ask_reasoning, run_swarm]
submodules: []
depends: [inference.client, agents.swarm]
dependents: [agents.theta, agents.cognition, mcp_server]
config_keys: []
env_vars: []
grpc_services: []
call_paths:
  reasoning: theta→mcp.ask_reasoning→inference.client.complete→engine
  swarm: cognition→mcp.run_swarm→SwarmManager.analyze→parallel_inference
test_cmds:
  reason: 'uv run gaius-cli --cmd "/ask \"test question\""'
  swarm: 'uv run gaius-cli --cmd "/swarm \"analysis query\" --domain test"'
guru_codes: []
fail_fast: true
-->
