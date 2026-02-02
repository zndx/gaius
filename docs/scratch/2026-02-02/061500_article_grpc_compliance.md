# Article Command gRPC Compliance + Situational Awareness

## Summary

Completed the migration of `/article` commands from direct filesystem access and subprocess calls to the gRPC-first architecture.

## Changes Made

### 1. CollectionService Methods
- Added `get_article_status()` - Returns situational awareness data
- Added `create_article()` - Creates article directory structure via engine

### 2. Proto Definitions
Added to `gaius_service.proto`:
- `ArticleInfo` message
- `CurationRunInfo` message
- `ArticleStatusRequest/Response`
- `ArticleNewRequest/Response`
- `ArticleCurateRequest`
- `ArticleCurationEvent` (for streaming)
- RPCs: `ArticleStatus`, `ArticleNew`, `ArticleCurate`

### 3. gRPC Servicer
Added three RPC implementations in `gaius_servicer.py`:
- `ArticleStatus` - Point-in-time query
- `ArticleNew` - Creates article via engine
- `ArticleCurate` - Streaming progress events

### 4. gRPC Client
Updated `grpc_client.py`:
- Added Article proto imports
- Added `_call_article()` dispatch method
- Added direct methods: `ArticleStatus()`, `ArticleNew()`, `ArticleCurate()`

### 5. TUI (`app.py`)
- Changed `/article` default handler from help to `_article_sitrep()`
- Added `_article_sitrep()` - Bloomberg Terminal style status display
- Fixed `_article_new()` to use gRPC instead of direct filesystem

### 6. CLI (`cli.py`)
- Fixed `_article_curate()` - Uses gRPC streaming instead of `subprocess.run()`
- Fixed `_article_new()` - Uses gRPC instead of direct filesystem

### 7. MCP (`mcp_server.py`)
- Fixed `article_new` tool - Uses gRPC instead of direct filesystem

## Architecture Compliance

Before:
- CLI: `subprocess.run()` for curate, `Path.mkdir()` for new
- TUI: `Path.mkdir()` for new
- MCP: `Path.mkdir()` for new

After:
- All surfaces: Client -> gRPC -> Engine -> KB filesystem

## Testing Verified

1. `/article` in TUI shows sitrep with:
   - Running state (IDLE/RUNNING)
   - Pending article count
   - Card counts (pending/published)
   - Article list with status icons
   - Available commands

2. `/publish cards` regression test passed:
   - 3 cards published successfully
   - Cards have proper source URLs and summaries

3. `/article new test-slug` creates article via gRPC:
   - Returns `article_id` and `collection_id`
   - KB directory created on engine side

## Files Modified

| File | Change |
|------|--------|
| `collection_service.py` | Added `get_article_status()`, `create_article()` |
| `gaius_service.proto` | Added Article proto messages and RPCs |
| `gaius_service_pb2.py` | Regenerated |
| `gaius_service_pb2_grpc.py` | Regenerated |
| `generated/__init__.py` | Added Article exports |
| `gaius_servicer.py` | Added Article RPC implementations |
| `grpc_client.py` | Added Article imports and methods |
| `app.py` | Added `_article_sitrep()`, fixed `_article_new()` |
| `cli.py` | Fixed `_article_curate()`, `_article_new()` |
| `mcp_server.py` | Fixed `article_new` |
