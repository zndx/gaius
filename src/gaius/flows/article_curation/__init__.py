"""Article Curation Flow - Metaflow pipeline for article research and publication.

This module implements a 9-step Metaflow pipeline for article curation:
1. Find unpublished articles in KB
2. Research Phase - gather KB context
3. Grok summary - synthesize research into zettelkasten
4. Article selection - optillm selects article (Atropos-RL traces)
5. ACP acquisition - fetch external sources only
6. Update manifest - write YAML with sources
7. Grok sync - push to X/Grok Collections API
8. Draft creation - generate draft, archive to hx/
9. Base file - BFO-grounded with ref_start/ref_end offsets

Usage:
    # Run via Metaflow CLI
    python -m metaflow.cli run ArticleCurationFlow --article ai-reasoning-weekly

    # Via Gaius CLI
    uv run gaius-cli --cmd "/article curate ai-reasoning-weekly"
"""

from gaius.flows.article_curation.flow import ArticleCurationFlow
from gaius.flows.article_curation.common import (
    ArticleCandidate,
    ArticleStatus,
    AcquiredSource,
    DraftHistoryEntry,
    ArticleReference,
)

__all__ = [
    "ArticleCurationFlow",
    "ArticleCandidate",
    "ArticleStatus",
    "AcquiredSource",
    "DraftHistoryEntry",
    "ArticleReference",
]
