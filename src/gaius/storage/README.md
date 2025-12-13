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
    """Abstract storage backend."""

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

All KB operations are restricted to:
- `archive/` - Quarterly archives
- `current/` - Active content
- `scratch/` - Daily zettelkasten

## KB Operations

High-level operations used by MCP, CLI, and TUI:

### Search

```python
from gaius.storage.kb_ops import search_kb, SearchResult

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
await update_kb(
    "current/topics/tda.md",
    updated_content,
)
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

# Recent evolution cycles
cycles = await get_recent_cycles(limit=10)
for cycle in cycles:
    print(f"{cycle.agent_id}: {cycle.improvement_percent:.1f}%")

# Agent scores
scores = await get_agent_scores()
for score in scores:
    print(f"{score.agent_id}: {score.avg_score:.3f}")

# Trend over days
trend = await get_evolution_trend(days=7)
```

### Daily Summaries

```python
from gaius.storage.database import get_daily_summary

summary = await get_daily_summary("2025-12-13")
print(f"Total evals: {summary.total_evals}")
print(f"Average score: {summary.avg_score:.3f}")
```

### XAI Budget

```python
from gaius.storage.database import get_xai_budget_status

status = await get_xai_budget_status()
print(f"Daily used: {status.daily_used}/{status.daily_limit}")
print(f"Weekly used: {status.weekly_used}/{status.weekly_limit}")
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
for snap in snapshots:
    print(f"{snap.created_at}: {snap.n_documents} docs")
```

### Snapshot Structure

```sql
CREATE TABLE grid_snapshots (
    id SERIAL PRIMARY KEY,
    kb_root VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    n_documents INT,
    coverage FLOAT,
    method VARCHAR(32),  -- umap, pca
    allocations JSONB,   -- 19x19 density matrix
    tda_features JSONB   -- Betti numbers, entropy
);
```

## MinIO Integration

MinIO is the primary object storage backend for Gaius, providing S3-compatible storage for KB documents, HX data lake, and content sync:

```python
from gaius.storage.minio import MinioStorage

storage = MinioStorage(
    endpoint="minio:9000",
    access_key="gaius",
    secret_key="secret",
    bucket="gaius-kb",
)

# Upload
await storage.write("current/topics/tda.md", content)

# Download
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

Provides:
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

# Status
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

## See Also

- [Parent README](../README.md) - Module overview
- [Database README](../../db/README.md) - Schema documentation
- [Core README](../core/README.md) - Grid projection
