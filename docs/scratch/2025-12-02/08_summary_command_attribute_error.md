# Summary Command AttributeError Fix

**Date:** 2025-12-02
**Issue:** `/summary` command crashed with "dailysumarynote object has no attribute title"

## Root Cause

In `src/gaius/app.py:1165`, the code tried to access `note.title` and `note.citations` attributes that don't exist on the `DailySummaryNote` dataclass.

### DailySummaryNote Actual Attributes

From `src/gaius/agents/daily_summary.py:26-49`:

```python
@dataclass
class DailySummaryNote:
    summary_date: date
    profile: str
    overview: str
    activity_summary: str
    key_entries: list[str]  # ← This exists
    insights: list[str]
    tomorrow_focus: str
    total_entries: int
    total_queries: int
    total_swarm_runs: int
    total_tokens: int
    domains_active: list[str]
    generated_at: datetime
    generator_model: str
    # NO 'title' attribute
    # NO 'citations' attribute
```

## Fix Applied

**File:** `src/gaius/app.py:1161-1169`

### Before
```python
think.complete_trace(
    operation="synthesis",
    query="daily summary",
    summary=f"Generated summary: {note.title}",  # ← AttributeError!
    tokens=0,
    sources=len(note.citations) if note.citations else 0,  # ← AttributeError!
    duration_ms=duration_ms,
)
```

### After
```python
think.complete_trace(
    operation="synthesis",
    query="daily summary",
    summary=f"Generated summary for {note.summary_date}",  # ✓ Uses summary_date
    tokens=0,
    sources=len(note.key_entries),  # ✓ Uses key_entries list
    duration_ms=duration_ms,
)
```

## Changes

1. **Replaced `note.title`** → `note.summary_date` (the date of the summary)
2. **Replaced `note.citations`** → `note.key_entries` (list of KB entries mentioned)

## Testing

```bash
# In TUI, press `/` then type:
summary

# Should now generate without error and show:
# - Generated summary for 2025-12-02
# - Sources: <number of key_entries>
```

## Related

This is part of the activity logging fixes from `07_activity_logging_bug_fix.md`. With the database now starting properly, daily summaries will have accurate data from the activity tracker.
