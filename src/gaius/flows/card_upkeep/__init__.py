"""CardUpkeepFlow - Publish cards from article .base files to Cloudflare KV.

This flow implements a 7-step pipeline that publishes cards:
1. start: Scan .base files for references needing cards
2. process_article: Create cards per article (foreach parallel)
3. join_articles: Merge parallel results
4. publish_batch: Publish pending cards
5. sync_to_kv: Push to Cloudflare KV
6. update_base_files: Update card_status in .base files
7. end: Emit lineage, report summary

Usage:
    # Via Metaflow CLI
    python -m gaius.flows.card_upkeep.flow run

    # Process specific article
    python -m gaius.flows.card_upkeep.flow run --article ai-keiretsu

    # Dry run
    python -m gaius.flows.card_upkeep.flow run --dry_run True
"""

from gaius.flows.card_upkeep.flow import CardUpkeepFlow
from gaius.flows.card_upkeep.common import ArticleProcessResult

__all__ = ["CardUpkeepFlow", "ArticleProcessResult"]
