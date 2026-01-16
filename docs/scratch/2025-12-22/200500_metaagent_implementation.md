# MetaAgent Implementation Summary

## Overview

Implemented **MetaAgent**, the unified analytics interface for the Gaius platform on the `feature/metaagent` branch. MetaAgent is a DeepAgents-style multi-agent system that answers natural language questions by correlating data from multiple sources.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         MetaAgent                               │
├─────────────────────────────────────────────────────────────────┤
│  User Question: "Why are arxiv flows slow?"                     │
│                                                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐│
│  │ Lineage    │  │ Operations │  │ Resource   │  │ Topology   ││
│  │ Analyst    │  │ Analyst    │  │ Analyst    │  │ Analyst    ││
│  │ (Cypher)   │  │ (SQL)      │  │ (SQL)      │  │ (SQL)      ││
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘│
│        └───────────────┴───────────────┴───────────────┘       │
│                              │                                  │
│                       ┌──────▼──────┐                          │
│                       │  Correlator │                          │
│                       │ (Synthesis) │                          │
│                       └──────┬──────┘                          │
│                              │                                  │
│  Answer + Evidence (DOT, Markdown)                              │
└─────────────────────────────────────────────────────────────────┘
```

## Data Sources

- **Lineage**: AGE graph for data provenance (Cypher queries on `gaius_hx`)
- **Operations**: Flow runs, agent performance (SQL on `meta.flow_runs`)
- **Resources**: GPU utilization, inference throughput (SQL on `meta.*`)
- **Topology**: Document clusters, semantic regions (SQL on `meta.kb_topology`)

## Files Created/Modified

### New Files

1. **`src/gaius/agents/metaagent_swarm.py`** (~600 lines)
   - `MetaAgentManager` - orchestrates multi-agent analysis
   - `MetaAgentResult` - result dataclass
   - `MetaAgentEvent` - streaming event
   - `AnalystInsight` - per-analyst result
   - `_execute_cypher()` - AGE graph queries
   - `_execute_sql()` - Meta schema queries
   - `_generate_dot()` - GraphViz output
   - `_generate_markdown_tables()` - Evidence tables

### Modified Files

1. **`src/gaius/engine/proto/gaius_service.proto`**
   - Added `MetaAgentQueryRequest`, `MetaAgentQueryResponse`, `MetaAgentEvent`
   - Added `MetaAgentQuery` and `MetaAgentQueryStream` RPCs

2. **`src/gaius/agents/roles.py`**
   - Added 5 new roles: `LINEAGE_ANALYST`, `OPERATIONS_ANALYST`, `RESOURCE_ANALYST`, `TOPOLOGY_ANALYST`, `CORRELATOR`
   - Added `METAAGENT_ROLES` and `METAAGENT_ANALYST_ROLES` registries
   - Each role has domain-specific system prompts with SQL/Cypher examples

3. **`src/gaius/agents/__init__.py`**
   - Exported MetaAgent classes

4. **`src/gaius/engine/generated/__init__.py`**
   - Exported MetaAgent proto messages

5. **`src/gaius/engine/grpc/servicers/gaius_servicer.py`**
   - Implemented `MetaAgentQuery` method
   - Implemented `MetaAgentQueryStream` method

6. **`src/gaius/client/grpc_client.py`**
   - Added `_call_gaius()` handler for MetaAgent service calls

7. **`src/gaius/mcp_server.py`**
   - Added `metaagent_query` MCP tool

8. **`src/gaius/cli.py`**
   - Added `/meta` command

## Usage

### CLI

```bash
# Get help
/meta

# Ask a question
/meta Why are arxiv flows slow?
/meta What sources feed into the CSA docs?
/meta Which agents have the best performance?
```

### MCP Tool

```
metaagent_query(query="...", domains="lineage,ops")
```

### gRPC

```protobuf
rpc MetaAgentQuery(MetaAgentQueryRequest) returns (MetaAgentQueryResponse);
rpc MetaAgentQueryStream(MetaAgentQueryRequest) returns (stream MetaAgentEvent);
```

## Key Design Decisions

1. **Engine-centric**: All capabilities exposed via gRPC, following the "Engine is ALL" principle
2. **Two-phase execution**: Parallel analysts → Correlator synthesis
3. **Security**: Read-only queries (MATCH/SELECT only), no write operations allowed
4. **Evidence formats**: DOT graphs and Markdown tables for visualization
5. **Streaming support**: Real-time progress events for UI feedback

## Testing

```bash
# Verify imports
uv run python -c "from gaius.agents.metaagent_swarm import MetaAgentManager; print('OK')"

# Test CLI (requires running engine)
uv run gaius-cli --cmd "/meta What documents are in the KB?" --format json
```

## Next Steps

1. **Improve prompts**: Fine-tune analyst system prompts for better query generation
2. **Add caching**: Cache frequent queries to reduce latency
3. **Expand domains**: Add more analyst types (e.g., EmbeddingAnalyst, PerformanceAnalyst)
4. **UI integration**: Add MetaAgent panel to TUI
