# TUI /inference ensure Command

**Date:** 2025-12-02
**Context:** Added missing `/inference ensure` command to TUI (already existed in CLI)

## Issue

The `/inference ensure` command was implemented in CLI but not in TUI, creating asymmetry between the two interfaces.

## Implementation

### Added ensure subcommand (app.py:1431-1458)

```python
elif args == "ensure":
    # Ensure default model (nvidia/Orchestrator-8B) is running
    content.show_file("inference.txt", "Ensuring nvidia/Orchestrator-8B is running...")

    async def ensure():
        try:
            manager = get_inference_manager()

            # Track progress in content panel
            progress_lines = ["# Starting nvidia/Orchestrator-8B", ""]

            def update_progress(task_name: str, progress: float, message: str):
                progress_lines.append(f"[{progress:.0%}] {message}")
                content.show_file("inference.md", "\n".join(progress_lines))

            success = await manager.ensure_orchestrator_running(update_progress)

            if success:
                progress_lines.append("")
                progress_lines.append("✓ nvidia/Orchestrator-8B is ready")
                content.show_file("inference.md", "\n".join(progress_lines))
            else:
                content.show_file("error.txt", "Failed to ensure default model is running.")

        except Exception as e:
            content.show_file("error.txt", f"Error ensuring default model: {e}")

    asyncio.create_task(ensure())
```

**Features:**
- Progress tracking shown in content panel as markdown
- Updates in real-time: `[0%] Checking orchestrator status` → `[100%] Ready`
- Success message with checkmark: `✓ nvidia/Orchestrator-8B is ready`
- Error handling with clear messages

### Updated documentation

**Docstring (line 1313):**
```python
/inference ensure              - Ensure default model (nvidia/Orchestrator-8B) running
```

**Status output footer (line 1353):**
```
Use `/inference ensure` to start the default model (nvidia/Orchestrator-8B).
Use `/inference start <endpoint>` to start an endpoint.
Use `/inference stop <endpoint>` to stop an endpoint.
```

**Error message (line 1461):**
```
Usage:
  /inference status
  /inference start <endpoint>
  /inference stop <endpoint>
  /inference restart <endpoint>
  /inference ensure
```

## Usage

### In TUI:
```
/inference ensure
```

Shows progress in content panel:
```
# Starting nvidia/Orchestrator-8B

[0%] Checking orchestrator status
[20%] Starting orchestrator endpoint
[40%] Waiting for model to load
[60%] Loading model into VRAM
[90%] Model loaded, warming up
[100%] Ready

✓ nvidia/Orchestrator-8B is ready
```

### In CLI:
```bash
uv run python -m gaius.cli --cmd "/inference ensure" --format json
```

Progress to stderr, result to stdout as JSON.

## Complete Command Set

Now fully symmetric between TUI and CLI:

| Command | Purpose |
|---------|---------|
| `/inference status` | Show all endpoints, queue status, metrics |
| `/inference start <endpoint>` | Start specific endpoint (reasoning, coding, fast, etc.) |
| `/inference stop <endpoint>` | Stop specific endpoint |
| `/inference restart <endpoint>` | Restart specific endpoint |
| `/inference ensure` | Ensure default model running (nvidia/Orchestrator-8B) |

## Status

✅ `/inference ensure` implemented in TUI
✅ Progress tracking in content panel
✅ Documentation updated
✅ Error handling added
✅ Symmetric with CLI
✅ TUI starts without errors
