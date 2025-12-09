# Sprint 2: Additional Fetchers

**Date**: 2025-11-30
**Session**: Fetcher Implementation

## Summary

Implemented 4 new fetchers to expand content sourcing capabilities.

## New Fetchers

### 1. Brave Fetcher (`brave.py`)
- Uses Brave Search API for sources without RSS feeds
- Brave explicitly permits AI pipeline usage
- Configurable queries, topics, and freshness filters
- File: `src/gaius/workers/fetchers/brave.py`

### 2. bioRxiv Fetcher (`biorxiv.py`)
- Uses bioRxiv API (`api.biorxiv.org`)
- Fetches preprints by date range
- Keyword filtering in title/abstract/category
- File: `src/gaius/workers/fetchers/biorxiv.py`

### 3. Docs Fetcher (`docs.py`)
- Crawls documentation sites via sitemap.xml
- Supports priority paths and exclusion patterns
- Handles sitemap indexes (nested sitemaps)
- File: `src/gaius/workers/fetchers/docs.py`

### 4. PhilPapers (via Brave)
- Updated philpapers source to use Brave fetcher
- Searches for philosophy topics: epistemology, consciousness, free will
- No dedicated fetcher needed - Brave handles it

## Source Type Updates

Added `brave` to SourceType enum:
```sql
ALTER TYPE source_type ADD VALUE 'brave';
```

Updated sources to use new types:
- `legiblenews` → brave (was rss, feed 404)
- `philpapers` → brave (was philpapers, no API)

## Current Fetch Results

| Source | Type | Items |
|--------|------|-------|
| arxiv_cs_dc | arxiv | 100 |
| biorxiv_synbio | biorxiv | 44 |
| cloudera_docs | docs | 50 |
| databricks_blog | rss | 10 |
| philpapers | brave | 34 |
| temporal_blog | rss | 50 |
| **Total** | | **288** |

## Inactive/Pending Sources

| Source | Status | Notes |
|--------|--------|-------|
| cloudera_blog | Inactive | RSS feed redirects to HTML |
| crusoe_blog | Pending | Needs scraper fetcher |
| legiblenews | Needs work | Query refinement needed |
| philevents | Pending | Needs API fetcher |

## Files Created

```
src/gaius/workers/fetchers/
├── brave.py      # Brave Search API fetcher
├── biorxiv.py    # bioRxiv API fetcher
├── docs.py       # Sitemap-based docs crawler
└── __init__.py   # Updated with new imports
```

## Key Learnings

1. **Brave Search API**: The `site:` prefix doesn't work reliably in API queries. Better to include domain in query text.

2. **bioRxiv API**: Returns all papers in date range, filtering must be done client-side. Categories don't always match collection names.

3. **Sitemaps**: Many sites use sitemap indexes (sitemaps of sitemaps). Need to handle both formats.

## Next Steps

- Implement scraper fetcher for sites without RSS/API/sitemap
- Add PhilEvents API fetcher
- Refine legiblenews queries for quality temporal grounding
- Add rate limiting between fetches
- Implement content processing pipeline (KB integration)
