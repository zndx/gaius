# Cognition kb_entries Table Fix

**Date**: 2025-12-28
**Status**: Fixed and Verified

## Problem

pg_cron scheduled cognition cycles were completing in 1ms with 0 thoughts generated. The scheduled tasks were running but producing no output.

## Root Cause

The engine-level cognition logic in `src/gaius/engine/services/cognition_logic.py` was querying a `kb_entries` table that **never existed**. This was a design concept from early documentation that was never implemented.

The actual KB content lives in:
- `content_items` - RSS/feed content (3017+ items)
- `activity_events` with `event_type = 'kb_create'` - manually created KB docs

The exception was caught silently:
```python
except Exception as e:
    logger.warning(f"Failed to gather KB context: {e}")  # "relation 'kb_entries' does not exist"
```

This caused `_gather_kb_context()` to return empty context, which led to early return with 0 thoughts.

Additionally, the code referenced a `thoughts` table which should be `cognition_thoughts`.

## Fix Applied

Updated `_gather_kb_context()` in `cognition_logic.py` to query the correct tables:

1. **content_items** - Get recent RSS/feed content with kb_path
2. **activity_events** - Get recent kb_create events
3. **feed_sources** - Join for domain names
4. **cognition_thoughts** (not `thoughts`) - Get recent thoughts for continuity

## Verification

```bash
uv run gaius-cli --cmd "/thoughts test-cycle" --format json
```

Before fix:
```json
{
  "thoughts_generated": 0,
  "duration_ms": 1  // Nearly instant - early return
}
```

After fix:
```json
{
  "thoughts_generated": 3,
  "patterns_detected": 1,
  "duration_ms": 14148
}
```

Thoughts verified in database:
```sql
SELECT title, thought_type FROM cognition_thoughts ORDER BY created_at DESC LIMIT 3;
-- "Emerging Patterns in Cognitive Focus..." (self_observation)
-- "Frequent Health Reports and Issues" (pattern)
-- "Blind Spots and Gaps in Observations..." (self_observation)
```

## New CLI Command

Added `/thoughts test-cycle` command to directly test engine-level cognition via gRPC, bypassing the L5 agent code path. This is useful for debugging the pg_cron scheduled task behavior.

## Files Changed

- `src/gaius/engine/services/cognition_logic.py` - Fixed `_gather_kb_context()` to use correct tables
- `src/gaius/cli.py` - Added `/thoughts test-cycle` command

## Lessons Learned

1. Schema drift between design docs and implementation is common - always verify tables exist
2. Silent exception handling (`except: pass`) hides critical failures
3. A 1ms completion time for a task that should take 10-90 seconds is a red flag
4. Having a gRPC test command helps isolate engine-level vs L5 agent code paths
