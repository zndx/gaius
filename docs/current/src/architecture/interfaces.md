# Interfaces: TUI, CLI, MCP

Gaius provides three access paths to the engine. Each serves a different use case but all communicate via the same gRPC protocol.

## TUI (Terminal User Interface)

The interactive terminal application built on [Textual](https://textual.textualize.io/).

```bash
uv run gaius
```

**Components**:
- **MainGrid**: 19x19 Go board for spatial visualization
- **MiniGridPanel**: Three 9x9 orthographic projections (CAD-style views)
- **FileTree**: Plan 9-inspired navigation with agents as files
- **ContentPanel**: Right panel displaying context and output
- **CommandInput**: Slash command input with history

**Best for**: Interactive exploration, spatial navigation, visual pattern recognition.

See [The TUI](../guide/tui.md) for the user guide.

## CLI (Command Line Interface)

Non-interactive interface for scripting and automation.

```bash
# Single command execution
uv run gaius-cli --cmd "/health" --format json

# Pipe to jq for extraction
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[]'

# Poll for status changes
for i in $(seq 1 15); do
    sleep 10
    uv run gaius-cli --cmd "/gpu status" --format json
done
```

**63 slash commands** covering health, agents, inference, evolution, knowledge base, visualization, and more.

**Best for**: Scripting, CI/CD integration, automated monitoring, quick status checks.

See [The CLI](../guide/cli.md) for the user guide.

## MCP (Model Context Protocol)

Programmatic interface exposing 163 tools to AI assistants like Claude Code.

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

**163 MCP tools** organized by domain: health, agents, inference, knowledge base, observability, evolution, visualization, bases, and more.

**Best for**: AI-assisted operations, autonomous health maintenance, Claude Code integration.

See [MCP Integration](../guide/mcp.md) for setup and usage.

## Interface Comparison

| Feature | TUI | CLI | MCP |
|---------|-----|-----|-----|
| Interactive | Yes | No | No |
| Visual grid | Yes | No | No |
| JSON output | No | Yes | Yes |
| Scriptable | No | Yes | Yes |
| AI-accessible | No | No | Yes |
| Slash commands | Yes | Yes | N/A |
| Streaming output | Yes | No | No |

## Shared Protocol

All three interfaces use the same gRPC client library (`gaius.client`) to communicate with the engine:

```python
from gaius.client import GrpcClient, GrpcClientConfig

config = GrpcClientConfig(
    host="localhost",
    port=50051,
    timeout=30,  # default; inference calls use 120s
)
client = GrpcClient(config)
result = await client.call("GetHealthStatus")
```

The default timeout is 30 seconds. Inference calls (completions, evaluations) use 120 seconds. These can be overridden via the `GAIUS_ENGINE_TIMEOUT` environment variable.
