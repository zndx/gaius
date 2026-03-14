# Research Workflow

The research workflow takes a topic from initial exploration through to a published collection of enriched cards. This is the primary content pipeline in Gaius.

## Overview

```
Topic definition --> Article curation --> Card creation --> Enrichment --> Publishing
```

Each step builds on the previous one. The workflow can be driven manually through the CLI, or orchestrated by Claude Code via MCP tools.

## Step 1: Define the Topic

Create or select an article definition with keywords and news queries that guide content discovery:

```bash
# List existing articles
uv run gaius-cli --cmd "/article list" --format json

# Create a new article with topic keywords
uv run gaius-cli --cmd "/article new" --format json
```

Articles need `keywords` and/or `news_queries` in their frontmatter for the Brave fetcher to find relevant sources. Without these, curation will fail fast with `#ACF.00000013.NOHINTS`.

## Step 2: Curate Articles

Run the article curation flow to fetch and process relevant content:

```bash
uv run gaius-cli --cmd "/article curate" --format json
```

The curation flow:
1. Searches the web using configured keywords and news queries
2. Fetches and extracts content from discovered URLs
3. Evaluates relevance against a selection rubric
4. Creates cards from qualifying articles (~20 cards per run, ~2 minutes)

The selection rubric includes a `curation_readiness` gate that prevents selecting articles whose metadata is incomplete.

## Step 3: Enrich Cards

Cards are created with basic metadata. Enrichment adds embeddings, summaries, and topology features:

```bash
# Check enrichment status
uv run gaius-cli --cmd "/collection list cards" --format json

# Generate summaries for cards that need them
uv run gaius-cli --cmd "/collection generate summaries" --format json
```

Card publishing is gated on enrichment completeness -- cards without sufficient enrichment cannot be published.

## Step 4: Render Visualizations

Each card gets a deterministic visualization rendered by the LuxCore engine:

```bash
uv run gaius-cli --cmd "/render cards" --format json
```

The grammar engine generates a unique visual based on the card's topology features, seeded by `hash(card_id)` for deterministic output. Two variants are produced: `display` (1400x300) and `og` (1200x630 for social sharing).

## Step 5: Publish Collection

Publish the completed cards to a collection:

```bash
# Create or select a collection
uv run gaius-cli --cmd "/collection create" --format json

# Add cards to the collection
uv run gaius-cli --cmd "/collection add card" --format json

# Publish
uv run gaius-cli --cmd "/collection publish cards" --format json
```

## MCP-Driven Research

When using Claude Code with MCP tools, the entire workflow can be conversational:

> "Research the topic of topological data analysis in financial risk. Curate articles, enrich the cards, and publish a collection."

Claude Code will call `article_new`, `article_curate`, `collection_generate_summaries`, and `collection_publish_cards` in sequence, reporting progress at each step.

## Monitoring Collection Balance

The `pending_cards` metric is the most effective signal for collection diversity. Monitor it to ensure the collection is not over-weighted toward a single source or topic.
