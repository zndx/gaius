# Article-to-Card Pipeline Audit

**Date**: 2026-02-02
**Status**: Verified Working

## Pipeline Overview

```
ArticleCurationFlow → CardUpkeepFlow → CollectionService → Cloudflare KV
```

### 1. ArticleCurationFlow (`src/gaius/flows/article_curation/flow.py`)

**Purpose**: Research and curate articles from KB zettelkasten notes.

**Key Steps**:
1. `start`: Scan `current/articles/*/` for articles with `zk/` notes
2. `grok_research_summary`: Synthesize notes with Grok-4-1-fast
3. `select_article`: Choose article to advance (optillm or explicit)
4. `acquire_external`: Parallel fetch from arXiv, bioRxiv, Brave
5. `sync_grok_collection`: Sync to X/Grok Collections API
6. `create_draft`: Generate article draft with Grok
7. `create_base`: Create BFO-grounded `.base` file with:
   - `@context` JSON-LD semantic vocabulary
   - `references[]` with `ref_id`, `source_id`, `traceable_id`
   - `ref_start`/`ref_end` offsets into source document
   - `brief_summary`: LLM-generated summary of cited passage
   - `card_status`: unknown|pending|published|skipped|archived

**Output**: `{HHMMSS}_{slug}.base` file in article directory

### 2. CardUpkeepFlow (`src/gaius/flows/card_upkeep/flow.py`)

**Purpose**: Create collection cards from `.base` file references.

**Key Steps**:
1. `start`: Scan `.base` files for refs with status `unknown`/`pending`
2. `process_article`: Create cards per article (foreach parallel)
3. `join_articles`: Merge results
4. `publish_batch`: Publish N cards from pending queue
5. `sync_to_kv`: Push to Cloudflare KV
6. `update_base_files`: Update `card_status` in `.base` files

**Fail-Fast Requirements** (No fallbacks permitted):
- `#CUF.00000009.NOBRIEFSUMMARY`: Missing `brief_summary` for reference
- `#CUF.00000010.NOTITLE`: Cannot extract title from `brief_summary`
- `#CUF.00000011.NOARTICLE`: Article not registered in database
- `#CUF.00000012.NOCOLLECTION`: Article has no associated collection

**Card Content Source**: Uses `brief_summary` exclusively (line 360-378):
```python
brief_summary = getattr(ref, "brief_summary", "") or ""

if not brief_summary:
    raise RuntimeError(
        f"Missing brief_summary for {ref.ref_id}.\n"
        "  Guru Meditation: #CUF.00000009.NOBRIEFSUMMARY"
    )

card_title = _extract_title(brief_summary)  # First sentence
summary = brief_summary  # Full LLM summary
```

### 3. CollectionService (`src/gaius/engine/services/collection_service.py`)

**Purpose**: Database operations for articles, collections, and cards.

**1:1 Mapping**: Each article has exactly one associated collection
- Created atomically via `create_article_with_collection()`
- Collection uses article slug as identifier

**Publishing**: `publish_and_sync()` publishes N pending cards from featured collection

### 4. CLI Integration

**Commands**:
- `/article curate [slug]` - Run ArticleCurationFlow
- `/article cards [--publish-count=N]` - Run CardUpkeepFlow
- `/publish cards [-N count]` - Publish pending cards to KV

## Verification Results

### Current State (2026-02-02 04:28)

**Collections**:
| Collection | Total Cards | Pending | Published |
|------------|-------------|---------|-----------|
| ai-keiretsu | 20 | 17 | 3 |
| gaius-content-curation | 0 | 0 | 0 |

**Published Cards** (sample):
| Title | Source | Type |
|-------|--------|------|
| TEON generalizes the Muon optimizer... | arxiv.org/abs/2601.23261 | arxiv |
| IRL-DAL proposes an inverse RL framework... | arxiv.org/abs/2601.23266 | arxiv |
| BRACE introduces Bayesian Reinforcement... | arxiv.org/abs/2601.23285 | arxiv |

**`.base` File Status**:
- 20 references total
- 3 with `card_status: published`
- 17 with `card_status: published` (updated after publish)
- All have `brief_summary` field populated

## Architecture Patterns

### Fail-Fast (MANDATORY)
- No fallbacks to excerpt if `brief_summary` missing
- RuntimeError with Guru Meditation codes
- OTel events for ops visibility

### Data Flow
```
.base file (YAML frontmatter)
    ├── references[].brief_summary (LLM summary)
    └── references[].traceable_id → source_url
            │
            ▼
collections.cards (Postgres)
    ├── title (first sentence of brief_summary)
    ├── summary (full brief_summary)
    └── source_url (from traceable_id)
            │
            ▼
Cloudflare KV → gaius.zndx.org landing page
```

### Status State Machine
```
unknown → pending → published
    │         │
    └─────────┴──→ skipped
                   archived
```

## Future Improvements

1. **Citation Offsets**: Currently most refs have `ref_start: -1, ref_end: -1`
   - Grok citation provenance extraction needs improvement
   - Should point to specific passage in source document

2. **OTel Metrics**: Track citation specificity ratio
   - `article_curation.citation.offset.specific` (has real offsets)
   - `article_curation.citation.offset.general` (whole source)

3. **Card Deduplication**: Currently no check for duplicate source URLs
   - Could merge cards from same source across articles
