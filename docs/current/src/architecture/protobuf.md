# Protobuf Schema

The gRPC API is defined in Protocol Buffers. Changes to the proto require a specific workflow to keep generated bindings, internal enums, and status mappings in sync.

## Key Files

| File | Purpose |
|------|---------|
| `engine/proto/gaius_service.proto` | Proto definitions (source of truth) |
| `engine/proto/gaius_service_pb2.py` | Generated Python bindings |
| `engine/proto/gaius_service_pb2_grpc.py` | Generated gRPC stubs |
| `engine/generated/__init__.py` | Re-exports for clean imports |
| `engine/grpc/servicers/gaius_servicer.py` | Server-side implementation |

## Endpoint Status Values

```protobuf
enum ProcessStatus {
    PROCESS_STATUS_UNSPECIFIED = 0;
    PROCESS_STATUS_STOPPED = 1;
    PROCESS_STATUS_STARTING = 2;
    PROCESS_STATUS_HEALTHY = 3;
    PROCESS_STATUS_UNHEALTHY = 4;
    PROCESS_STATUS_STOPPING = 5;
    PROCESS_STATUS_FAILED = 6;
    PROCESS_STATUS_PENDING = 7;   // Queued for startup
}
```

Startup state transitions: `PENDING -> STARTING -> HEALTHY`

## Change Workflow

### 1. Edit the Proto File

Append new enum values. Don't renumber existing values for wire compatibility.

### 2. Regenerate Bindings

```bash
just proto-generate
```

### 3. Update Generated Exports

Add new symbols to `engine/generated/__init__.py`:
- Add to the import block
- Add to the `__all__` list

**Critical**: Skipping this step causes import errors at engine startup.

### 4. Update Internal Enums

If there's a parallel Python enum (e.g., in `vllm_controller.py`), sync it with the proto enum.

### 5. Update Status Mappings

Add string-to-proto mappings in the servicer's `_STATUS_MAP`.

### 6. Verify Import

```bash
uv run python -c "from gaius.engine.generated import NEW_SYMBOL; print('OK')"
```

### 7. Restart and Test

```bash
just restart-clean
uv run gaius-cli --cmd "/gpu status" --format json
```

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Engine fails to start | Missing export in `__init__.py` | Add symbol to imports and `__all__` |
| Port 50051 not listening | gRPC server didn't initialize | Check logs for import errors |
| Status shows wrong value | Missing status mapping | Add to `_STATUS_MAP` |

## Testing gRPC Features

gRPC reflection is not enabled, so `grpcurl` cannot discover services. Use the CLI instead:

```bash
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[] | {name, status}'
```
