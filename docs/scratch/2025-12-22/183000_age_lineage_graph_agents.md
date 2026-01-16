# AGE Lineage Graph for Code Agent Analysis

Date: 2025-12-22
Status: **IMPLEMENTED**

## Vision

Local code agents write and execute Cypher queries against the Apache AGE graph to:
1. Trace provenance of any KB resource back to original sources
2. Understand which processes (jobs, transforms) produced derived artifacts
3. Track fine-tuned adapter lineage from training data through KB to model checkpoints
4. Detect stale content by graph traversal rather than per-file checks

## Current Infrastructure

### OpenLineage Events Table (Active)
```sql
-- 71 events across 41 runs in 4 namespaces
SELECT job_namespace, job_name, run_state, count(*)
FROM lineage_events GROUP BY 1,2,3;

-- gaius.datasets | nifi_som_generation
-- gaius.fetch    | arxiv
-- gaius.flows    | arxiv_docling
-- gaius.storage  | kb_sync
```

### AGE Graph Structure (Schema Ready)
```
Vertex Labels:
  - Dataset   (Data sources/sinks: KB files, S3 objects, URLs)
  - Job       (Processing definitions: sync, fetch, transform)
  - Run       (Execution instances with timestamps)

Edge Labels:
  - INPUT_TO  (Dataset → Run: what data was consumed)
  - OUTPUTS   (Run → Dataset: what data was produced)
  - PARENT    (Run → Run: nested/child runs)
  - EXECUTES  (Job → Run: which job spawned this run)
```

### Materialization Gap
Events are recorded but not yet materialized to graph:
- `processed = false` for all 71 events
- Graph vertices/edges not yet populated

## Implementation Plan

### Phase 1: Graph Materialization Worker

Create a background worker that processes pending events:

```python
# gaius/lineage/materializer.py
async def materialize_event(event: LineageEvent, conn: asyncpg.Connection):
    """Convert OpenLineage event to AGE graph elements."""

    # Create/update Dataset vertices for inputs
    for input_ds in event.inputs:
        await conn.execute("""
            SELECT * FROM cypher('gaius_hx', $$
                MERGE (d:Dataset {namespace: $ns, name: $name})
                SET d.updated_at = $ts
                RETURN d
            $$) AS (d agtype)
        """, input_ds['namespace'], input_ds['name'], event.event_time)

    # Create Run vertex
    await conn.execute("""
        SELECT * FROM cypher('gaius_hx', $$
            MERGE (r:Run {run_id: $run_id})
            SET r.state = $state, r.event_time = $ts
            RETURN r
        $$) AS (r agtype)
    """, str(event.run_id), event.run_state, event.event_time)

    # Create edges
    for input_ds in event.inputs:
        await conn.execute("""
            SELECT * FROM cypher('gaius_hx', $$
                MATCH (d:Dataset {namespace: $ns, name: $name})
                MATCH (r:Run {run_id: $run_id})
                MERGE (d)-[:INPUT_TO]->(r)
            $$) AS (e agtype)
        """, input_ds['namespace'], input_ds['name'], str(event.run_id))
```

### Phase 2: Query Interface for Code Agents

Expose graph queries via MCP tool that local models can invoke:

```python
# gaius/mcp_server.py
@mcp_tool
async def lineage_query(cypher: str) -> dict:
    """Execute Cypher query on lineage graph.

    Args:
        cypher: Cypher query string (read-only for safety)

    Returns:
        Query results as JSON
    """
    if not is_read_only_query(cypher):
        raise ValueError("Only read queries allowed")

    return await execute_age_query(cypher)
```

### Phase 3: Code Agent Prompts

System prompt for lineage-aware agents:

```markdown
You have access to `lineage_query` tool to query the gaius_hx
Apache AGE graph. The graph follows OpenLineage standard:

Vertices:
- Dataset: {namespace, name, updated_at}
- Job: {namespace, name}
- Run: {run_id, state, event_time}

Edges:
- INPUT_TO: Dataset used by Run
- OUTPUTS: Run produced Dataset
- PARENT: Run is child of Run
- EXECUTES: Job spawned Run

Example queries:

-- Trace KB file to original source
MATCH path = (source:Dataset)-[:INPUT_TO|OUTPUTS*]->(kb:Dataset)
WHERE kb.name = 'current/cloudera/docs/csa/overview.md'
  AND source.namespace = 'external'
RETURN path

-- Find all runs that produced training data
MATCH (r:Run)-[:OUTPUTS]->(d:Dataset)
WHERE d.namespace = 'gaius.training'
RETURN r.run_id, d.name, r.event_time

-- Impact analysis: what's affected if source changes
MATCH (source:Dataset {name: 'csa-docs-archive.zip'})-[:INPUT_TO|OUTPUTS*]->(affected)
RETURN DISTINCT affected.namespace, affected.name
```

## Query Examples for Key Use Cases

### 1. KB Resource Provenance
```cypher
-- What sources feed into this KB document?
MATCH path = (source:Dataset)-[:INPUT_TO|OUTPUTS*1..10]->(target:Dataset)
WHERE target.namespace = 'kb'
  AND target.name CONTAINS 'cloudera/docs/csa'
  AND source.namespace IN ['external', 'archive', 'filesystem']
RETURN source.namespace, source.name, length(path) as hops
ORDER BY hops
```

### 2. Adapter Training Lineage
```cypher
-- What KB documents contributed to this adapter?
MATCH (kb:Dataset)-[:INPUT_TO]->(train:Run)-[:OUTPUTS]->(adapter:Dataset)
WHERE adapter.name = 'adapters/csa-specialist-v3.safetensors'
RETURN kb.name, train.event_time
ORDER BY train.event_time DESC
```

### 3. Stale Content Detection
```cypher
-- KB files not updated since source changed
MATCH (source:Dataset)-[:INPUT_TO]->(r:Run)-[:OUTPUTS]->(kb:Dataset)
WHERE source.namespace = 'external'
  AND kb.namespace = 'kb'
  AND source.updated_at > kb.updated_at
RETURN kb.name, source.name,
       source.updated_at as source_updated,
       kb.updated_at as kb_updated
```

### 4. Process Dependency Graph
```cypher
-- What jobs depend on this job's output?
MATCH (j1:Job)-[:EXECUTES]->(:Run)-[:OUTPUTS]->(d:Dataset)
      -[:INPUT_TO]->(:Run)<-[:EXECUTES]-(j2:Job)
WHERE j1.name = 'cloudera_docs_sync'
RETURN DISTINCT j2.namespace, j2.name
```

## Integration with Content Provenance

The new `gaius.rase.domains.kb.provenance` module provides:
- `ContentSource` → maps to Dataset vertex
- `KBResourceLineage` → subgraph pattern
- `record_lineage_event()` → creates events for materialization

```python
# When syncing Cloudera docs, record lineage
await record_lineage_event(
    run_id=str(uuid4()),
    job_namespace="gaius.sync",
    job_name="cloudera_docs",
    run_state="COMPLETE",
    inputs=[{
        "namespace": "archive",
        "name": "https://docs.cloudera.com/downloads/csa-docs-archive.zip",
        "facets": {"version": "1.5.4", "hash": "541b2c78..."}
    }],
    outputs=[{
        "namespace": "kb",
        "name": "current/cloudera/docs/csa/1.5.4/overview.md",
        "facets": {"word_count": 1234}
    }],
)
```

## Security Considerations

1. **Read-only by default**: MCP tool only allows SELECT/MATCH queries
2. **Query sanitization**: Validate Cypher before execution
3. **Rate limiting**: Prevent expensive graph traversals
4. **Audit logging**: Track which queries agents execute

## Implementation Status

1. [x] Graph materialization - Already working via `LineageEmitter`
2. [x] `lineage_cypher` MCP tool - Added for arbitrary Cypher queries
3. [x] Security - Read-only enforcement (MATCH/RETURN only)
4. [ ] Create agent system prompts with Cypher examples
5. [ ] Build staleness detection using graph queries
6. [ ] Visualize lineage graph in TUI (optional)

## Usage

The `lineage_cypher` MCP tool allows code agents to execute read-only Cypher:

```python
# Via MCP
result = await mcp__gaius__lineage_cypher(
    cypher='MATCH (s:Dataset)-[:INPUT_TO]->(:Run)-[:OUTPUTS]->(kb:Dataset) '
           'WHERE s.namespace = "gaius.source" '
           'RETURN s.name, kb.name LIMIT 10'
)

# Returns:
{
  "query": "...",
  "row_count": 10,
  "results": [
    {"c0": "arxiv:2312.10997", "c1": "scratch/2025-12-15/...retrieval-augmented...md"},
    ...
  ]
}
```

## Current Graph State

- **75 Dataset vertices** (KB files, sources, HX content)
- **37 Run vertices** (job executions)
- **3 Job vertices** (arxiv fetch, arxiv_docling, nifi_som_generation)
- **130 edges** (INPUT_TO, OUTPUTS, EXECUTES)
