# Qdrant WAL Health Check Enhancement

## Issue Discovered
During debugging session on 2025-12-21, discovered that Qdrant can have multiple "open" WAL segments which causes startup failures:

```
ERROR qdrant::startup: Panic occurred ... Failed to load local shard ... 
Wal error: Can't init WAL: Os { code: 11, kind: WouldBlock, message: "Resource temporarily unavailable" }
```

## Root Cause
WAL corruption: multiple `open-*` files in shard WAL directory when there should be at most one open segment.

Example of corrupted state:
```
/raid/qdrant/gaius/collections/gaius_kb_colnomic/0/wal/
├── closed-2053
├── first-index
├── open-22   # <-- should not exist
└── open-23   # <-- current open segment
```

## Fix Applied
Manually removed duplicate open segment: `rm -f open-22`

## Health Check Enhancement Needed

Add to `/health` command:

1. **Check**: Scan each Qdrant collection's WAL directories for multiple `open-*` files
2. **Warning**: Emit warning if more than one `open-*` file exists
3. **Fix Strategy**: 
   - Stop Qdrant
   - Remove older open segments (keep highest numbered)
   - Restart Qdrant

### Location
`src/gaius/health/checks/qdrant.py` - add `QdrantWalIntegrity` check

### Implementation
```python
def check_wal_integrity(collection_path: Path) -> list[str]:
    """Check for WAL corruption (multiple open segments)."""
    issues = []
    wal_path = collection_path / "0" / "wal"
    if wal_path.exists():
        open_files = list(wal_path.glob("open-*"))
        if len(open_files) > 1:
            issues.append(f"Multiple open WAL segments in {collection_path.name}: {[f.name for f in open_files]}")
    return issues
```

## Reference
- Qdrant data directory: `/raid/qdrant/gaius/collections/`
- Health check config: `config/base.conf` → `vector_store.host`, `vector_store.port`
