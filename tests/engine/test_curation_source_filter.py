"""Reflex classifier for marketing/aggregation web results (2026-09-06).

The day the curate's web half went week-first, ten vendor listicles were
published as research briefs. These are the shapes acquisition refuses; a
primary source must never trip them.
"""

import pytest

from gaius.flows.article_curation.common import looks_like_marketing

MARKETING = [
    ("https://answerthis.io/blog/best-ai-research-assistant-tools", "Top 10 AI Tools for Researchers in 2026 | AnswerThis"),
    ("https://agentic.ai/best/research-deep-analysis", "11 Best AI Research & Analysis Agents in 2026 — Agentic.ai"),
    ("https://www.lindy.ai/blog/ai-agents-for-business", "13 AI Agents for Business in 2026 for Every Kind of Work | Lindy"),
    ("https://peoplemanagingpeople.com/tools/best-ai-knowledge-base-tools/", "10 Best AI Knowledge Base Tools Reviewed in 2026"),
    ("https://buffer.com/resources/ai-social-media-content-creation-tools/", "17 AI Tools for Social Media Content Creation in 2026"),
    ("https://www.elsevier.com/products/scopus/scopus-ai", "Scopus with AI | Elsevier"),
    ("https://vendor.example/pricing", "Plans and pricing"),
    ("https://vendor.example/compare/x-vs-y", "X vs Y: which is better"),
    ("https://arxiv.org/list/cs/recent?skip=884&show=2000", "cs recent"),
]

PRIMARY = [
    ("https://arxiv.org/abs/2609.01234", "SWE-Gate: Passing Functional Tests Is Not Enough for Agents"),
    ("https://www.nature.com/articles/s41586-026-0001", "Peer-reviewed evaluation of agentic systems"),
    ("https://github.com/VoltAgent/awesome-ai-agent-papers", "GitHub - VoltAgent/awesome-ai-agent-papers: A curated list"),
    ("https://dl.acm.org/doi/10.1145/1234567", "Measurement-Driven Sub-Network Selection for On-Premise Inference"),
    ("https://engineering.example.com/posts/how-we-shard-kv-cache", "How we shard the KV cache across eight GPUs"),
    ("https://arxiv.org/html/2605.10310v1", "Top-k routing in mixture-of-experts: a study"),
]


@pytest.mark.parametrize("url,title", MARKETING)
def test_marketing_shapes_are_refused(url: str, title: str) -> None:
    assert looks_like_marketing(url, title) is not None


@pytest.mark.parametrize("url,title", PRIMARY)
def test_primary_sources_pass(url: str, title: str) -> None:
    assert looks_like_marketing(url, title) is None
