# MCP Tools

163 MCP tools expose Gaius functionality to Claude Code and other MCP-compatible clients.

## Tool Categories

| Category | Count | Description |
|----------|-------|-------------|
| Health | ~20 | Health checks, FMEA, observer, incidents |
| Agents | ~15 | Swarm, evolution, cognition, theta |
| Inference | ~10 | Scheduler, endpoints, GPU status |
| Knowledge Base | ~15 | Search, CRUD, sync, semantic search |
| Observability | ~10 | Metrics, Prometheus, status |
| Data Pipeline | ~10 | Metaflow, lineage, flows |
| Visualization | ~5 | Render, card management |
| Bases | ~10 | Feature store queries, entity history |
| Collections | ~15 | Card collections, publishing |
| Articles | ~5 | Article curation, status |
| X Bookmarks | ~8 | Sync, auth, folders |
| Calibration | ~5 | Understanding calibration |
| Evolution | ~10 | Agent versions, optimization |
| System | ~25 | Config, models, sessions, research |

## Naming Convention

Tools follow a consistent naming pattern: `<domain>_<action>` (e.g., `health_observer_status`, `scheduler_submit`, `gpu_health`).

## Example Usage

From Claude Code:

```
> Use the health_observer_status tool to check system health
> Use the gpu_health tool to check GPU memory usage
> Use the search_kb tool to find articles about pensions
```

## Server Configuration

```json
{
  "mcpServers": {
    "gaius": {
      "command": "uv",
      "args": ["run", "gaius-mcp"],
      "cwd": "/path/to/gaius"
    }
  }
}
```

> **Note**: For the complete tool list with parameters, see `src/gaius/mcp_server.py`.
