# TUI Streaming and Fail-Fast Fixes

**Status: COMPLETED** (2025-12-30 19:37 UTC)

## Summary

Fixed the `/ambient cycle` TUI hang and ensured ThinkPanel, ObservePanel (GPU monitor), and `/watch` commands comply with fail-fast requirements.

## Changes Made

### 1. Fixed `/ambient cycle` Streaming (app.py:3262-3333)

**Problem**: TUI froze during `/ambient cycle` because `content.show_file()` was called synchronously in a tight async loop without yielding control.

**Solution**: Added debounced updates with 200ms interval and `await asyncio.sleep(0)` to yield control:

```python
UPDATE_INTERVAL = 0.2  # Max 5 updates/sec to keep TUI responsive

now = time.monotonic()
if now - last_update >= UPDATE_INTERVAL:
    content.show_file("ambient.md", progress_text)
    last_update = now
    await asyncio.sleep(0)  # Yield control to TUI event loop
```

### 2. ThinkPanel Fail-Fast (think_panel.py)

**Problem**: ThinkPanel silently fell back to polling when streaming failed.

**Solution**: Removed all fallback-to-polling code paths. Now shows explicit errors with guru meditation codes:

- `#THINK.00000001.STREAMFAIL` - Streaming setup failed
- `#THINK.00000002.NOENGINE` - Engine not connected
- `#THINK.00000003.COGFAIL` - Cognition stream failed
- `#THINK.00000004.EVOLFAIL` - Evolution stream failed

### 3. GPU Monitor Strict Fail-Fast (gpu_monitor.py)

**Problem**: GPU monitor functions returned empty dict `{}` on errors instead of raising.

**Solution**: All three sync functions now raise `RuntimeError` with guru codes:

- `#GPU.00000001.PYNVML_MISSING` - pynvml import failed
- `#GPU.00000002.MEMORYFAIL` - GPU memory query failed
- `#GPU.00000003.UTILFAIL` - GPU utilization query failed
- `#GPU.00000004.INFOFAIL` - GPU info query failed

### 4. Removed Watch Stubs (cli.py)

**Problem**: `/watch spans` and `/watch traces` were stub implementations returning empty arrays.

**Solution**: Both now raise `NotImplementedError` with guru codes:

- `#OTEL.00000001.NOTAVAIL` - OpenTelemetry not available
- `#OTEL.00000002.SPANS_NYI` - Span streaming not yet implemented
- `#OTEL.00000003.TRACES_NYI` - Trace streaming not yet implemented

## Testing Results

### CLI Streaming
```bash
uv run gaius-cli --cmd "/ambient cycle" --format json
# ✓ All phases stream correctly:
# - AMBIENT_PHASE_BASELINE_HEALTH
# - AMBIENT_PHASE_BASELINE_WORKLOAD
# - AMBIENT_PHASE_REASONING_EVICTION
# - AMBIENT_PHASE_REASONING_WORKLOAD (7716ms)
# - AMBIENT_PHASE_BASELINE_RESTORATION
```

### TUI Responsiveness (Textual Pilot)
```
TUI responsive at iteration 1
TUI responsive at iteration 2
...
TUI responsive at iteration 10
SUCCESS: TUI remained responsive during ambient cycle
```

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/app.py` | Added debouncing to `_run_ambient_cycle()` |
| `src/gaius/widgets/think_panel.py` | Removed silent polling fallback, added guru codes |
| `src/gaius/engine/resources/gpu_monitor.py` | Changed all returns to raises |
| `src/gaius/cli.py` | Replaced watch stubs with NotImplementedError |

## Architecture Compliance

All changes now comply with:
1. **gRPC thin client architecture**: TUI communicates only via gRPC
2. **Fail-fast principle**: No silent fallbacks, all errors are actionable
3. **Guru meditation codes**: Unique identifiers for each failure mode
