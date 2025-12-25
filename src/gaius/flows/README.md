# Gaius Flows

Metaflow-based data pipelines with OpenLineage tracking (OpenLineage, 2024). Integrates with devenv PostgreSQL, MinIO for storage, and Apache AGE graph for lineage.

## Architecture

```mermaid
graph TB
    subgraph "Flow Execution"
        MF[Metaflow Runtime]
        FLOW[GaiusFlow]
        STEP[Flow Steps]
    end

    subgraph "Lineage"
        OL[OpenLineage Events]
        AGE[Apache AGE Graph]
    end

    subgraph "Storage"
        MINIO[MinIO/S3]
        KB[Knowledge Base]
        PG[PostgreSQL]
    end

    MF --> FLOW
    FLOW --> STEP
    STEP --> OL
    OL --> AGE
    STEP --> MINIO
    STEP --> KB
    MF --> PG
```

## Module Structure

```
flows/
├── __init__.py          # Flow registry, register_flow decorator
├── base.py              # GaiusFlow base class
├── config.py            # Flow configuration
├── runner.py            # Flow execution utilities
├── docling/             # arXiv paper processing
│   └── arxiv_flow.py    # ArxivDoclingFlow
├── cloudera_docs/       # Cloudera documentation sync
└── topics/              # Topic extraction flows
```

## GaiusFlow Base Class

All Gaius flows inherit from `GaiusFlow` for lineage integration:

```python
from gaius.flows import GaiusFlow
from metaflow import step

class MyFlow(GaiusFlow):
    @step
    def start(self):
        self.emit_lineage_start(
            "my_flow",
            inputs=[Dataset("source", "input.pdf")],
        )
        self.next(self.process)

    @step
    def process(self):
        # Process data...
        self.next(self.end)

    @step
    def end(self):
        self.emit_lineage_complete(
            outputs=[Dataset("gaius.kb", "scratch/output.md")],
        )
```

### KB Path Helpers

```python
# Zettelkasten path: scratch/{date}/{HHMMSS}_{title}.md
path = self.zettelkasten_path("My Analysis")
# → "scratch/2024-12-25/103045_my_analysis.md"

# Archive path: current/archive/{quarter}/attachments/{filename}
path = self.archive_path("paper.pdf")
# → "current/archive/2024Q4/attachments/paper.pdf"
```

## Flow Registry

Flows are registered for CLI discovery:

```python
from gaius.flows import register_flow

@register_flow("my-flow")
class MyFlow(GaiusFlow):
    ...
```

List registered flows:

```python
from gaius.flows import FLOW_REGISTRY

for name, flow_class in FLOW_REGISTRY.items():
    print(f"{name}: {flow_class.__doc__}")
```

## Available Flows

### ArxivDoclingFlow

Fetches arXiv papers, converts PDF to markdown using docling (DS4SD, 2024), and stores in KB:

```bash
uv run python -m metaflow.run gaius.flows.docling:ArxivDoclingFlow \
    --arxiv_id 2312.12345
```

Pipeline:
1. Download PDF from arXiv
2. Convert to markdown via docling (GPU-accelerated)
3. Extract topics using BERTopic
4. Score relevance with local LLM
5. Save to KB zettelkasten

### ClouderaDocsFlow

Syncs Cloudera documentation archives:

```bash
uv run python -m gaius.flows.cloudera_docs --product csa
```

## OpenLineage Integration

Flows emit OpenLineage events for provenance tracking:

### Event Types

| Event | Timing | Purpose |
|-------|--------|---------|
| `START` | Flow begin | Record inputs |
| `COMPLETE` | Flow end | Record outputs |
| `FAIL` | On error | Record failure |

### Dataset Schema

```python
from gaius.hx.lineage.events import Dataset

# Source dataset
input_ds = Dataset(
    namespace="gaius.source",
    name="arxiv:2312.12345",
)

# Output dataset
output_ds = Dataset(
    namespace="gaius.kb",
    name="scratch/2024-12-25/paper.md",
)
```

### Lineage Graph

Events are stored in Apache AGE graph:

```sql
-- Query lineage for a KB file
SELECT * FROM ag_catalog.cypher('openlineage', $$
    MATCH path = (src:Dataset)-[:INPUT_TO|OUTPUTS*]->(kb:Dataset)
    WHERE kb.name = 'scratch/2024-12-25/paper.md'
    RETURN path
$$) as (path agtype);
```

## Configuration

```python
@dataclass
class FlowConfig:
    metaflow_datastore: str = "postgresql"
    metaflow_metadata: str = "postgresql"
    kb_root: Path = Path("build/dev")
    archive_pdfs: bool = True
```

Environment variables:
- `GAIUS_KB_ROOT`: KB root directory
- `METAFLOW_DATASTORE_SYSROOT_S3`: MinIO path for artifacts
- `METAFLOW_DEFAULT_METADATA`: Metadata backend

## Running Flows

### Via Metaflow CLI

```bash
python -m metaflow.run gaius.flows.docling:ArxivDoclingFlow \
    --arxiv_id 2312.12345 \
    --enable_topics \
    --enable_scoring
```

### Via MCP

```bash
uv run gaius-cli --cmd "/fetch_paper 2312.12345"
```

### Programmatically

```python
from gaius.flows.runner import run_flow

result = await run_flow(
    "arxiv-docling",
    arxiv_id="2312.12345",
    enable_topics=True,
)
```

## References

- DS4SD. (2024). *docling: Document Understanding*. https://github.com/DS4SD/docling
- OpenLineage. (2024). *OpenLineage Specification*. https://openlineage.io/

## See Also

- [Parent README](../README.md) — Module overview
- [HX README](../hx/README.md) — Lineage storage
- [Storage README](../storage/README.md) — KB integration
