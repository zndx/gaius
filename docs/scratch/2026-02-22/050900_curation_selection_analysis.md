# Article Curation Selection Analysis

**Date**: 2026-02-22
**Runs**: 3 consecutive (run IDs 3, 5, 6)
**Model**: Devstral-24B (instruct endpoint, TP=4)

## Selection Results

| Round | Selected | Confidence | Reasoning |
|-------|----------|------------|-----------|
| 1 | ai-reasoning-agents | 0.85 | New article, 0 pending cards |
| 2 | cyber-physical-systems | 0.90 | 0 pending cards (ai-reasoning had 20) |
| 3 | ai-keiretsu | 0.90 | 0 pending cards (CPS and ai-reasoning both had 20) |

## Candidate State Per Round

### Round 1
| Article | ZK Notes | Pending Cards | Total Cards | Selected |
|---------|----------|---------------|-------------|----------|
| ai-keiretsu | 39 | 0 | 0 | |
| gaius-content-curation | 6 | 0 | 0 | |
| cyber-physical-systems | 1 | 0 | 0 | |
| ai-reasoning-agents | 1 | 0 | 0 | Y |

### Round 2
| Article | ZK Notes | Pending Cards | Total Cards | Selected |
|---------|----------|---------------|-------------|----------|
| ai-keiretsu | 41 | 0 | 0 | |
| ai-reasoning-agents | 1 | 20 | 20 | |
| gaius-content-curation | 6 | 0 | 0 | |
| cyber-physical-systems | 1 | 0 | 0 | Y |

### Round 3
| Article | ZK Notes | Pending Cards | Total Cards | Selected |
|---------|----------|---------------|-------------|----------|
| cyber-physical-systems | 1 | 20 | 20 | |
| ai-keiretsu | 42 | 0 | 0 | Y |
| ai-reasoning-agents | 1 | 20 | 20 | |
| gaius-content-curation | 6 | 0 | 0 | |

## Observations

### What Works

1. **Collection Balance is effective**: The pending_cards signal correctly deprioritizes recently-curated articles. After round 1 created 20 cards for ai-reasoning-agents, rounds 2 and 3 correctly avoided it.

2. **Near-perfect round-robin**: 3 of 4 unique articles selected across 3 runs. This demonstrates the rubric naturally distributes attention.

3. **Consistent confidence**: All selections at 0.85-0.90 suggests the model is confident in its choices rather than randomly picking.

### Issues Found

1. **gaius-content-curation never selected**: Despite having 0 pending cards in all 3 rounds, this article was skipped. Possible causes:
   - The "Gaius" self-referential title may bias the model against it
   - 6 zk notes is a middle ground that doesn't trigger novelty or depth heuristics
   - A 4th round would likely select it (only article with 0 pending cards remaining)

2. **Missing keywords caused hard failure**: `cyber-physical-systems` had empty keywords/news_queries, causing Brave fetcher to fail-fast with `#ACF.00000013.NOHINTS`. Fixed by populating frontmatter, but the selection rubric should have prevented selecting articles with empty metadata.

3. **Curation readiness gap**: Added `curation_readiness` field to candidate text and selection criteria to prevent selecting articles that can't complete the pipeline.

## Rubric Re-weighting Recommendations

### Current Weights (all equal)
The prompt says "weighted equally" for all criteria. Based on data:

### Recommended Changes

1. **Curation Readiness**: Gate (not weighted) - MUST be "ready" to be eligible. Already implemented.

2. **Collection Balance**: Keep as highest-priority weighted criterion. The data shows it's the single most effective signal for diversity.

3. **Recency Fairness**: Working implicitly through pending_cards. Consider adding explicit `last_curated_at` tracking so the model can see temporal patterns beyond just card counts.

4. **Timeliness/Novelty/Audience Fit/Source Quality**: These are fine as secondary criteria for breaking ties between equally-balanced candidates. No re-weighting needed.

### No Arbitrary Values Needed
The current rubric is data-driven through card counts, not arbitrary weights. The collection balance signal naturally adapts:
- After curation: +20 pending cards = strong deprioritization
- After cards are published: pending count drops = article becomes eligible again
- This creates a self-regulating feedback loop

## Technical Fixes Applied

1. **gRPC timeout**: Increased inference timeout from 30s to 120s default in `SchedulerProxy.complete()`. The 24B model with cot_reflection takes 15-20s per selection.

2. **Curation readiness**: Added `has_keywords`, `has_queries`, and readiness status to candidate text in selection prompt.

3. **cyber-physical-systems keywords**: Populated empty frontmatter with `cs.SY`, `cs.RO`, `cs.AI`, `eess.SY` categories and relevant keywords.

## Pipeline Timing (per run)

| Step | Duration |
|------|----------|
| start (discover candidates) | ~5s |
| grok_research_summary | ~17s |
| select_article | ~20s |
| acquire_external (3 fetchers parallel) | ~10s |
| update_manifest | ~3s |
| sync_grok_collection (20 docs) | ~17s |
| create_draft (Grok API) | ~20s |
| create_base (Grok API) | ~17s |
| create_cards | ~3s |
| **Total** | **~2 min** |
