# arXiv RSS-first curation (2026-09-14)

End-stage content objective: unpublished articles still get arXiv sources,
drafts, cards, publish — without exceeding API norms.

## Norms (verified)

- ToU: GET `export.arxiv.org/api/query`, 1 req / 3s, never POST.
- `"Rate exceeded."` 429 with no Retry-After is capacity; staff: try later.
  15 min quiet then one `id_list` GET → 200.
- `rss.arxiv.org/rss/cs.LG` → 200 Fastly HIT. Weekend `skipDays` Sat/Sun
  yields an empty channel (do not clobber Friday's cache).

## Workflow

1. RSS per `arxiv_categories` (≤3), 6h TTL, serialized GET.
2. Rank by keywords locally; fill remainder with recent category papers.
3. Empty weekend RSS → 7-day stale cache, not a search burst.
4. Search API only if RSS+stale empty and circuit closed (one capped GET).
5. Headerless 429 → 15 min circuit, no retries.
6. `gaius_article_curate` was paused during the 429; unpause after this lands
   so 09:07 UTC uses RSS-first.
