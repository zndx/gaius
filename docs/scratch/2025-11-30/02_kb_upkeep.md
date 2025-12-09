# KB Upkeep Architecture

## Overview

Automated knowledge base maintenance using pg_cron for scheduling, combining:
- **Research feeds**: arXiv, bioRxiv, PhilPapers
- **Industry sources**: Cloudera, Databricks, Temporal, Crusoe
- **Temporal grounding**: LegibleNews.com
- **Profile-based customization**: cloudera, weathership, common

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           FEED SOURCES                                    │
├───────────────┬───────────────┬───────────────┬──────────────────────────┤
│    arXiv      │   bioRxiv     │  PhilPapers   │     Industry Docs        │
│   cs.DC       │  Synth Bio    │  Philosophy   │  Cloudera, Databricks    │
└───────┬───────┴───────┬───────┴───────┬───────┴───────────┬──────────────┘
        │               │               │                   │
        └───────────────┴───────┬───────┴───────────────────┘
                                ↓
                    ┌───────────────────────┐
                    │      pg_cron          │
                    │  schedule_due_fetches │
                    │    (every 15 min)     │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │     fetch_jobs        │
                    │  (scheduled tasks)    │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │   Python Workers      │
                    │  - Poll fetch_jobs    │
                    │  - Fetch content      │
                    │  - optillm synthesis  │
                    └───────────┬───────────┘
                                ↓
        ┌───────────────────────┼───────────────────────┐
        ↓                       ↓                       ↓
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│     KB        │       │    Qdrant     │       │    MinIO      │
│  build/dev/   │       │   Vectors     │       │    PDFs       │
│  Markdown     │       │  Embeddings   │       │   Assets      │
└───────────────┘       └───────────────┘       └───────────────┘
```

## Profiles

### `common` - Shared Temporal Grounding
| Source | Type | Interval | Purpose |
|--------|------|----------|---------|
| LegibleNews | RSS | Hourly | Current events context |

### `weathership` - Research Profile
| Source | Type | Interval | Focus Areas |
|--------|------|----------|-------------|
| arXiv cs.DC | API | 6 hours | Distributed computing |
| bioRxiv | RSS | 6 hours | Synthetic biology |
| PhilPapers | Scraper | Daily | Philosophy of mind, epistemology, consciousness, free will |
| PhilEvents | API | Daily | Philosophy events/CFPs |

Philosophy topics tracked:
- Epistemology
- Philosophy of Mind
- Aesthetics
- Logic and Philosophy of Logic
- Freedom and Liberty
- Theories of Free Will
- Temporal Experience
- Consciousness

### `cloudera` - Enterprise Profile
| Source | Type | Interval | Focus Areas |
|--------|------|----------|-------------|
| Cloudera Docs | Sitemap | Weekly | CDP, ML, Data Engineering |
| Cloudera Blog | RSS | Daily | Product announcements |
| Databricks | RSS | Daily | Lakehouse, Spark |
| Temporal.io | RSS | Daily | Workflow orchestration |
| Crusoe.ai | Scraper | Daily | GPU cloud infrastructure |

## Database Schema

```
db/migrations/
├── 20251130000001_initial_schema.sql    # Tables: profiles, feed_sources, content_items
├── 20251130000002_seed_profiles_sources.sql  # Profile + source seed data
└── 20251130000003_pg_cron_jobs.sql      # Scheduled jobs + helper functions
```

### Key Tables

- `profiles` - cloudera, weathership, common
- `feed_sources` - Source configurations with fetch intervals
- `profile_sources` - Profile-source associations with weights
- `content_items` - Fetched content with metadata
- `fetch_jobs` - Job queue for Python workers

### Monitoring View

```sql
SELECT * FROM v_source_status;
-- Shows: name, type, status (ok/overdue/never), item counts, profiles
```

## pg_cron Jobs

| Job | Schedule | Function |
|-----|----------|----------|
| `check-due-fetches` | */15 * * * * | Poll sources, create fetch_jobs |
| `cleanup-fetch-jobs` | 0 3 * * 0 | Prune old job records |
| `archive-stale-content` | 0 4 1 * * | Archive 90-day old unfiled content |

## Running Migrations

```bash
# Ensure devenv services are running
devenv up

# Run migrations
dbmate up

# Check status
dbmate status
```

## Integration Points

1. **MCP Server**: Expose feed management via tools
2. **TUI**: Profile switching in Gaius interface
3. **CLI**: Manual feed triggers and status checks
4. **Embeddings**: Qdrant integration for semantic search
5. **Agentic tasks**: PhilPapers scraping may evolve into agent workflows

## Next Steps

1. [x] Create PostgreSQL schema migrations
2. [x] Define profile configurations
3. [x] Set up pg_cron jobs
4. [ ] Implement Python fetch workers
5. [ ] Add arXiv API fetcher
6. [ ] Add bioRxiv RSS parser
7. [ ] Add PhilPapers scraper (potential agentic task)
8. [ ] Integrate with MCP server tools
9. [ ] Add profile management to TUI
