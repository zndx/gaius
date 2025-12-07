# Phase 6: Clean Architecture Around Aeron IPC

**Date**: 2025-12-05
**Status**: Complete

## Summary

Completed Phase 6 of the gaius-engine refactoring: dead code elimination and clean integration architecture around Aeron IPC. The system now has:

1. **Centralized engine daemon** - Long-running service handling all inference, evolution, and compute
2. **Storage abstraction** - Pluggable backends (filesystem, Minio, Agent Studio)
3. **Unified client proxies** - TUI/CLI/MCP access services via IPC
4. **Consolidated data access** - Single source of truth for database queries

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                 │
├─────────────┬─────────────┬─────────────────────────────────────────┤
│    TUI      │    CLI      │           MCP Server                    │
│  (app.py)   │  (cli.py)   │       (mcp_server.py)                   │
└──────┬──────┴──────┬──────┴──────────────┬──────────────────────────┘
       │             │                      │
       └─────────────┴──────────────────────┘
                     │
           ┌─────────▼─────────┐
           │  gaius.client     │
           │  (engine_proxy.py)│
           │                   │
           │  OrchestratorProxy│
           │  SchedulerProxy   │
           │  EvolutionProxy   │
           │  HealthProxy      │
           │  TDAProxy         │
           │  GridProxy        │
           └─────────┬─────────┘
                     │ Aeron IPC
           ┌─────────▼─────────┐
           │  gaius-engine     │
           │  (server.py)      │
           │                   │
           │  ┌─────────────┐  │
           │  │ Services    │  │
           │  │ Orchestrator│  │
           │  │ Scheduler   │  │
           │  │ Evolution   │  │
           │  │ Health      │  │
           │  └─────────────┘  │
           │                   │
           │  ┌─────────────┐  │
           │  │ Compute     │  │
           │  │ TDA         │  │
           │  │ Grid        │  │
           │  └─────────────┘  │
           │                   │
           │  ┌─────────────┐  │
           │  │ Backends    │  │
           │  │ vLLM        │  │
           │  │ optillm     │  │
           │  └─────────────┘  │
           └───────────────────┘
```

## Dead Code Removed

| File | Lines | Reason |
|------|-------|--------|
| `src/gaius/app2.py` | 293 | Obsolete UI experiment |
| `src/gaius/app3.py` | 192 | Obsolete UI experiment |
| `src/gaius/app4.py` | 187 | Obsolete UI experiment |
| **Total** | **672** | |

## Storage Abstraction

New module `gaius.storage` provides:

```
gaius.storage/
├── __init__.py          # Public API
├── protocol.py          # StorageBackend protocol (extends deepagents)
├── filesystem.py        # FilesystemStorage (default)
├── minio.py             # MinioStorage (S3-compatible)
├── agent_studio.py      # AgentStudioStorage (stub for Cloudera)
├── factory.py           # Backend factory + registry
├── database.py          # Centralized database queries
└── kb_ops.py            # High-level KB operations
```

### Configuration

```bash
# Filesystem (default)
GAIUS_KB_BACKEND=filesystem
GAIUS_KB_ROOT=build/dev

# Minio/S3
GAIUS_KB_BACKEND=minio
GAIUS_KB_ENDPOINT=localhost:9010
GAIUS_KB_ACCESS_KEY=minioadmin
GAIUS_KB_SECRET_KEY=minioadmin
```

## Consolidated Data Access

All database queries now go through `gaius.storage.database`:

| Function | Description |
|----------|-------------|
| `get_recent_cycles()` | Evolution cycle history |
| `get_agent_scores()` | Agent evaluation scores |
| `get_evolution_trend()` | Performance trends |
| `get_eval_comparison()` | Local vs XAI comparison |
| `get_xai_budget()` | XAI budget status |
| `get_held_out_stats()` | Held-out query pool |

### Before (duplicated in MCP + widgets)
```python
# In mcp_server.py AND evolution_panel.py
import asyncpg
conn = await asyncpg.connect(url)
rows = await conn.fetch("SELECT ...")
```

### After (single source of truth)
```python
from gaius.storage.database import get_recent_cycles
cycles = await get_recent_cycles(limit=10)
```

## MCP Server Refactoring

KB operations now use storage abstraction:

| Tool | Before | After |
|------|--------|-------|
| `search_kb` | Direct `Path.rglob()` | `storage.kb_ops.search_kb()` |
| `read_kb` | `path.read_text()` | `storage.kb_ops.read_kb()` |
| `create_kb` | `path.write_text()` | `storage.kb_ops.create_kb()` |
| `update_kb` | `path.write_text()` | `storage.kb_ops.update_kb()` |
| `delete_kb` | `path.unlink()` | `storage.kb_ops.delete_kb()` |
| `list_kb` | Direct `Path.rglob()` | `storage.kb_ops.list_kb()` |

Database queries now use centralized module:

| Tool | Before | After |
|------|--------|-------|
| `get_evolution_trend` | Direct asyncpg | `storage.database.get_evolution_trend()` |
| `get_eval_comparison` | Direct asyncpg | `storage.database.get_eval_comparison()` |

## Engine Service Handlers

All handlers now respond to complete action sets:

### Orchestrator
- `status` - GPU allocation, evolution status
- `list_agents` - Configured agents
- `start` / `stop` - Endpoint management

### Scheduler
- `status` - Queue depth, backends
- `submit` - Queue inference job
- `get_result` - Retrieve job result

### Evolution
- `status` - Running state, cycles, next agent
- `trigger` - Manual evolution trigger
- `start` / `stop` - Daemon control

### Grid
- `status` - Cache info, method
- `project` - Project embeddings to grid

### TDA
- `status` - Cache info, dimensions
- `compute` - Compute persistent homology

### Health
- `status` - Uptime, version, service states
- `metrics` - GPU/endpoint health

## Client Proxy Usage

```python
# Preferred: Use proxies for IPC communication
from gaius.client import get_orchestrator_proxy, get_scheduler_proxy

# Get status via engine
orch = await get_orchestrator_proxy()
status = await orch.status()

# Submit inference via engine
sched = await get_scheduler_proxy()
job = await sched.submit(prompt="...", model="Qwen3")
```

## Files Modified

### New Files
- `src/gaius/storage/database.py` - Centralized database queries
- `src/gaius/storage/kb_ops.py` - High-level KB operations

### Updated Files
- `src/gaius/storage/__init__.py` - Export KBDocument
- `src/gaius/mcp_server.py` - Use storage abstractions
- `src/gaius/engine/server.py` - Complete service handlers
- `src/gaius/inference/search/vector.py` - Storage backend support

### Removed Files
- `src/gaius/app2.py`
- `src/gaius/app3.py`
- `src/gaius/app4.py`

## Verification

```bash
# Test MCP server loads
uv run python -c "from gaius.mcp_server import create_server; print('OK')"

# Test storage abstraction
uv run python -c "
from gaius.storage import get_storage_backend
backend = get_storage_backend()
print(f'Documents: {backend.get_stats()[\"total_documents\"]}')
"

# Test KB operations
uv run gaius-cli --cmd "/reindex" --format json

# Test engine server compiles
uv run python -c "from gaius.engine.server import GaiusEngine; print('OK')"
```

## Next Steps

1. **Wire actual service implementations** - Connect handlers to service classes
2. **Implement Aeron bridge** - Real IPC transport (currently uses mock)
3. **Add integration tests** - End-to-end client → engine → backend
4. **Production deployment** - systemd unit, container orchestration

## Migration Notes

For existing deployments:

1. Install search dependencies: `uv sync --extra search`
2. Remove obsolete app files (done automatically)
3. Update any direct database queries to use `gaius.storage.database`
4. Update any direct KB access to use `gaius.storage.kb_ops`
