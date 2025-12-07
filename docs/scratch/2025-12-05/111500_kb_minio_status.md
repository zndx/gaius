# KB Configuration and Minio Status Investigation

**Date**: 2025-12-05
**Status**: Complete

## Summary

Investigated KB configuration and Minio storage status. Found that the `/reindex` issue was due to missing optional dependencies, not engine changes.

## Findings

### 1. KB Location Configuration

KB location is controlled by:
- `config/base.conf` → `gaius.kb.root = "build/dev"` with `${?GAIUS_KB_ROOT}` override
- Current KB root: `build/dev/`
- Allowed directories: `archive/`, `current/`, `scratch/`

No changes were made to KB configuration during the engine phases.

### 2. /reindex Issue

**Root Cause**: Missing `search` optional dependencies.

The `VectorSearch` class requires:
- `qdrant-client>=1.12.0`
- `sentence-transformers>=3.0.0`
- `bm25s>=0.2.0`

**Fix**: `uv sync --extra search`

**Result**: `/reindex` now works correctly:
- 1954 chunks indexed from 480 markdown files
- 13.5% grid coverage (49 unique positions)
- UMAP projection working

### 3. Minio Status

| Aspect | Status |
|--------|--------|
| Infrastructure (devenv.nix) | ✅ Configured - port 9010, bucket `zndx-gaius` |
| Documentation (kb.md) | ✅ Documents `GAIUS_KB_BACKEND=minio` env vars |
| Implementation | ❌ NOT IMPLEMENTED |

The documentation in `docs/src/guide/kb.md` is aspirational. The actual code (`src/gaius/inference/search/vector.py`) only supports local filesystem storage.

### 4. What Would Be Needed for Minio Support

1. Create storage abstraction layer (Protocol/Interface)
2. Implement Minio backend alongside filesystem backend
3. Update `VectorSearch._load_chunks()` to use abstraction
4. Add configuration to select backend via `GAIUS_KB_BACKEND`

## Files Reviewed

- `src/gaius/inference/search/vector.py` - VectorSearch implementation
- `src/gaius/core/config.py` - Configuration system
- `src/gaius/core/projection.py` - Grid projection
- `config/base.conf` - Base configuration
- `docs/src/guide/kb.md` - KB documentation
- `devenv.nix` - Development environment (Minio service)

## CLI Verification

```bash
# After installing dependencies
$ uv sync --extra search

$ uv run gaius-cli --cmd "/reindex" --format json
{
  "command": "reindex",
  "args": "",
  "success": true,
  "data": {
    "n_documents": 1954,
    "coverage": 0.13573407202216067,
    "method": "umap",
    "grid_mappings": 49,
    "has_embeddings": true,
    "embedding_count": 1954
  }
}
```
