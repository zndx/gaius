# M5: Situational Awareness + Daily Summary

## Summary

Completed Milestone 5 of the Gaius v1.0 roadmap, implementing activity tracking,
situational awareness reports, and AI-powered daily summary generation.

## Deliverables Completed

### 1. Activity Tracking (`src/gaius/core/activity.py`)

**ActivityTracker class:**
- PostgreSQL-backed event logging with memory fallback
- Event types: query, domain_change, swarm_run, tda_compute, kb_create, startup
- Query methods: get_today(), get_yesterday(), get_this_week()
- ActivitySummary dataclass with markdown rendering

**Database schema:**
```sql
CREATE TABLE activity_events (
    event_type activity_type NOT NULL,
    profile_name TEXT,
    domain TEXT,
    details JSONB,
    created_at TIMESTAMPTZ
);
```

### 2. Situational Awareness (`src/gaius/awareness/`)

**SituationalAwareness class:**
- Time horizons: emphasis, tactical, strategic, secular
- KB scanning for recent entries
- Vector store metrics
- LLM-generated insights (optional)

**SituationalReport dataclass:**
- to_markdown() for full report
- to_compact() for status bar

**Configuration (HOCON):**
```hocon
awareness {
  emphasis_hours = 24
  default_horizon_days = 7
  strategic_horizon_days = 90
  secular_horizon_days = 365
}
```

### 3. Daily Summary Agent (`src/gaius/agents/daily_summary.py`)

**DailySummaryAgent class:**
- Combines activity data + KB entries
- LLM synthesis for overview and insights
- Generates Zettelkasten-format markdown notes
- Saves to database and optionally to KB scratch/

**DailySummaryNote dataclass:**
- Summary date and profile
- Activity metrics (queries, swarm runs, tokens)
- Key entries list
- AI-generated insights and focus recommendations

### 4. App Integration

**New commands:**
- `/summary` - Generate and show daily summary
- `/activity` - Show recent activity log

**Startup behavior:**
- Shows situational awareness report on app start
- Logs startup event with profile and domain
- Configurable via `startup.show_situational`

**Activity tracking hooks:**
- Domain changes logged
- Swarm runs logged with token counts
- Commands can be tracked (extensible)

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `src/gaius/core/activity.py` | NEW | Activity tracking module |
| `src/gaius/awareness/__init__.py` | NEW | Awareness package init |
| `src/gaius/awareness/situational.py` | NEW | Situational awareness reports |
| `src/gaius/agents/daily_summary.py` | NEW | Daily summary agent |
| `db/migrations/20251130000005_activity_tracking.sql` | NEW | Activity DB schema |
| `src/gaius/core/__init__.py` | Modified | Export activity tracking |
| `src/gaius/agents/__init__.py` | Modified | Export daily summary |
| `src/gaius/app.py` | Modified | Integrate M5 features |

## Usage

```bash
# App shows situational awareness on startup automatically

# Generate daily summary
/summary

# View activity log
/activity

# Change domain (triggers activity logging)
/domain quantum computing
```

## Test Results

```
Activity Tracking:
  - Event logging: PASSED
  - Summary queries: PASSED
  - Recent events: PASSED

Situational Awareness:
  - Report generation: PASSED
  - KB scanning: PASSED (385 entries)
  - Vector store query: PASSED (1464 vectors)

Daily Summary Agent:
  - Activity integration: PASSED
  - LLM synthesis: PASSED
  - Markdown generation: PASSED
```

## Architecture

```
App Startup
    │
    ▼
log_activity(STARTUP)
    │
    ▼
generate_startup_report()
    │
    ├─────────────────────────┐
    ▼                         ▼
ActivityTracker          SituationalAwareness
    │                         │
    ├── get_today()           ├── _get_recent_entries()
    ├── get_yesterday()       ├── _count_kb_entries()
    └── get_this_week()       └── _count_vector_store()
                                  │
                                  ▼
                          SituationalReport
                                  │
                                  ▼
                          ContentPanel.show_file()
```

## Configuration Reference

```hocon
gaius {
  awareness {
    emphasis_hours = 24        # Recent activity window
    default_horizon_days = 7   # Tactical planning
    strategic_horizon_days = 90
    secular_horizon_days = 365
  }

  startup {
    commands = []              # Commands to run on start
    show_situational = true    # Show awareness report
  }
}
```

## Next Steps

With M5 complete, the Gaius v1.0 roadmap milestones (M1-M5) are finished:

- M1: File Navigation + Wikilinks
- M2: Think mode + enterApp + Telemetry
- M3: Real Grid Data + TDA
- M4: DeepAgents Swarm
- M5: Situational Awareness + Daily Summary

Future enhancements:
- Scheduled daily summary generation via pg_cron
- Profile-specific awareness configurations
- Integration with external calendar/event sources
- Trend analysis across multiple days
