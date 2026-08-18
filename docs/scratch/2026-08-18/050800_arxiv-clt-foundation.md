# ArXiv / publish / CLT foundation — 2026-08-18 05:08 UTC

Is there a live summarization workload we can hang CLT on?

## Yes: inflow. No: publish. No: agent thought.

**Ingest is live.** `feed_check` at 04:24 UTC scheduled `arxiv_cs_dc`
and `biorxiv_synbio`. Last 36 h:

| source | items | llm ≥50 | processed to KB |
|---|---:|---:|---:|
| arxiv_cs_dc | 133 | 100 | 100 |
| temporal_blog | 50 | 50 | 50 |
| biorxiv_synbio | 18 | 10 | 10 |
| databricks_blog | 10 | 10 | 10 |

`content_items`: 2131 total, 211 today, 323 / 7 d. 282 have `kb_path`
this week. Notes under `build/dev/current/content/arxiv_cs_dc/2026-08-17/`
are the **author abstract**, scored and filed — not an agent rewrite.
41 items still wait `llm_triage` (33 ArXiv, 8 bioRxiv).

**Publish to gaius.zndx.org is frozen.** Featured collection
`ai-reasoning-agents`. Public cards all mid-March. `collections.cards`:
212 published (max 2026-03-12), 20 pending (all 2026-03-11), last
`published_at` 14 Mar. `publish_cards` runs four slots/day,
`kv_sync_success=true`, `published_count=0`. `article_curate` daily
09:00 fails: `#YK.00000005.DISK` (root 17 Gi free / 99 %; floor 32 Gi).

**Agent thought is empty.** `cognition_cycle` last night:
`thoughts_generated=0`, `tokens_out=0`. 04:43: no handler.
`cognition_thoughts` latest row 2026-08-15. Ambient: 258 cycles, 0
tasks since 15 Aug.

**Summarization stage is a no-op.** `content_items.summarized_at` is
0 forever. Yesterday’s `content_summarization`:
`items_processed=0`. `content_processing` is idle
(`no_items_pending`) because it only files already-triaged abstracts.

**FMP** is a third inflow: `prospects_check` 17 Aug saw 59 new
filings. Not on the landing yet.

**CLT cannot run.** `clt_status` /
`HF_HUB_ENABLE_HF_TRANSFER` import fail. Qdrant
`gaius_clt_latent_thoughts` = 0 points.

## What to hang the visualization on

1. Fix CLT import; load light on parked GPU 4.
2. Batch-probe last-week abstracts (title+summary) → `FeatureTape`
   rows keyed by `content_items.id` / `fetched_at` (stream=`inflow`).
3. When cognition or a real summarize pass writes text, probe that
   as stream=`thought` with `source_id` back to the inflow item.
4. ELK table = windowed feature counts (1 m / 1 h / 1 d / 7 d).
5. Do not restart `article_curate` or KV publish until disk is
   under the YK floor — that path is not the CLT corpus.

The 27B Completes on 0–3 are not this pipeline.
