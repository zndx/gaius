# MCP Integration

Gaius exposes 163 tools via the Model Context Protocol (MCP), making its full functionality available to Claude Code and other MCP-compatible AI clients.

## What Is MCP?

The Model Context Protocol is a standard for connecting AI assistants to external tools and data sources. When configured, Claude Code can call Gaius tools directly -- checking health, querying the knowledge base, managing agents, and running operations -- all within a conversational workflow.

## Starting the MCP Server

```bash
uv run gaius-mcp
```

This starts a stdio-based MCP server that communicates with Claude Code over standard input/output. The server connects to the same gRPC engine (port 50051) used by the TUI and CLI.

## What You Can Do

With MCP integration, Claude Code can operate across the full Gaius stack:

| Category | Tools | Examples |
|----------|-------|---------|
| Health & Diagnostics | 15 tools | `health_observer_check`, `fmea_catalog`, `gpu_health` |
| Agent Management | 12 tools | `optimize_agent`, `save_agent_version`, `run_swarm` |
| Knowledge Base | 10 tools | `search_kb`, `semantic_search`, `create_kb` |
| Inference & Scheduling | 8 tools | `ask_reasoning`, `evaluate_with_xai`, `scheduler_submit` |
| Observability | 8 tools | `prometheus_query`, `observe_metrics`, `metabase_get_dashboard` |
| Content Pipeline | 12 tools | `article_curate`, `collection_publish_cards`, `publish_cards` |
| Evolution & Training | 10 tools | `trigger_evolution`, `run_daily_evaluation`, `get_evolution_trend` |
| Topology & Geometry | 6 tools | `compute_tda`, `explain_grid_position`, `calibrate_understanding` |

## Architecture

The MCP server is a thin client over the same gRPC engine used by the TUI and CLI. Each MCP tool maps to an engine service call or direct database/HTTP query. The server handles JSON serialization and error propagation.

```
Claude Code  <--stdio-->  gaius-mcp  <--gRPC-->  Engine (port 50051)
                                     <--HTTP-->  Services (Metabase, Prometheus, etc.)
                                     <--SQL-->   PostgreSQL (port 5444)
```

This architecture means MCP tools have exactly the same capabilities as CLI commands — no degraded mode, no subset API.

## Next Steps

- **[Claude Code Setup](./claude-code-setup.md)** -- configure your `.claude.json` to connect
- **[Tool Categories](./mcp-categories.md)** -- browse the 163 tools by domain
