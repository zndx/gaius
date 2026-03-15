# Interfaces: TUI, CLI, MCP

Gaius provides three access paths to the engine. All three are thin clients — they contain no business logic, performing zero computation beyond display formatting. Every operation routes through gRPC to the engine, which is the single source of truth.

## TUI (Terminal User Interface)

The interactive terminal application built on [Textual](https://textual.textualize.io/).

```bash
uv run gaius
```

**Components**:
- **MainGrid**: 19x19 Go board for spatial visualization of embedding topology
- **MiniGridPanel**: Three 9x9 orthographic projections (CAD-style views showing topology, embeddings, and temporal evolution)
- **FileTree**: Plan 9-inspired navigation where agents appear as files under `/agents/`
- **ContentPanel**: Right panel displaying file contents, agent output, and position context
- **CommandInput**: Slash command input with history and tab completion
- **ObservePanel**: Real-time metrics with 15-second refresh, sparklines showing 5 minutes of history

**Design inspirations**: Go board (spatial metaphor, tenuki), Bloomberg Terminal (information density), Plan 9/Acme (everything is a file), CAD orthographic views (multiple projections updating together).

**Best for**: Interactive exploration, spatial navigation, visual pattern recognition.

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

**63 slash commands** spanning health diagnostics, agent management, inference control, evolution monitoring, knowledge base operations, visualization rendering, observability, and more. Every command available in the TUI is available in the CLI with identical semantics.

The CLI is the primary testing interface. After every code change, the CLI verifies that the product works — it is the product, not a wrapper around it.

**Best for**: Scripting, CI/CD integration, automated monitoring, quick status checks.

## MCP (Model Context Protocol)

Programmatic interface exposing 163 tools to AI assistants.

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

**163 MCP tools** organized by domain: health (diagnostics, observer, incidents, fixes), agents (evolution, swarm, latent memory, CLT), inference (scheduler, ask, evaluate), knowledge base (search, read, create, sync), observability (metrics, prometheus, status), visualization (render, collections), and bases (entity queries, lineage).

The MCP server enables AI-assisted operations — an external agent can monitor health, trigger evolution cycles, query the knowledge base, and manage infrastructure through the same gRPC protocol as human-operated interfaces.

**Best for**: AI-assisted operations, autonomous health maintenance, programmatic integration.

## Interface Comparison

| Feature | TUI | CLI | MCP |
|---------|-----|-----|-----|
| Interactive | Yes | No | No |
| Visual grid | Yes | No | No |
| JSON output | No | Yes | Yes |
| Scriptable | No | Yes | Yes |
| AI-accessible | No | No | Yes |
| Slash commands | 63 | 63 | N/A (163 tools) |
| Streaming output | Yes | No | No |

## Engine-First Architecture

All three interfaces use the same gRPC client library (`gaius.client`) to communicate with the engine:

```
TUI ─┐
CLI ──┼── gRPC (port 50051) ──→ Engine ──→ Services, Backends, Storage
MCP ─┘
```

The engine is the single source of truth for metric export, state management, and inference routing. Clients never access GPUs, databases, or external APIs directly. This architecture means:

- Adding a new capability requires only an engine service + gRPC method — all three clients get it automatically
- Testing via CLI validates the same code path as TUI and MCP
- Observability instrumentation happens once, in the engine, tagged with the originating service (`gaius-tui`, `gaius-cli`, `gaius-mcp`, `gaius-engine`, `gaius-worker`)
