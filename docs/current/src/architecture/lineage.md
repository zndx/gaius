# Lineage Tracking

Lineage tracking provides graph-based provenance that connects data sources to derived artifacts. Every pipeline stage emits OpenLineage events that are materialized into an Apache AGE graph stored in PostgreSQL.

## Architecture

```
Metaflow Pipelines ──┐
Fetch Workers ───────┤──> RunEvent ──> LineageEmitter ──> Apache AGE Graph
Agents ──────────────┘                                         |
                                                               v
                                                    Cypher Queries (MCP + CLI)
```

## Graph Schema

The lineage graph uses four vertex labels and four edge labels:

**Vertices:**
- `Dataset` -- a data source or sink (namespace, name)
- `Job` -- a processing definition (namespace, name)
- `Run` -- a single execution of a job (run_id, state, event_time)

**Edges:**
- `INPUT_TO` -- Dataset consumed by Run
- `OUTPUTS` -- Run produced Dataset
- `EXECUTES` -- Job spawned Run
- `PARENT` -- Run is child of another Run

## OpenLineage Events

Flows emit events at key lifecycle points:

| Event | Timing | Purpose |
|-------|--------|---------|
| `START` | Flow begin | Record input datasets |
| `COMPLETE` | Flow end | Record output datasets |
| `FAIL` | On error | Record failure with context |

```python
from gaius.hx.lineage import get_emitter, RunEvent, Dataset, Job

emitter = get_emitter()

event = RunEvent.complete(
    run=run,
    job=Job("gaius.flows", "ArticleCurationFlow"),
    inputs=[Dataset("gaius.source", "brave:ai-reasoning")],
    outputs=[Dataset("gaius.kb", "scratch/2026-03-14/paper.md")],
)
await emitter.emit(event)
```

## Cypher Queries

Lineage can be queried via the MCP `lineage_cypher` tool or the CLI:

```bash
# Trace upstream sources for a KB file
uv run gaius-cli --cmd "/lineage query scratch/paper.md"
```

### Example Queries

Find all KB files derived from arXiv sources:

```cypher
MATCH (s:Dataset)-[:INPUT_TO]->(:Run)-[:OUTPUTS]->(kb:Dataset)
WHERE s.namespace = 'gaius.source' AND s.name STARTS WITH 'arxiv:'
RETURN s.name as source, kb.name as kb_path
```

Trace full provenance chain (up to 5 hops):

```cypher
MATCH path = (src:Dataset)-[:INPUT_TO|OUTPUTS*1..5]->(target:Dataset)
WHERE target.namespace = 'gaius.kb'
  AND target.name CONTAINS 'attention_is_all_you_need'
RETURN src.namespace, src.name
```

Count vertices by label:

```cypher
MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt
```

## HX Package

The lineage subsystem lives in `gaius.hx.lineage`:

```
hx/lineage/
├── events.py    # Dataset, Job, Run, RunEvent (OpenLineage types)
├── emitter.py   # LineageEmitter (store + graph sync)
└── graph.py     # AGE Cypher helpers
```

The parent `gaius.hx` package is the raw content data lake (Apache Iceberg). Lineage events bridge HX raw storage to KB curated content, recording every transformation step.

## Integration Points

- **Metaflow flows** emit START/COMPLETE/FAIL events via the `GaiusFlow` base class
- **Fetch workers** emit events when acquiring external content
- **MCP tools** expose `query_lineage` and `lineage_cypher` for graph traversal
- The lineage graph is stored in the same PostgreSQL instance (`zndx_gaius:5444`) using the Apache AGE extension
