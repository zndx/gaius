# MetaAgent Analytics

MetaAgent is Gaius's natural language interface to observability data. It translates questions into structured queries across multiple data domains, executing them in parallel and synthesizing correlated insights.

## Purpose

While [Metabase](https://www.metabase.com/) provides guided dashboards for quantitative exploration, MetaAgent enables conversational queries:

| Interface | Modality | Best For |
|-----------|----------|----------|
| Metabase | Visual dashboards | Exploring metrics, building reports |
| MetaAgent | Natural language | Specific questions, cross-domain correlation |

**Example queries:**
- "What sources feed into the CSA docs?"
- "Why might Cloudera docs sync be slow?"
- "How many documents are in the KB?"

## Architecture

MetaAgent deploys 4 specialized analysts in parallel, each querying a different data domain:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MetaAgent (gRPC)                            │
├─────────────────────────────────────────────────────────────────────┤
│  User Question: "Why are arxiv flows slow?"                         │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐│
│  │ Lineage      │  │ Ops          │  │ Resource     │  │ Topology ││
│  │ Analyst      │  │ Analyst      │  │ Analyst      │  │ Analyst  ││
│  │ (AGE/Cypher) │  │ (meta.*)     │  │ (meta.*)     │  │ (meta.*) ││
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────┬─────┘│
│         │                 │                 │                │      │
│         └─────────────────┴─────────────────┴────────────────┘      │
│                                    │                                │
│                            ┌───────▼───────┐                        │
│                            │  Correlator   │                        │
│                            │  (Synthesis)  │                        │
│                            └───────┬───────┘                        │
│                                    │                                │
│  Answer: "Flow processing 15 papers, GPU 2 at 98% memory..."        │
└─────────────────────────────────────────────────────────────────────┘
```

## The Four Analysts

| Analyst | Data Source | Query Language | Purpose |
|---------|-------------|----------------|---------|
| **LineageAnalyst** | Apache AGE graph | Cypher | Data provenance, dependencies |
| **OpsAnalyst** | `meta.flow_runs`, `meta.agent_performance` | SQL | Flow status, agent health |
| **ResourceAnalyst** | `meta.gpu_utilization`, `meta.inference_throughput` | SQL | GPU metrics, bottlenecks |
| **TopologyAnalyst** | `meta.kb_topology`, `meta.document_clusters` | SQL | KB structure, coverage |

Each analyst:
1. Receives the user's question
2. Generates an appropriate query (Cypher or SQL)
3. Executes it against the database
4. Returns structured findings

The **Correlator** synthesizes all findings into a coherent answer.

## Data Domains

### AGE Lineage Graph (`gaius_hx`)

The lineage graph tracks data provenance using OpenLineage semantics:

```cypher
-- Find sources that feed into CSA documentation
MATCH (s:Dataset)-[:INPUT_TO]->(:Run)-[:OUTPUTS]->(t:Dataset)
WHERE t.name CONTAINS 'csa'
RETURN s.namespace, s.name, t.name
```

Vertex types:
- **Dataset**: Files, KB entries, external sources
- **Job**: ETL pipelines, sync flows
- **Run**: Individual execution of a job

Edge types:
- `INPUT_TO`: Dataset consumed by a Run
- `OUTPUTS`: Run produces a Dataset
- `EXECUTES`: Job executes a Run

### Meta Schema (`meta.*`)

Analytics tables populated by MetaSyncFlow:

| Table | Content |
|-------|---------|
| `meta.flow_runs` | Flow executions with status, duration |
| `meta.job_catalog` | Aggregate job statistics |
| `meta.agent_performance` | Agent evaluation scores over time |
| `meta.gpu_utilization` | GPU memory and utilization time-series |
| `meta.inference_throughput` | Model throughput by hour |
| `meta.kb_topology` | Betti numbers, entropy, document counts |
| `meta.document_clusters` | HDBSCAN clusters with topics |

## Usage

### CLI

```bash
# Simple lineage query
uv run gaius-cli --cmd "/meta 'What sources feed into CSA docs?'" --format json

# Cross-domain correlation
uv run gaius-cli --cmd "/meta 'Why might Cloudera docs sync be slow?'" --format json

# KB topology
uv run gaius-cli --cmd "/meta 'How many documents are in the KB?'" --format json
```

### MCP Tool

```python
# Available as MCP tool: metaagent_query
result = await metaagent_query(
    query="What flows ran recently?",
    include_dot=True,      # GraphViz DOT visualization
    include_markdown=True  # Markdown evidence tables
)
```

### gRPC

```protobuf
rpc MetaAgentQuery(MetaAgentQueryRequest) returns (MetaAgentQueryResponse);
rpc MetaAgentQueryStream(MetaAgentQueryRequest) returns (stream MetaAgentEvent);
```

## Response Format

```json
{
  "question": "What sources feed into CSA docs?",
  "success": true,
  "answer": "The CSA documentation outputs are fed by two primary sources...",
  "agents_used": 4,
  "duration_ms": 9754,
  "queries_executed": [
    "MATCH (s:Dataset)-[:INPUT_TO]->(:Run)-[:OUTPUTS]->(t:Dataset)...",
    "SELECT name, namespace FROM meta.job_catalog WHERE name LIKE '%CSA%';",
    "SELECT NULL",
    "SELECT name, document_paths FROM meta.semantic_regions WHERE name = 'CSA'"
  ],
  "evidence_tables": 2,
  "dot_graph_bytes": 435
}
```

## Relationship to Other Systems

| System | Role | Integration |
|--------|------|-------------|
| **Metabase** | Visual dashboards | Queries same `meta.*` tables |
| **OpenTelemetry** | Runtime metrics | Future: OTelAnalyst for latency queries |
| **GEPA** | Prompt optimization | Future: Optimize Correlator synthesis |
| **Swarm** | Domain analysis | MetaAgent focuses on observability, Swarm on exploration |

## FMEA Failure Modes

MetaAgent has dedicated failure modes in the FMEA catalog:

| Code | Name | Description |
|------|------|-------------|
| `META_001` | Cypher Query Failure | AGE graph query errors |
| `META_002` | Analyst Timeout | Analyst taking >30s to respond |
| `META_003` | Correlator Empty | No analyst findings to synthesize |
| `META_004` | Entity Resolution Failure | KB semantic search returns no matches |

These integrate with the `/health` command for automated remediation.
