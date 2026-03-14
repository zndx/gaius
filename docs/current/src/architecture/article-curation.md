# Article Curation

The ArticleCurationFlow is an 11-step Metaflow pipeline that automates the discovery, research, drafting, and publication of articles. It is the primary content production mechanism in Gaius.

## Pipeline Overview

```
start ──> grok_research_summary ──> select_article ──> acquire_external
   ──> update_manifest ──> create_draft ──> create_base ──> create_cards
   ──> enrich_cards ──> publish_batch ──> end
```

Each run produces approximately 20 cards in under 2 minutes.

## Article Discovery

Articles live at `current/articles/{slug}/` in the knowledge base. Each article directory contains a markdown file with YAML frontmatter that must include `keywords` and/or `news_queries` to guide the Brave search fetcher:

```yaml
---
title: "AI Reasoning Weekly"
keywords: ["chain-of-thought", "reasoning models", "test-time compute"]
news_queries: ["AI reasoning breakthroughs 2026"]
---
```

Empty keywords trigger a fail-fast error:

```
#ACF.00000013.NOHINTS - Article has no keywords or news_queries
  Try: Add keywords to the article frontmatter
```

## Article Selection

The selection rubric evaluates candidate articles using several signals. The `curation_readiness` gate prevents selecting articles that lack sufficient zettelkasten notes or have incomplete frontmatter. Collection balance -- specifically `pending_cards` count -- is the most effective diversity signal, steering selection toward underrepresented topics.

## External Source Acquisition

Once an article is selected, the flow fetches external sources in parallel using Brave search. Results are scored for relevance by a local LLM. Only sources exceeding the relevance threshold are retained.

## Draft Generation and Card Creation

Drafts are synthesized using Grok, drawing from the article's `zk/` zettelkasten notes. The flow does NOT search the broader KB to avoid exposing private materials in published articles.

After drafting, the flow creates a BFO-grounded `.base` file with references, then generates collection cards from those references. Cards are created with `pending` status.

## Enrichment Before Publish

Cards must be fully enriched before publication. Enrichment includes:

1. **Summary generation** -- LLM-generated card summaries
2. **Image rendering** -- Procedural visualizations via [LuxCore](./luxcore.md)

Only cards that pass both enrichment steps are published. Failed cards remain `pending` for the next run. This prevents incomplete content from appearing on the site.

## CLI Access

```bash
# Curate a specific article
uv run gaius-cli --cmd "/article curate ai-reasoning-weekly"

# List available articles
uv run gaius-cli --cmd "/article list"

# Check article status
uv run gaius-cli --cmd "/article status"
```

## Fail-Fast Guarantees

The flow fails immediately if required services are unavailable. No fallbacks or placeholder content is generated. Key guru meditation codes:

| Code | Meaning |
|------|---------|
| `#ACF.00000013.NOHINTS` | Article missing keywords/news_queries |
| `#FL.00001.DOCLING_FAIL` | Document conversion failed |
| `#FL.00002.METAFLOW_DB` | Metaflow metadata DB unavailable |

## Privacy

The curation flow only uses the article's own `zk/` notes as source material. It does not search the broader knowledge base, ensuring private materials are never exposed in published articles.
