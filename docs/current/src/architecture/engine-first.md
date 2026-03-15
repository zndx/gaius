# Engine-First Architecture

All business logic lives in the gRPC engine. The TUI, CLI, and MCP server are thin clients that translate user intent into engine RPC calls and format responses for display.

## Why Engine-First

Early Gaius had business logic scattered across the TUI, CLI, and various utility scripts. This created several problems:

- **Duplication**: The same logic reimplemented across interfaces
- **Inconsistency**: CLI and TUI producing different results for the same operation
- **Testing difficulty**: Business logic entangled with UI code
- **Resource contention**: Multiple processes competing for GPU access
- **Observability blind spots**: Metrics emitted inconsistently across interfaces

The engine-first approach solves all of these by centralizing logic in a single daemon that manages all shared resources — GPUs, database connections, vector stores, and inference endpoints.

## The Rule

**Interfaces do not contain business logic.** They:

1. Parse user input into a command or RPC call
2. Send the request to the engine via gRPC (port 50051)
3. Format the response for display

If you find yourself writing business logic in `app.py`, `cli.py`, or `mcp_server.py`, it belongs in an engine service instead.

## Architecture

```
TUI (Textual)  ─┐
CLI (argparse)  ──┼── gRPC client ──→ Engine daemon (port 50051)
MCP (stdio)     ─┘                         │
                                    ┌──────┼──────┐
                                    │      │      │
                               Services  Backends  Storage
                                    │      │      │
                              Scheduler  vLLM    PostgreSQL
                              Health    Nomic    Qdrant
                              Evolution optillm  R2/MinIO
                              Cognition ColPali  Filesystem
```

The engine hosts 37 services organized into four groups: resource management, intelligence, data, and external integration. All services share the same process, enabling zero-cost inter-service calls.

## Thin Client Examples

### TUI (app.py)

```python
result = await self.grpc_client.call("GetHealthStatus")
self.display(result)  # Formatting only
```

### CLI (cli.py)

```python
result = await client.call("GetHealthStatus")
print(json.dumps(result, indent=2))  # Serialization only
```

### MCP (mcp_server.py)

```python
@server.tool()
async def health_observer_status():
    result = await client.call("GetHealthStatus")
    return result  # Schema mapping only
```

## Benefits

- **Single source of truth**: One implementation, three interfaces. A new feature requires only an engine service + gRPC method — all clients get it automatically.
- **GPU management**: Engine controls all GPU allocation through the Orchestrator. No client can directly access CUDA devices.
- **Background services**: Evolution, cognition, health monitoring, and scheduled tasks run in the engine daemon with zero coordination overhead.
- **Consistent observability**: OTel instrumentation happens once in the engine, tagged with the originating service (`gaius-tui`, `gaius-cli`, `gaius-mcp`, `gaius-engine`, `gaius-worker`).
- **Testing**: CLI validates the same code path as TUI and MCP. Testing via CLI *is* testing the product.

## Exceptions

A few operations are interface-specific by necessity:

- **TUI rendering**: Widget layout, Textual event handling, sparkline rendering
- **CLI formatting**: JSON/text output formatting, color codes
- **MCP tool metadata**: Tool descriptions and parameter schemas for AI assistant discovery

These are presentation concerns, not business logic.
