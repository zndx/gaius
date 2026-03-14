# Claude Code Setup

This page describes how to configure Claude Code to use the Gaius MCP server, giving Claude Code direct access to all 163 Gaius tools.

## Configuration

Add the Gaius MCP server to your Claude Code MCP configuration. The configuration file is typically at `~/.claude.json` or in your project's `.claude/` directory.

Add the following to the `mcpServers` section:

```json
{
  "mcpServers": {
    "gaius": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/gaius", "gaius-mcp"],
      "env": {
        "GAIUS_ENGINE_HOST": "localhost",
        "GAIUS_ENGINE_PORT": "50051"
      }
    }
  }
}
```

Replace `/path/to/gaius` with the absolute path to your Gaius repository checkout.

## Environment Variables

The MCP server respects these environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GAIUS_ENGINE_HOST` | `localhost` | gRPC engine hostname |
| `GAIUS_ENGINE_PORT` | `50051` | gRPC engine port |
| `DATABASE_URL` | from config | PostgreSQL connection URL |

In most setups, the defaults work without any environment overrides.

## Prerequisites

Before Claude Code can use Gaius tools, the platform services must be running:

```bash
cd /path/to/gaius
devenv shell
devenv processes up -d
```

The MCP server connects to the gRPC engine on startup. If the engine is not running, tool calls will fail with connection errors.

## Verifying the Connection

After configuring, ask Claude Code to run a health check:

> "Check the Gaius health status"

Claude Code should invoke the `health_observer_check` tool and return a structured health report. If it reports connection errors, verify that `devenv processes up -d` has been run.

## Tool Discovery

Claude Code can list available tools. The 163 tools are organized into categories such as health, agents, inference, knowledge base, observability, evolution, visualization, and bases. See [Tool Categories](./mcp-categories.md) for the full breakdown.

## Security Considerations

The MCP server runs locally and communicates with Claude Code over stdio. It does not expose a network port. All operations are scoped to the local Gaius instance. For ACP (Agent Client Protocol) integration, which involves GitHub operations, additional security controls apply -- see the [ACP Security Model](../architecture/acp-security.md) documentation.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Tool not found" | MCP config not loaded | Restart Claude Code after editing config |
| Connection refused | Engine not running | Run `devenv processes up -d` |
| Timeout on tool calls | Engine overloaded | Check `/gpu status` or run `just restart-clean` |
| Python errors | Dependencies missing | Run `uv sync` in the gaius directory |
