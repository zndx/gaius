# ACP Timeout Removal

## Summary

Removed the artificial 300-second timeout on ACP sessions. Claude Code should run until natural completion (issue resolved or GitHub issue created), not be killed by an arbitrary timer.

## Problem

When the HealthObserverService escalated to Claude Code via ACP, the session was killed after 300 seconds even though Claude Code was actively working:

```
08:55:37 [WARNING] Prompt timed out after 300.0s.
Guru Meditation: #ACP.00000004.PROMPTTIMEOUT
```

The debug log (`~/.claude/debug/afce1f07-1afd-4851-9161-b2826ed5ce5a.txt`) showed Claude Code was actively investigating - running Bash commands, using MCP tools, creating TodoWrite entries - and would have completed successfully given more time.

## Solution

Made ACP prompt timeout optional (None = no timeout):

1. **`src/gaius/acp/client.py`** (lines 112-113)
   - Changed `prompt_timeout: float = 300.0` to `prompt_timeout: float | None = None`
   - Updated `prompt()` method to conditionally apply `asyncio.timeout()` only when timeout is not None

2. **`src/gaius/engine/services/health_observer_service.py`** (lines 84-86, 772-791)
   - Removed `acp_timeout: float = 300.0` from ObserverConfig
   - Removed timeout parameter from ACP client initialization and prompt calls
   - Claude Code now runs until it naturally completes its investigation

## Changes

```python
# client.py - before
prompt_timeout: float = 300.0  # 5 minutes for complex operations

# client.py - after
prompt_timeout: float | None = None  # None = no timeout, let Claude Code run to completion

# prompt() method - now conditionally applies timeout
if effective_timeout is not None:
    async with asyncio.timeout(effective_timeout):
        await self._connection.prompt(...)
else:
    # No timeout - let Claude Code run until natural completion
    await self._connection.prompt(...)
```

## Verification

```bash
uv run python -c "from gaius.acp import ACPConfig; print(f'timeout: {ACPConfig().prompt_timeout}')"
# Output: timeout: None
```

## Files Changed

- `src/gaius/acp/client.py` - Made timeout optional, updated prompt() method
- `src/gaius/engine/services/health_observer_service.py` - Removed acp_timeout config and usage
