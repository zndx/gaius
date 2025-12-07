# Storage Abstraction Layer Implementation

**Date**: 2025-12-05
**Status**: Complete

## Summary

Implemented a pluggable storage abstraction layer for the Gaius KB that:
1. Extends [deepagents' BackendProtocol](https://github.com/langchain-ai/deepagents) for LangChain ecosystem compatibility
2. Supports local filesystem, Minio/S3, and future Cloudera Agent Studio backends
3. Integrates with VectorSearch for seamless indexing across storage backends

## Architecture

```
gaius.storage
├── __init__.py          # Public API
├── protocol.py          # StorageBackend protocol (extends deepagents)
├── filesystem.py        # FilesystemStorage (default)
├── minio.py             # MinioStorage (S3-compatible)
├── agent_studio.py      # AgentStudioStorage (stub for future)
└── factory.py           # Backend factory + registry
```

### Protocol Hierarchy

```
deepagents.backends.BackendProtocol
    ├── ls_info, read, write, edit
    ├── glob_info, grep_raw
    └── upload_files, download_files

gaius.storage.StorageBackend (extends BackendProtocol)
    ├── iter_documents()    # KB-specific iteration
    ├── get_document()      # Single doc retrieval
    ├── document_exists()   # Existence check
    └── get_stats()         # Storage statistics
```

## Configuration

### Environment Variables

```bash
# Backend selection
GAIUS_KB_BACKEND=filesystem|minio|agent_studio

# Filesystem backend (default)
GAIUS_KB_ROOT=build/dev

# Minio/S3 backend
GAIUS_KB_BACKEND=minio
GAIUS_KB_ENDPOINT=localhost:9010
GAIUS_KB_ACCESS_KEY=minioadmin
GAIUS_KB_SECRET_KEY=minioadmin
GAIUS_KB_ROOT=zndx-gaius        # bucket name
GAIUS_KB_SECURE=false           # http vs https

# Agent Studio (future)
GAIUS_KB_BACKEND=agent_studio
GAIUS_AGENT_STUDIO_URL=https://agent-studio.cloudera.local
GAIUS_AGENT_STUDIO_API_KEY=...
```

## Usage

### Basic Usage

```python
from gaius.storage import get_storage_backend

# Automatically selects backend from GAIUS_KB_BACKEND env var
backend = get_storage_backend()

# List documents
for doc in backend.iter_documents():
    print(doc.path, doc.title)

# Read file (deepagents-compatible)
content = backend.read("/current/topics/kudu.md")

# Write file
result = backend.write("/scratch/2025-12-05/notes.md", "# Notes\n...")

# Get stats
stats = backend.get_stats()
print(f"Total documents: {stats['total_documents']}")
```

### With VectorSearch

```python
from gaius.storage import get_storage_backend
from gaius.inference.search.vector import VectorSearch

# Storage backend is automatically used by get_vector_search()
# Or explicitly:
backend = get_storage_backend()
vs = VectorSearch(storage_backend=backend)
vs.index_kb()
```

### Custom Backend Registration

```python
from gaius.storage import register_backend

# Register custom backend (e.g., from external package)
register_backend("my_storage", lambda config: MyStorageBackend(config))

# Now can use: GAIUS_KB_BACKEND=my_storage
```

## Migration Path

### Phase 1: Development (Current)
- `GAIUS_KB_BACKEND=filesystem` (default)
- KB stored in `build/dev/`
- No additional configuration needed

### Phase 2: Production Object Storage
- `GAIUS_KB_BACKEND=minio`
- Migrate data: `mc cp --recursive build/dev/* minio/zndx-gaius/`
- Update env vars in deployment

### Phase 3: Cloudera Agent Studio
- `GAIUS_KB_BACKEND=agent_studio`
- Implement actual Agent Studio SDK integration
- Data migrated via Agent Studio APIs

## deepagents Compatibility

The storage abstraction is designed for full compatibility with deepagents' ecosystem:

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from gaius.storage import get_storage_backend

# Use Gaius storage as part of composite backend
gaius_backend = get_storage_backend()

agent = create_deep_agent(
    backend=CompositeBackend(
        default=StateBackend(),
        routes={"/kb/": gaius_backend},
    ),
)
```

## Files Created

- `src/gaius/storage/__init__.py` - Package exports
- `src/gaius/storage/protocol.py` - StorageBackend protocol
- `src/gaius/storage/filesystem.py` - FilesystemStorage
- `src/gaius/storage/minio.py` - MinioStorage
- `src/gaius/storage/agent_studio.py` - AgentStudioStorage (stub)
- `src/gaius/storage/factory.py` - Backend factory

## Files Modified

- `src/gaius/inference/search/vector.py`
  - Added `storage_backend` parameter to VectorSearch
  - Updated `_load_chunks()` to use storage abstraction
  - Updated `get_vector_search()` factory to use storage backend

## Verification

```bash
# Test storage abstraction
uv run python -c "
from gaius.storage import get_storage_backend
backend = get_storage_backend()
print('Documents:', backend.get_stats()['total_documents'])
"

# Test reindex with storage backend
uv run gaius-cli --cmd "/reindex" --format json
```

## References

- [deepagents BackendProtocol](https://docs.langchain.com/oss/python/deepagents/backends)
- [Cloudera Agent Studio](https://github.com/cloudera/CAI_STUDIO_AGENT)
- [LangChain DeepAgents v0.2](https://blog.langchain.com/doubling-down-on-deepagents/)
