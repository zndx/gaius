# pg_cron Jobs

Gaius uses the `pg_cron` extension for scheduled database maintenance. Jobs are defined in SQL migrations and run inside PostgreSQL without external schedulers.

## Core Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| `check-due-fetches` | Every 15 min | Check `feed_sources` for overdue fetches and create `fetch_jobs` records |
| `cleanup-fetch-jobs` | Sunday 3 AM | Remove old fetch job records (keep last 100 per source) |
| `archive-stale-content` | 1st of month, 4 AM | Mark content items older than 90 days as archived |

## How It Works

The `schedule_due_fetches()` function checks each active `feed_source` against its configured `fetch_interval_minutes`. When a source is due, it creates a `fetch_jobs` record with `status = 'scheduled'`. Python workers poll this table and execute the actual fetch.

```sql
-- Example: schedule a fetch for a specific source
SELECT schedule_fetch('arxiv-cs-ai');

-- Check all due sources
SELECT * FROM schedule_due_fetches();
```

## Additional Scheduled Tasks

Beyond the core jobs, several migrations add domain-specific cron schedules:

| Migration | Job | Schedule |
|-----------|-----|----------|
| `20251214000001_evolution_periodic_tasks` | Evolution cycle triggers | Periodic |
| `20251223000001_theta_consolidation_cron` | Theta memory consolidation | Periodic |
| `20251228000002_triage_cron_jobs` | Content triage | Periodic |
| `20260202200000_landing_page_cron` | Landing page card publishing | Periodic |
| `20260203100000_scheduled_task_notify` | `NOTIFY` on scheduled task changes | Event-driven |
| `20260816000001_board_reindex_cron` | Continuous 19×19 board reindex | Every minute |
| `20260817000001_weekly_signals_summary_cron` | Weekly Signals Summary (S2S remotes) | Monday 15:00 UTC |

The `scheduled_task_notify` migration uses PostgreSQL `LISTEN`/`NOTIFY` to wake the engine watchdog when tasks are due, avoiding polling overhead.

## Monitoring

The `v_source_status` view provides at-a-glance health for all feed sources:

```sql
SELECT name, status, total_items, pending_jobs FROM v_source_status;
```

Status values: `ok`, `overdue`, `never` (never fetched).

## Source

Core jobs: `db/migrations/20251130000003_pg_cron_jobs.sql`. Additional schedules are spread across domain-specific migrations in `db/migrations/`.
