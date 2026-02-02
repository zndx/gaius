# Article Curation Streaming Fix

## Summary

Fixed `/article curate` gRPC streaming to properly receive pg_notify events from ArticleCurationFlow.

## Root Causes

### 1. Wrong Metaflow Command

**Before:**
```python
cmd = [
    "uv", "run", "python", "-m", "metaflow.cli",
    "run", "ArticleCurationFlow",
]
```

**After:**
```python
cmd = [
    "uv", "run", "python", "-m", "gaius.flows.article_curation.flow",
    "run",
]
```

Metaflow flows are run using the module that defines them, not `metaflow.cli`.

### 2. Incorrect asyncio Event Loop Handling

**Before:**
```python
asyncio.get_event_loop().call_soon_threadsafe(
    lambda e=event: event_queue.put_nowait(e)
)
```

**After:**
```python
event_queue.put_nowait(event)
```

The asyncpg callback runs synchronously on the same event loop thread, so `call_soon_threadsafe` is unnecessary and can cause issues in Python 3.10+ where `get_event_loop()` behaves differently in async contexts.

## Files Modified

| File | Change |
|------|--------|
| `collection_service.py:1395-1397` | Fixed Metaflow command to use flow module |
| `collection_service.py:1366-1368` | Fixed asyncio callback to use direct queue put |
| `collection_service.py:1346` | Added `loop = asyncio.get_running_loop()` |
| `collection_service.py:1391` | Added 100ms delay to ensure listener is ready |

## Testing

Direct service test shows events being received:
```
CALLBACK: article_curation_progress -> {"event_id" : 24, ...
EVENT: start - Starting article curation for ai-keiretsu...
CALLBACK: article_curation_progress -> {"event_id" : 25, ...
EVENT: research - Synthesizing 34 zettelkasten notes...
```

## Deployment

Engine restart required to pick up changes:
```bash
devenv tasks run restart:clean
```

After restart, verify with:
```bash
uv run gaius-cli --cmd "/article curate ai-keiretsu"
```
