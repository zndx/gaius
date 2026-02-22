# End-to-End Publish Quality in ArticleCurationFlow

## Summary

Made ArticleCurationFlow a complete pipeline — curate, create cards, publish a batch, sync all KV stores — so each run produces visible, quality-validated content on gaius.zndx.org.

## Changes

### `src/gaius/flows/article_curation/flow.py`

1. **Fixed 3 fail-fast violations in `_generate_brief_summaries()`**:
   - XAI backend not available: `return {}` → `raise RuntimeError(#ACF.00000018.XAINOTAVAIL)`
   - API call failed: `return {}` → `raise RuntimeError(#ACF.00000019.BRIEFSUMFAIL)`
   - Parse error: bare `except Exception` → `except json.JSONDecodeError` with `#ACF.00000020.BRIEFSUMPARSE`
   - Also fixed "no JSON found" case (missing else branch)

2. **Added URL validation quality gate** (`_validate_source_url()`):
   - Rejects empty URLs, placeholder patterns (`2501.00000`, `example.com`), malformed URLs
   - Guru code: `#ACF.00000021.BADURL`
   - Called before `add_card()` in `_create_cards_async()`

3. **Added `publish_batch` step** (step 9, between `create_cards` and `end`):
   - Calls `publish_cards()`, `sync_to_kv()`, `sync_collection_to_kv()`, `sync_collections_index_to_kv()`
   - All operations fail-fast
   - Updated flow docstring (8-step → 9-step) and progress events

### `src/gaius/flows/article_curation/progress.py`

- Added `publish` step (number 9, progress 0.95)
- Added `emit_publish()` function
- Bumped `TOTAL_STEPS` from 9 to 10

### `src/gaius/engine/services/collection_service.py`

1. **Fixed `publish_and_sync()` fail-fast**: Removed try/except that swallowed `CollectionError` during KV sync
2. **Auto-activate collection on first publish**: After publishing cards, collections with `status='draft'` are upgraded to `status='active'`
3. **Fixed SQL bug in `publish_cards()`**: Nested window function (`ROW_NUMBER() OVER (ORDER BY ROW_NUMBER() OVER (...))`) was invalid PostgreSQL — replaced with the simpler rank_in_group approach

## Data Operations

1. Archived 1 fake test card (`source_url LIKE '%2501.00000%'`)
2. Published all 60 pending cards across 3 collections (max 10 per batch, 6 rounds)
3. Auto-activated 2 draft collections (cyber-physical-systems, ai-keiretsu)
4. Synced all KV stores: landing page (34 cards), 3 collection pages, collections index

## Final State

| Collection | Status | Published Cards |
|------------|--------|----------------|
| ai-reasoning-agents | active (featured) | 34 |
| cyber-physical-systems | active | 20 |
| ai-keiretsu | active | 20 |
| gaius-content-curation | draft | 0 |

## New Guru Codes

| Code | Description |
|------|-------------|
| `#ACF.00000018.XAINOTAVAIL` | XAI backend unavailable for brief summaries |
| `#ACF.00000019.BRIEFSUMFAIL` | Brief summary API call failed |
| `#ACF.00000020.BRIEFSUMPARSE` | Brief summary response parse error |
| `#ACF.00000021.BADURL` | Invalid or placeholder source URL |
