# Proto Change Workflow

Changes to the gRPC protobuf schema require a specific workflow to keep generated bindings, internal enums, and status mappings in sync.

## Step-by-Step

### 1. Edit the Proto File

Edit `src/gaius/engine/proto/gaius_service.proto`. Append new enum values — don't renumber existing values for wire compatibility.

### 2. Regenerate Bindings

```bash
just proto-generate
```

This generates `gaius_service_pb2.py` and `gaius_service_pb2_grpc.py`.

### 3. Update Generated Exports

Add new symbols to `src/gaius/engine/generated/__init__.py`:
- Add to the import block
- Add to the `__all__` list

**Critical**: Skipping this causes engine startup failures.

### 4. Update Internal Enums

If there's a parallel Python enum (e.g., in `vllm_controller.py`), sync it with the proto enum.

### 5. Update Status Mappings

Add string-to-proto mappings in the servicer's `_STATUS_MAP`.

### 6. Verify

```bash
uv run python -c "from gaius.engine.generated import NEW_SYMBOL; print('OK')"
```

### 7. Restart and Test

```bash
just restart-clean
uv run gaius-cli --cmd "/gpu status" --format json
```

## Common Mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Engine fails to start | Missing export in `__init__.py` | Add symbol to imports and `__all__` |
| Port 50051 not listening | Import error in gRPC server | Check engine logs |
| Status shows wrong value | Missing `_STATUS_MAP` entry | Add mapping |

See [Protobuf Schema](../architecture/protobuf.md) for more detail.
