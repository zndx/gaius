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

With MCP integration, Claude Code can:

- **Diagnose issues**: query health status, check endpoint state, review incident history
- **Manage agents**: view evolution status, trigger training, promote agent versions
- **Search knowledge**: query the knowledge base, perform semantic search, explore lineage
- **Run inference**: submit prompts to the scheduler, evaluate outputs, manage XAI budget
- **Monitor systems**: read Prometheus metrics, check Metabase dashboards, view GPU health
- **Create content**: trigger article curation, render card visualizations, manage collections

## Architecture

The MCP server is a thin wrapper over the same services available through the CLI. Each MCP tool maps to an internal command or service call. The server handles serialization (JSON arguments and responses) and error propagation.

```
Claude Code  <--stdio-->  gaius-mcp  <--gRPC-->  Engine (port 50051)
                                     <--HTTP-->  Services (Metabase, Prometheus, etc.)
                                     <--SQL-->   PostgreSQL (port 5444)
```

## Next Steps

- **[Claude Code Setup](./claude-code-setup.md)** -- configure your `.claude.json` to connect
- **[Tool Categories](./mcp-categories.md)** -- browse the 163 tools by domain
