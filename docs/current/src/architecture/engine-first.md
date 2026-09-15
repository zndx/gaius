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
- **Background coordination**: Evolution, cognition, health monitoring and the scheduled-task queue run in the engine daemon. Substantive workloads are not executed in the engine process; the engine delegates them to platform Metaflow (see [Engine-First and workload execution](#engine-first-and-workload-execution)).
- **Consistent observability**: OTel instrumentation happens once in the engine, tagged with the originating service (`gaius-tui`, `gaius-cli`, `gaius-mcp`, `gaius-engine`, `gaius-worker`).
- **Testing**: CLI validates the same code path as TUI and MCP. Testing via CLI *is* testing the product.

## Engine-First and workload execution

Engine-First governs where logic lives and how it is reached. It does not mean the engine process executes every workload. In production the engine **yields execution**:

- **Substantive workflows are Metaflow flows** (`GaiusFlow`), executed on the shared Kubernetes cluster under YuniKorn admission, and orchestrated by the Signals Airflow across the federated workspace. See [Metaflow Integration](./metaflow.md).
- **Schedules are declared locally as pg_cron jobs** (see [pg_cron](./pgcron.md)) and mirrored in the workload catalogue. When Airflow is available the catalogue syncs to Signals, which materialises one DAG per enabled class, so every project's runs align and execute smoothly on one clock.
- **Flows are engine clients.** A flow reaches thinking, embeddings and other capabilities over gRPC (`Engine/Complete`, `EmbedTexts`) exactly as the CLI does; it never loads a second engine, a model, or an inference shortcut. That is what keeps platform execution Engine-First.
- **The engine keeps the coordination-shaped work**: the catalogue and its sync, the scheduled-task queue and its handlers that spawn or attach runs, YuniKorn claims, objectives and verification, health and remediation.

This division is not a compromise of the principle; it is the principle applied to a federated deployment. Heavy compute inside the engine process (a JVM, a BERT model, a long CPU stage on the event loop) starves the engine's own health probes, and a workload that only the engine process can run cannot be ordered or admitted alongside the other projects' runs. Do not cite Engine-First as a reason to move a workflow out of Metaflow and into an engine handler.

## Exceptions

A few operations are interface-specific by necessity:

- **TUI rendering**: Widget layout, Textual event handling, sparkline rendering
- **CLI formatting**: JSON/text output formatting, color codes
- **MCP tool metadata**: Tool descriptions and parameter schemas for AI assistant discovery

These are presentation concerns, not business logic.
