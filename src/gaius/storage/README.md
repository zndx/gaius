# Gaius Storage

Unified storage abstraction for knowledge base, embeddings, and persistent state. Supports multiple backends: filesystem, MinIO/S3, and Cloudera Agent Studio.

## Architecture

```mermaid
graph TB
    subgraph "Interfaces"
        CLI[CLI/TUI]
        MCP[MCP Server]
        AGENTS[Agents]
    end

    subgraph "Operations Layer"
        KBOPS[kb_ops.py<br/>High-level KB API]
        DB[database.py<br/>PostgreSQL Queries]
        GRID[grid_state.py<br/>Grid Snapshots]
    end

    subgraph "Storage Backends"
        FS[FilesystemStorage<br/>Development]
        MINIO[MinioStorage<br/>Primary Storage]
        STUDIO[AgentStudioStorage<br/>Cloudera Enterprise]
    end

    subgraph "Data Stores"
        PG[(PostgreSQL<br/>State, Metrics)]
        QD[(Qdrant<br/>Embeddings)]
        S3[(MinIO/S3<br/>KB Files)]
    end

    CLI --> KBOPS
    MCP --> KBOPS
    AGENTS --> KBOPS

    CLI --> DB
    MCP --> DB

    KBOPS --> FS
    KBOPS --> MINIO
    KBOPS --> STUDIO

    FS --> S3
    MINIO --> S3
    DB --> PG
    GRID --> PG
    GRID --> QD
```

## Module Structure

```
storage/
├── __init__.py        # Module exports
├── protocol.py        # StorageBackend protocol, KBDocument
├── factory.py         # get_storage_backend(), register_backend()
├── filesystem.py      # FilesystemStorage (local files)
├── minio.py           # MinioStorage (S3-compatible)
├── agent_studio.py    # AgentStudioStorage (Cloudera)
├── kb_ops.py          # High-level KB operations
├── database.py        # PostgreSQL queries
├── grid_state.py      # Grid projection snapshots
└── sync_engine.py     # KB synchronization
```

## Storage Protocol

All backends implement the `StorageBackend` protocol:

```python
class StorageBackend(Protocol):
    """Abstract storage backend interface."""

    config: StorageConfig

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files with metadata."""

    def read(self, path: str) -> str:
        """Read file content."""

    def write(self, path: str, content: str) -> WriteResult:
        """Write file content."""

    def delete(self, path: str) -> bool:
        """Delete file."""

    def iter_documents(
        self,
        extensions: tuple[str, ...] = (".md",),
    ) -> Iterator[KBDocument]:
        """Iterate all documents with content."""
```

### Configuration

```python
@dataclass
class StorageConfig:
    root: str = "build/dev"
    backend: str = "filesystem"  # filesystem, minio, agent_studio
    allowed_dirs: tuple[str, ...] = ("archive", "current", "scratch")
```

## KB Structure

```
build/dev/                 # KB root (gitignored)
├── current/               # Active work (manual organization)
│   ├── projects/
│   ├── topics/
│   └── heuristics/gaius/  # System heuristics
├── scratch/               # Zettelkasten (date-based)
│   └── 2025-12-13/
│       ├── 143000_notes.md
│       └── 210000_fmea.md
└── archive/               # Quarterly archives
    └── 2025Q4/
        └── attachments/
```

### Allowed Directories

All KB operations are restricted to designated directories for security:
- `archive/` — Quarterly archives
- `current/` — Active content
- `scratch/` — Daily zettelkasten notes

## KB Operations

High-level operations used by MCP, CLI, and TUI:

### Search

```python
from gaius.storage.kb_ops import search_kb

results = await search_kb("persistent homology", max_results=10)
for result in results:
    print(f"{result.path} ({result.match_type})")
    print(f"  {result.preview}")
```

### Read/Write

```python
from gaius.storage.kb_ops import read_kb, create_kb, update_kb

# Read
content = await read_kb("current/topics/tda.md")

# Create
path = await create_kb(
    "scratch/2025-12-13/notes.md",
    "# Notes\n\nContent here...",
)

# Update
await update_kb("current/topics/tda.md", updated_content)
```

### List

```python
from gaius.storage.kb_ops import list_kb

entries = await list_kb("current/topics/")
for entry in entries:
    print(f"{entry.path} ({entry.size} bytes)")
```

## Database Access

Centralized PostgreSQL queries:

### Evolution Data

```python
from gaius.storage.database import (
    get_recent_cycles,
    get_agent_scores,
    get_evolution_trend,
)

cycles = await get_recent_cycles(limit=10)
scores = await get_agent_scores()
trend = await get_evolution_trend(days=7)
```

### Daily Summaries

```python
from gaius.storage.database import get_daily_summary

summary = await get_daily_summary("2025-12-13")
print(f"Total evals: {summary.total_evals}")
print(f"Average score: {summary.avg_score:.3f}")
```

## Grid State Persistence

Grid projections are snapshotted for history tracking:

```python
from gaius.storage.grid_state import (
    save_grid_state,
    load_current_state,
    list_grid_snapshots,
)

# Save current state
await save_grid_state(grid_data, tda_features)

# Load latest
state = await load_current_state()
print(f"Documents: {state.n_documents}")
print(f"Coverage: {state.coverage:.1%}")

# List history
snapshots = await list_grid_snapshots(limit=10)
```

### Snapshot Schema

```sql
CREATE TABLE grid_snapshots (
    id SERIAL PRIMARY KEY,
    kb_root VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    n_documents INT,
    coverage FLOAT,
    method VARCHAR(32),  -- umap, pca
    allocations JSONB,   -- 19×19 density matrix
    tda_features JSONB   -- Betti numbers, entropy
);
```

## MinIO Integration

MinIO provides S3-compatible storage for KB documents:

```python
from gaius.storage.minio import MinioStorage

storage = MinioStorage(
    endpoint="minio:9000",
    access_key="gaius",
    secret_key="secret",
    bucket="gaius-kb",
)

await storage.write("current/topics/tda.md", content)
content = await storage.read("current/topics/tda.md")
```

### Configuration

```bash
export GAIUS_KB_BACKEND=minio
export MINIO_ENDPOINT=minio:9000
export MINIO_ACCESS_KEY=gaius
export MINIO_SECRET_KEY=secret
export MINIO_BUCKET=gaius-kb
```

## Agent Studio Integration

Cloudera Agent Studio for enterprise deployment:

```python
from gaius.storage.agent_studio import AgentStudioStorage

storage = AgentStudioStorage(
    workspace_id="gaius-prod",
    api_key=os.environ["AGENT_STUDIO_API_KEY"],
)
```

Features:
- Enterprise authentication
- Audit logging
- Version control integration
- Team collaboration

## Sync Engine

Synchronizes KB content with embeddings:

```python
from gaius.storage.sync_engine import SyncEngine

engine = SyncEngine()

# Full sync
await engine.sync_all()

# Incremental (changed files only)
await engine.sync_incremental()

status = engine.get_status()
print(f"Synced: {status.synced_count}")
print(f"Pending: {status.pending_count}")
```

### Sync Pipeline

```mermaid
graph LR
    A[KB Files] --> B[Content Hash]
    B --> C{Changed?}
    C -->|Yes| D[Generate Embedding]
    C -->|No| E[Skip]
    D --> F[Store in Qdrant]
    F --> G[Update Grid Projection]
```

## Configuration

```hocon
storage {
    backend = "filesystem"  # filesystem, minio, agent_studio
    root = "build/dev"

    filesystem {
        create_dirs = true
    }

    minio {
        endpoint = "minio:9000"
        bucket = "gaius-kb"
        secure = false
    }

    database {
        url = "postgresql://gaius:gaius@localhost:5432/gaius"
        pool_size = 10
    }
}
```

## Call Graph

```
# KB Read Path
mcp_server.py:read_kb(path)
  └─→ storage.kb_ops.read_kb(path)
      └─→ get_storage_backend()                # singleton factory
          └─→ StorageBackend.read(path)
              ├─→ FilesystemStorage.read()     # local dev
              ├─→ MinioStorage.read()          # S3-compatible
              └─→ AgentStudioStorage.read()    # Cloudera

# KB Write Path
mcp_server.py:create_kb(path, content)
  └─→ storage.kb_ops.create_kb(path, content)
      └─→ get_storage_backend().write(path, content)
          └─→ sync_engine.queue_embedding(path)
              └─→ qdrant_client.upsert(embedding)

# Search Path
mcp_server.py:search_kb(query)
  └─→ storage.kb_ops.search_kb(query)
      ├─→ qdrant_client.search(query_embedding)  # vector search
      └─→ storage.filesystem.glob(pattern)       # filename match

# Grid State Persistence
widgets.grid.MainGrid.snapshot()
  └─→ storage.grid_state.save_grid_state(data, tda)
      └─→ database.execute_insert(grid_snapshots)
```

## Data Flow

```mermaid
graph TB
    INPUT["User Input<br/>(MCP tool, CLI command, TUI action)"]
    KBOPS["kb_ops.py<br/>(search_kb, read_kb, create_kb, ...)"]
    FS["Filesystem<br/>Storage"]
    MINIO["MinIO<br/>Storage"]
    STUDIO["Agent Studio<br/>Storage"]
    SYNC["sync_engine.py<br/>(embedding generation, upsert)"]
    QD["Qdrant<br/>Embeddings"]
    PG["PostgreSQL<br/>State"]
    S3["MinIO/S3<br/>KB Files"]

    INPUT --> KBOPS
    KBOPS --> FS
    KBOPS --> MINIO
    KBOPS --> STUDIO
    FS --> SYNC
    MINIO --> SYNC
    STUDIO --> SYNC
    SYNC --> QD
    SYNC --> PG
    SYNC --> S3
```

## Integration Points

| Component | Uses | Used By | Integration |
|-----------|------|---------|-------------|
| `get_storage_backend()` | factory.py | kb_ops, mcp_server, agents | Singleton factory |
| `kb_ops` | StorageBackend, qdrant | mcp_server, agents, theta | `search_kb()`, `read_kb()`, `create_kb()` |
| `database.py` | asyncpg | grid_state, evolution, health | Connection pool |
| `grid_state.py` | database, qdrant | core.projection, widgets | `save_grid_state()`, `load_current_state()` |
| `sync_engine.py` | StorageBackend, qdrant | workers, flows | `sync_all()`, `sync_incremental()` |

## See Also

- [Parent README](../README.md) — Module overview
- [Database README](../../db/README.md) — Schema documentation
- [Core README](../core/README.md) — Grid projection
- [HX README](../hx/README.md) — Raw content data lake
- [Agents README](../agents/README.md) — KB access for theta consolidation

---

<!-- GAI:META
module: gaius.storage
layer: L2-transport
singleton: get_storage_backend
key_types: [StorageBackend, FilesystemStorage, MinioStorage, AgentStudioStorage, KBDocument, WriteResult]
key_funcs: [search_kb, read_kb, create_kb, update_kb, list_kb, save_grid_state, load_current_state]
submodules: []
depends: [core.config, qdrant_client, asyncpg, minio]
dependents: [mcp_server, agents, flows, workers, widgets.grid]
config_keys: [storage.backend, storage.root, storage.minio.endpoint, storage.database.url]
env_vars: [GAIUS_KB_BACKEND, MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET]
grpc_services: []
qdrant_collections: [gaius_embeddings]
postgres_tables: [grid_snapshots]
external_deps: [asyncpg, qdrant_client, minio]
call_paths:
  read: mcp.read_kb→kb_ops.read_kb→get_storage_backend→StorageBackend.read
  write: mcp.create_kb→kb_ops.create_kb→StorageBackend.write→sync_engine.queue_embedding
  search: mcp.search_kb→kb_ops.search_kb→qdrant.search+filesystem.glob
  grid_snapshot: widgets.grid.snapshot→grid_state.save_grid_state→database.insert
test_cmds:
  read: 'uv run gaius-cli --cmd "/kb read current/topics/test.md"'
  search: 'uv run gaius-cli --cmd "/kb search persistent homology"'
guru_codes: [ST.00001.QDRANT_DOWN, ST.00002.MINIO_UNREACHABLE, ST.00003.PG_CONN_FAIL]
fail_fast: true
-->
