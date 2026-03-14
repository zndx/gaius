"""Create a fresh collection with cards for E2E verification.

Uses create_article_with_collection to satisfy the article_id NOT NULL
constraint on cards (enforced by 20260202000002 migration).
"""

import asyncio
import json

import asyncpg

from gaius.core.config import get_database_url
from gaius.engine.services.collection_service import CollectionService


CARDS_DATA = [
    ("Scaling Multiagent Systems with Process Rewards",
     "Investigates how process-based rewards can improve coordination and performance in large-scale multi-agent systems.",
     "https://arxiv.org/abs/2501.00000", "arxiv"),
    ("Multi-Agent Systems Should be Treated as Principal-Agent Problems",
     "Argues that multi-agent AI systems exhibit principal-agent dynamics requiring economic mechanism design.",
     "https://arxiv.org/abs/2501.00001", "arxiv"),
    ("MonoScale: Scaling Multi-Agent System with Monotonic Improvement",
     "Proposes a monotonic improvement guarantee for multi-agent scaling that prevents catastrophic performance drops.",
     "https://arxiv.org/abs/2501.00002", "arxiv"),
    ("End-to-end Optimization of Belief and Policy Learning in Shared Autonomy",
     "Jointly optimizes belief estimation and policy learning for shared autonomy where humans and AI collaborate.",
     "https://arxiv.org/abs/2501.00003", "arxiv"),
    ("IRL-DAL: Safe Trajectory Planning via Energy-Guided Diffusion Models",
     "Combines inverse reinforcement learning with diffusion models for safe trajectory planning in autonomous driving.",
     "https://arxiv.org/abs/2501.00004", "arxiv"),
    ("TEON: Tensorized Orthonormalization for LLM Pre-Training",
     "Extends the Muon optimizer with tensorized orthonormalization for more efficient large language model pre-training.",
     "https://arxiv.org/abs/2501.00005", "arxiv"),
    ("Agile Reinforcement Learning through Separable Neural Architecture",
     "Introduces a separable neural architecture enabling agile adaptation in RL without catastrophic forgetting.",
     "https://arxiv.org/abs/2501.00006", "arxiv"),
    ("Learning to Execute Graph Algorithms Exactly with GNNs",
     "Demonstrates that graph neural networks can learn to execute classical graph algorithms with exact correctness.",
     "https://arxiv.org/abs/2501.00007", "arxiv"),
    ("Disentangling Multispecific Antibody Function with GNNs",
     "Applies graph neural networks to characterize multispecific antibody functional properties.",
     "https://arxiv.org/abs/2501.00008", "arxiv"),
    ("High-quality Dynamic Game Content via Small Language Models",
     "Proves that small language models can generate high-quality dynamic game content.",
     "https://arxiv.org/abs/2501.00009", "arxiv"),
    ("AI Agents for Economic Research",
     "NBER working paper exploring how AI agents transform economic research methodology.",
     "https://www.nber.org/papers/w33145", "web"),
    ("An Economy of AI Agents",
     "Examines emergent economic behaviors when AI agents interact in market-like environments.",
     "https://arxiv.org/abs/2509.01063", "web"),
    ("Agentic AI Systems in Financial Services",
     "Survey of agentic AI in financial services including model risk management and compliance.",
     "https://arxiv.org/abs/2501.10000", "web"),
    ("AgentAI: Autonomous Agents in Distributed AI for Industry 4.0",
     "Comprehensive survey on autonomous AI agents in distributed manufacturing environments.",
     "https://www.sciencedirect.com/agentai", "web"),
    ("Virtual Agent Economies",
     "Explores emergent economic dynamics in virtual environments populated by AI agents.",
     "https://arxiv.org/abs/2501.11000", "web"),
]


async def main():
    db_url = get_database_url()
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    svc = CollectionService(pool)

    slug = "ai-reasoning-agents"

    # Check if article+collection already exists
    existing_article = await svc.get_article_by_slug(slug)
    if existing_article:
        print(f"Article already exists: {existing_article.article_id}")
        article = existing_article
        collection = await svc.get_collection(existing_article.collection_id)
    else:
        # Create article+collection atomically (1:1 mapping)
        article, collection = await svc.create_article_with_collection(
            slug=slug,
            title="AI Reasoning & Multi-Agent Systems",
            kb_path="current/articles/ai-reasoning-agents",
        )
        print(f"Created article: {article.article_id}")
        print(f"Created collection: {collection.collection_id} ({collection.slug})")

    # Update collection description and activate + feature it
    await pool.execute(
        """UPDATE collections.collections
           SET status = 'active',
               featured = TRUE,
               name = 'AI Reasoning & Multi-Agent Systems',
               description = 'Curated research in AI reasoning, multi-agent systems, reinforcement learning, and autonomous decision-making. Covers frontier work from arXiv, NBER, and applied AI research.'
           WHERE collection_id = $1""",
        collection.collection_id,
    )
    # Clear other featured flags
    await pool.execute(
        """UPDATE collections.collections
           SET featured = FALSE
           WHERE collection_id != $1 AND featured = TRUE""",
        collection.collection_id,
    )
    print(f"Set collection {collection.slug} to active + featured")

    # Check existing cards
    existing_cards = await svc.list_cards(collection.collection_id)
    if existing_cards:
        print(f"Collection already has {len(existing_cards)} cards, skipping card creation")
    else:
        # Add cards with article_id
        for i, (title, summary, url, stype) in enumerate(CARDS_DATA):
            card = await svc.add_card(
                collection_id=collection.collection_id,
                title=title,
                summary=summary,
                source_url=url,
                source_type=stype,
                sequence=i + 1,
                article_id=article.article_id,
            )
            print(f"  Card {i+1}: {card.card_id} - {title[:50]}")

    # Publish all pending cards
    published = await svc.publish_cards(count=15, collection_id=collection.collection_id)
    print(f"Published {len(published)} new cards")

    # Sync landing page to KV
    try:
        sync_result = await svc.sync_to_kv()
        print(f"Landing KV sync: {json.dumps(sync_result)}")
    except Exception as e:
        print(f"Landing KV sync error: {e}")

    # Print summary
    stats = await svc.get_stats(collection.collection_id)
    print(f"\nCollection stats: {json.dumps(stats)}")
    print(f"Collection ID: {collection.collection_id}")
    print(f"Article ID: {article.article_id}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
