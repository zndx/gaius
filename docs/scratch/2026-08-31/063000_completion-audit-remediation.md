# Completion audit: every intended procedure that wasn't completing

Doctrine applied: (1) anything not completing gets remediated as priority;
(2) supervise PROGRESS, never kill work that is progressing — wall-clock
deadlines only as generous outer nets (see the progress-over-timeouts
memory and #VLLM.00000005.STALLED).

## The timeout house of cards (three independent stacks, same disease)

1. **grpc_client defaults** — 26 Scheduler call sites, one timeout; the
   30s base deadline killed every xhigh thinking completion. Fixed with a
   choke-point resolver (scaled outer net) + engine-side token-stall
   streaming supervision (`af2a178`). Cognition dark since 08-15 → lit.
2. **engine_client explicit** — `generate_card_summary` et al. passed
   `timeout=120` against 4096-token xhigh summaries (~500s worst). Every
   publish slot failed the enrichment gate (#COL.00000016.NOENRICH,
   7/8 over 48h). Resolver added to engine_client (complete_simple
   delegates); explicit 120s stripped from collection_service ×2 and the
   search flow's cot_reflection synthesis. Proof: the forever-failing
   card enriched end-to-end in 292s (open-weights + LuxCore + KV).
3. **flow-level budget** — article_curate's select step (already fixed
   flow-side: 32k budget after vLLM content=None → optillm regex 500).

## Also remediated

- **Metaflow STACKDOWN false alarm** (`87985d5`): readers pointed at
  meta.flow_runs (dead since flows moved to the platform profile
  ~07-26); rewired to the live signals-side metaflow store with honest
  end-step status derivation. Health: PASS, 173 runs/24h @90.8%.
- **Disk**: 31G free (below the 32G envelope floor, tier_settle failing)
  → 94G free (journal vacuum 2.9G + `uv cache prune --force` 21.4G past
  parked uv-run read-locks + operator file moves).
- Reboot-window transients (pg_cron "connection failed" ×8,
  board_reindex) self-cleared; YK admission bursts were boot churn.

## Follow-ups (non-blocking)

- Cerebras optional-summary model pins stale (zai-glm-4.7 archived,
  qwen-3-32b/llama-3.3-70b 404) — optional path correctly non-fatal.
- COG guru-code namespace carries long-standing collisions (1, 2, 11,
  19, 20, 24-26, 32-34 doubled) — deserves a renumbering sweep.
- search flow :324 endpoint-restore 120s is marginal vs ~2.5min model
  load (different class: lifecycle, not inference).
- Morning natural verification: publish slot (~06:30-07:00), cognition
  cron 08:43, article_curate 09:07 — all on fixed code after the final
  restart.
