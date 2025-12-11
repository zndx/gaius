# Health Watch - Runtime Observation for Fallbacks and Stubs

Implemented `/health watch <command>` to execute commands while monitoring for patterns indicating incomplete implementations.

## Motivation

When beta testers (or we ourselves) encounter functionality that isn't fully implemented, the system should surface this clearly rather than silently falling back to degraded behavior. The dev policy requires:
- All fallbacks, stub implementations, and caught exceptions must be evidenced in logs and/or telemetry
- The `LEGACY_FALLBACK: ... - tech debt` convention marks known tech debt

## Implementation

### New Module: `src/gaius/health/watcher.py`

Provides runtime observation of command execution:

```python
class ObservationType(Enum):
    STUB = "stub"
    FALLBACK = "fallback"
    LEGACY = "legacy"
    NOT_IMPLEMENTED = "not_implemented"
    EXCEPTION_CAUGHT = "exception_caught"
    SUCCESS = "success"
    NOOP = "noop"

class CommandWatcher:
    """Watches command execution for observable patterns."""

    async def watch_command(command_fn, command_str) -> WatchResult
```

### Standard Patterns

The watcher looks for these patterns in log output:

| Pattern | Type | Action |
|---------|------|--------|
| `LEGACY_FALLBACK: ... - tech debt` | LEGACY | warn_tech_debt |
| `(stub)` or `\bstub\b` | STUB | warn_incomplete |
| `not (yet )?implemented` | NOT_IMPLEMENTED | warn_incomplete |
| `fallback` | FALLBACK | info_fallback |
| `no-?op` | NOOP | warn_noop |

### CLI Integration

Added `/health watch <command>` subcommand:

```bash
# Watch a command for fallbacks
/health watch /scheduler status

# Output shows any problematic patterns detected
{
  "status": "warn",
  "has_issues": true,
  "observations": {
    "fallback": [
      {"message": "fallback", "line": "Optillm fallback configured..."}
    ]
  }
}
```

### Heuristics Format Update

Updated `build/dev/current/heuristics/gaius/_index.md` to include Observable Patterns specification:

```yaml
log_patterns:
  - pattern: "LEGACY_FALLBACK: .* - tech debt"
    level: warning
    indicates: fallback_active

span_attributes:
  - name: "implementation.status"
    values: ["stub", "partial", "complete"]
```

Updated evolution daemon heuristic with Observable Patterns section.

## Files Changed

| File | Changes |
|------|---------|
| `src/gaius/health/watcher.py` | NEW: CommandWatcher, ObservationType, WatchResult |
| `src/gaius/cli.py` | Added /health watch subcommand |
| `build/dev/current/heuristics/gaius/_index.md` | Added Observable Patterns spec |
| `build/dev/current/heuristics/gaius/evolution/daemon_not_running.md` | Added Observable Patterns section |

## Usage Examples

```bash
# Show help
uv run gaius-cli --cmd "/health watch" --format json

# Watch scheduler status (detects fallback configuration)
uv run gaius-cli --cmd "/health watch /scheduler status" --format json

# Watch any command
uv run gaius-cli --cmd "/health watch /evolve status" --format json
```

## Future Enhancements

1. **OTel Integration**: Capture span attributes like `implementation.status` and `fallback.used`
2. **Heuristic Matching**: Match observations to known heuristics for actionable suggestions
3. **Continuous Watch**: Stream observations in real-time for long-running operations
4. **Pattern Registry**: Load custom patterns from heuristic KB entries
