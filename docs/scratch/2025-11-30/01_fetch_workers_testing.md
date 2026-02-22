# Fetch Workers End-to-End Testing

**Date**: 2025-11-30
**Session**: Sprint 1 Testing & Bug Fixes

## Summary

Completed end-to-end testing of the fetch workers module. Fixed several issues discovered during testing.

## Issues Fixed

### 1. PostgreSQL TCP Listening
- **Problem**: asyncpg couldn't connect via TCP (port 5444)
- **Fix**: Added `listen_addresses = "127.0.0.1"` to devenv.nix postgres config
- **File**: `devenv.nix:51`

### 2. HTTP Redirect Handling
- **Problem**: httpx wasn't following 301 redirects (arXiv HTTP→HTTPS)
- **Fix**: Added `follow_redirects=True` to httpx.AsyncClient
- **File**: `src/gaius/workers/manager.py:47-48`

### 3. arXiv API URL
- **Problem**: Using HTTP instead of HTTPS for arXiv API
- **Fix**: Changed `API_URL` from `http://export.arxiv.org` to `https://export.arxiv.org`
- **File**: `src/gaius/workers/fetchers/arxiv.py:24`

### 4. Metadata Double-JSON-Encoding
- **Problem**: Metadata stored as `"{...}"` (JSON string in JSONB) instead of `{...}` (JSONB object)
- **Cause**: `json.dumps()` called before passing to asyncpg, but asyncpg JSONB codec already encodes
- **Fix**: Removed explicit `json.dumps()` calls, let asyncpg codec handle serialization
- **File**: `src/gaius/workers/db.py` (lines 122, 143, 221)

## Working Sources

| Source | Type | Status | Items Fetched |
|--------|------|--------|---------------|
| arxiv_cs_dc | arxiv | Working | 100 papers |
| temporal_blog | rss | Working | 50 posts |

## Inactive Sources (Feed URLs Unavailable)

| Source | Issue | Action |
|--------|-------|--------|
| legiblenews | 404 Not Found | Marked inactive, need alternative |
| cloudera_blog | 301 to non-RSS page | Marked inactive |
| databricks_blog | 404 Not Found | Marked inactive |

## Pending Implementation

Sources requiring additional fetchers (Sprint 2):
- `biorxiv_synbio` - bioRxiv API fetcher
- `philpapers` - PhilPapers scraper/API
- `philevents` - PhilEvents API
- `cloudera_docs` - Documentation sitemap crawler
- `crusoe_blog` - Web scraper

## Test Commands

```bash
# Check worker status
uv run gaius-worker --status

# Schedule a job manually
psql -h 127.0.0.1 -p 5444 -d zndx_gaius -c "SELECT schedule_fetch('arxiv_cs_dc');"

# Run worker once (process all pending jobs)
uv run gaius-worker --once -v

# Verify metadata is proper JSONB
psql -h 127.0.0.1 -p 5444 -d zndx_gaius -c \
  "SELECT jsonb_typeof(metadata), metadata->>'arxiv_id' FROM content_items LIMIT 1;"
```

## pg_cron Jobs

Scheduled jobs running automatically:
- `check-due-fetches`: Every 15 minutes - schedules jobs for due sources
- `cleanup-fetch-jobs`: Weekly (Sunday 3 AM) - keeps last 100 jobs per source
- `archive-stale-content`: Monthly (1st, 4 AM) - marks old unprocessed content
