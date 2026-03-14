# Collection Pipeline Integrity — All Stores in Sync

**Date**: 2026-02-21 20:31
**Branch**: `feature/bases-feature-store`

## Summary

Completed the 8-step plan to eliminate silent degradation across the collection pipeline and bring all data stores (PostgreSQL, Iceberg HX, KB disk, Grok Collections) into full sync.

## Changes

### Fail-Fast Fixes (Steps 1-3)

1. **`src/gaius/flows/article_curation/flow.py`** — Removed try/except around `_update_grok_collection_id_in_db()`. If DB persistence fails after Grok collection creation, the operation now fails immediately.

2. **`src/gaius/mcp_server.py`** — Fixed `collection_generate_summaries` MCP tool to not mask failures. Both frontier and open_weights summary generation must succeed, or the tool reports failure.

3. **`src/gaius/hx/tables.py`** — Replaced 4 instances of bare `except Exception` with `except NoSuchTableError`. Real errors (connection failure, auth) now propagate instead of being silently swallowed.

### New Capabilities (Steps 4-7)

4. **`src/gaius/engine/services/collection_service.py`** — Added `add_source()` method for creating provenance records in `collections.sources`. Uses `asyncpg.Range` for INT4RANGE column, idempotent via `ON CONFLICT DO NOTHING`.

5. **`src/gaius/engine/services/collection_service.py`** — Extended `add_card()` with `source_date`, `kb_path`, `zettle_slug` parameters.

6. **`src/gaius/flows/article_curation/flow.py`** — Updated `_create_cards_async()` to:
   - Pass `zettle_slug` and `kb_path` to `add_card()`
   - Create Source records via `add_source()` for each card (fail-fast)

7. **`src/gaius/engine/services/collection_service.py`** — Added standalone `sync_collection_to_grok()` method that reads source files from KB disk, creates/finds Grok collection via xai-sdk, uploads documents, and persists `grok_collection_id`.

### Backfill (Step 8)

8. **`scripts/backfill_sources.py`** — One-time migration script that:
   - Created 15 source files on disk (`build/dev/current/articles/ai-reasoning-agents/sources/`)
   - Inserted 15 Source records in `collections.sources`
   - Updated all 15 cards with `zettle_slug` and `kb_path`
   - Updated article `sources_count = 15`
   - Synced to Grok Collections API (`collection_77837df5-2e7f-4dd4-b804-60a304b806bb`)

## Verification

All 5 verification checks pass:

| Check | Result |
|-------|--------|
| All 15 cards have source records | Pass |
| All 15 cards have zettle_slug + kb_path | Pass |
| Grok collection exists for featured collection | Pass |
| 15 source files on disk | Pass |
| HX records match PG summaries (2 records) | Pass |
| Article sources_count = 15 | Pass |

## Data State

| Store | Records | Status |
|-------|---------|--------|
| PostgreSQL cards | 15 published | All with zettle_slug, kb_path |
| PostgreSQL sources | 15 | Linked to cards |
| PostgreSQL summaries | 2 (frontier + open_weights) | Both with hx_generation_id |
| Iceberg HX generations | 2 | Matching PG summaries |
| KB disk source files | 15 | In `ai-reasoning-agents/sources/` |
| Grok Collections | 1 collection, 15 documents | `collection_77837df5-...` |
