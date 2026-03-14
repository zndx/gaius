# Engine-First Architecture

All business logic lives in the gRPC engine. The TUI, CLI, and MCP server are thin clients that translate user intent into engine RPC calls.

## Why Engine-First

Early Gaius had business logic scattered across the TUI, CLI, and various utility scripts. This created several problems:

- **Duplication**: The same logic reimplemented across interfaces
- **Inconsistency**: CLI and TUI producing different results for the same operation
- **Testing difficulty**: Business logic entangled with UI code
- **Resource contention**: Multiple processes competing for GPU access

The engine-first approach solves all of these by centralizing logic in a single daemon that manages all shared resources.

## The Rule

**Interfaces do not contain business logic.** They:

1. Parse user input into a command or RPC call
2. Send the request to the engine via gRPC
3. Format the response for display

If you find yourself writing business logic in `app.py`, `cli.py`, or `mcp_server.py`, it belongs in an engine service instead.

## Thin Client Examples

### TUI (app.py)

The TUI calls engine RPCs through the gRPC client:

```python
# TUI widget calls engine for health data
result = await self.grpc_client.call("GetHealthStatus")
self.display(result)
```

### CLI (cli.py)

The CLI dispatches slash commands to engine RPCs:

```python
# CLI maps /health to engine RPC
result = await client.call("GetHealthStatus")
print(json.dumps(result, indent=2))
```

### MCP (mcp_server.py)

MCP tools wrap engine RPCs for AI assistants:

```python
@server.tool()
async def health_observer_status():
    result = await client.call("GetHealthStatus")
    return result
```

## Benefits

- **Single source of truth**: One implementation, three interfaces
- **GPU management**: Engine controls all GPU allocation
- **Background services**: Evolution, cognition, health monitoring run in the engine daemon
- **Consistent state**: All clients see the same system state

## Exceptions

A few operations are interface-specific by necessity:

- **TUI rendering**: Widget layout and Textual event handling
- **CLI formatting**: JSON/text output formatting
- **MCP tool metadata**: Tool descriptions and parameter schemas

These are presentation concerns, not business logic.
