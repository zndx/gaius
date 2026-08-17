# Metaflow Integration

Gaius uses Metaflow for production data pipelines that run on Kubernetes. Flows handle article curation, content evaluation, rendering, and document processing.

## Infrastructure

Two profiles exist. **When Signals is on the lattice, platform Metaflow is SoR.**

| Mode | When | Metadata | Artifacts | Compute |
|------|------|----------|-----------|---------|
| `platform` | Signals `Engine/Status` (`:50551`) has healthy `metaflow` or `scheduler`, and `:30180/ping` succeeds | Signals metadata service | RustFS `s3://metaflow/metaflow` | Host Metaflow + YK Application on `root.internal.inference.extract` (no `root.gaius`) |
| `local` | Signals Status unreachable (standalone devenv) | Gaius Tilt / `infra/tilt` | Gaius MinIO / `/raid/metaflow` | host subprocess |

`apply_metaflow_config()` (and every flow spawn env) resolves this via
`gaius.flows.platform_metaflow.resolve_metaflow_mode`. Federated + Metaflow
down is `#MF.00000006.NOPLATFORM` — do not tilt-deploy a competing service.

Force for tests: `GAIUS_METAFLOW_MODE=local` or `platform`.

## GaiusFlow Base Class

All Gaius flows inherit from `GaiusFlow`, which provides OpenLineage integration and KB path helpers:

```python
from gaius.flows import GaiusFlow
from metaflow import step

class MyFlow(GaiusFlow):
    @step
    def start(self):
        self.emit_lineage_start("my_flow", inputs=[...])
        self.next(self.process)

    @step
    def end(self):
        self.emit_lineage_complete(outputs=[...])
```

KB path helpers generate paths following the zettelkasten convention:

```python
# scratch/{date}/{HHMMSS}_{title}.md
path = self.zettelkasten_path("My Analysis")

# current/archive/{quarter}/attachments/{filename}
path = self.archive_path("paper.pdf")
```

## Flow Registry

Flows are registered for CLI discovery using the `@register_flow` decorator:

```python
from gaius.flows import register_flow

@register_flow("article-curation")
class ArticleCurationFlow(GaiusFlow):
    ...
```

Registered flows can be listed and invoked from the CLI or MCP tools.

## Available Flows

| Flow | Purpose | Typical Duration |
|------|---------|-----------------|
| ArticleCurationFlow | End-to-end article research and card publication | ~2 min |
| ArxivDoclingFlow | Fetch and convert arXiv papers to markdown | ~30s |
| ClouderaDocsFlow | Sync Cloudera documentation archives | varies |
| KnowledgeSummaryFlow | Parallel collection `summary.md` (ontology, heuristics, articles, projects, thoughts) | seconds |

See [Article Curation](./article-curation.md) for the full 11-step pipeline.

## Configuration

Key environment variables:

| Variable | Purpose |
|----------|---------|
| `METAFLOW_SERVICE_URL` | Metaflow service endpoint (http://localhost:30180) |
| `METAFLOW_DATASTORE_SYSROOT_S3` | MinIO path for flow artifacts |
| `METAFLOW_DEFAULT_METADATA` | Metadata backend (postgresql) |
| `GAIUS_KB_ROOT` | Knowledge base root directory |

## Running Flows

```bash
# Via Metaflow CLI
python -m metaflow.cli run ArticleCurationFlow --article ai-reasoning-weekly

# Via Gaius CLI
uv run gaius-cli --cmd "/article curate ai-reasoning-weekly"

# Via MCP tool
uv run gaius-cli --cmd "/fetch_paper 2312.12345"
```

## K8s Prerequisites

- `kubectl` and `k9s` are Nix-managed via `devenv.nix` (not the system RKE2 binary)
- KUBECONFIG must be set to `~/.config/kube/rke2.yaml` (never use fallback syntax)
- K8s pods need `pg_hba.conf` entries for `10.42.0.0/16` and `10.43.0.0/16` subnets
