# Metaflow Integration

Gaius uses Metaflow for production data pipelines that run on Kubernetes. Flows handle article curation, content evaluation, rendering, and document processing.

## Infrastructure

The Metaflow service is deployed via Tilt in `infra/tilt/` and runs on the local RKE2 Kubernetes cluster. The service is exposed via K8s NodePort on port 30180 (patched automatically by `metaflow-port-forwards.sh` on startup).

The environment variable `METAFLOW_SERVICE_URL=http://localhost:30180` must be set for flow execution. This is configured automatically in `devenv.nix` `enterShell` for interactive shells and explicitly in process scripts.

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
