"""KB-embedded Research Memory with MemRL frontmatter.

Implements intent-experience-utility (z, e, Q) triplets stored as
zettelkasten entries with YAML frontmatter for Q-values and metadata.

Two-phase retrieval:
1. Semantic similarity filter (BM25 + vector)
2. Q-value ranking (prefer high-utility memories)

Guru Meditation Codes:
- #RF.00000001.MEMRETRIEVE: Memory retrieval failed
- #RF.00000005.QUPDATE: Q-value update failed
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default Q-value for new memories
DEFAULT_Q_VALUE = 0.5

# Bellman EMA learning rate
DEFAULT_ALPHA = 0.3


@dataclass
class RewardComponents:
    """Reward signal components for research quality."""

    coherence: float = 0.0  # Logical flow, consistency (40%)
    coverage: float = 0.0  # Query aspects addressed (35%)
    novelty: float = 0.0  # Distance from prior research (25%)

    @property
    def total(self) -> float:
        """Compute weighted total reward."""
        return 0.40 * self.coherence + 0.35 * self.coverage + 0.25 * self.novelty

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary for frontmatter."""
        return {
            "coherence": round(self.coherence, 3),
            "coverage": round(self.coverage, 3),
            "novelty": round(self.novelty, 3),
        }


@dataclass
class ResearchMemory:
    """A research episode stored as a KB zettelkasten entry.

    Implements MemRL intent-experience-utility triplets:
    - z (intent): The query embedding
    - e (experience): The synthesis content
    - Q (utility): Learned value from rewards

    Stored as markdown with YAML frontmatter in:
    scratch/{date}/{HHMMSS}_research.md
    """

    # Identity
    session_id: str
    query: str
    kb_path: str = ""

    # MemRL state
    q_value: float = DEFAULT_Q_VALUE
    reward_components: RewardComponents = field(default_factory=RewardComponents)
    update_count: int = 0

    # Session context
    pass_number: int = 1
    convergence_reason: str = ""
    total_passes: int = 1

    # Content
    synthesis: str = ""
    sources_kb: list[str] = field(default_factory=list)
    sources_web: list[dict[str, str]] = field(default_factory=list)
    agent_perspectives: dict[str, str] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)

    # Timestamps
    created: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    # Embedding path (stored separately for efficiency)
    query_embedding_path: str = ""

    def update_q_value(self, reward: float, alpha: float = DEFAULT_ALPHA) -> None:
        """Update Q-value using Bellman EMA.

        Q_new <- Q_old + alpha * (reward - Q_old)

        This is a simple temporal-difference update that converges
        to the expected reward over time.

        Args:
            reward: Immediate reward signal (0-1).
            alpha: Learning rate (default 0.3).
        """
        self.q_value += alpha * (reward - self.q_value)
        self.update_count += 1
        self.last_updated = datetime.now()
        logger.debug(
            f"Q-value updated: {self.q_value:.3f} (reward={reward:.3f}, "
            f"alpha={alpha}, count={self.update_count})"
        )

    def to_frontmatter(self) -> dict[str, Any]:
        """Generate YAML frontmatter for KB storage."""
        return {
            "type": "research_memory",
            "query": self.query,
            "query_embedding_path": self.query_embedding_path,
            "q_value": round(self.q_value, 3),
            "reward_components": self.reward_components.to_dict(),
            "update_count": self.update_count,
            "pass_number": self.pass_number,
            "total_passes": self.total_passes,
            "session_id": self.session_id,
            "convergence_reason": self.convergence_reason,
            "created": self.created.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }

    def to_markdown(self) -> str:
        """Generate full markdown document with frontmatter."""
        frontmatter = yaml.dump(
            self.to_frontmatter(),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        # Build markdown sections
        sections = [
            f"---\n{frontmatter}---\n",
            f"# Research: {self.query}\n",
        ]

        # Executive summary (first 2 paragraphs of synthesis)
        if self.synthesis:
            paragraphs = self.synthesis.split("\n\n")[:2]
            sections.append("## Executive Summary\n")
            sections.append("\n\n".join(paragraphs) + "\n")

        # Agent perspectives
        if self.agent_perspectives:
            sections.append("## Agent Perspectives\n")
            for agent, perspective in self.agent_perspectives.items():
                sections.append(f"### {agent}\n")
                sections.append(f"{perspective}\n")

        # Full synthesis
        if self.synthesis:
            sections.append("## Synthesis\n")
            sections.append(f"{self.synthesis}\n")

        # Sources
        sections.append("## Sources\n")

        if self.sources_kb:
            sections.append("### KB Sources\n")
            for source in self.sources_kb:
                sections.append(f"- [[{source}]]\n")

        if self.sources_web:
            sections.append("### Web Sources\n")
            for source in self.sources_web:
                title = source.get("title", "Untitled")
                url = source.get("url", "")
                sections.append(f"- [{title}]({url})\n")

        # Open questions
        if self.open_questions:
            sections.append("## Open Questions\n")
            for question in self.open_questions:
                sections.append(f"- {question}\n")

        # Actions
        sections.append("## Actions\n")
        sections.append(f"[action:/research {self.query}]\n")
        sections.append(f"[action:/search --local {self.query}]\n")

        # Session metadata
        sections.append("## Session Metadata\n")
        sections.append(f"- Passes: {self.total_passes}\n")
        sections.append(f"- Convergence: {self.convergence_reason}\n")
        sections.append(f"- Q-value: {self.q_value:.3f}\n")
        sections.append(f"- High-Q memories retrieved: {self.update_count}\n")

        return "\n".join(sections)

    @classmethod
    def from_frontmatter(cls, kb_path: str, frontmatter: dict[str, Any], content: str = "") -> ResearchMemory:
        """Parse a ResearchMemory from KB entry with frontmatter.

        Args:
            kb_path: Path to the KB entry.
            frontmatter: Parsed YAML frontmatter.
            content: Optional markdown content.

        Returns:
            ResearchMemory instance.
        """
        # Parse reward components
        reward_dict = frontmatter.get("reward_components", {})
        reward = RewardComponents(
            coherence=reward_dict.get("coherence", 0.0),
            coverage=reward_dict.get("coverage", 0.0),
            novelty=reward_dict.get("novelty", 0.0),
        )

        # Parse timestamps
        created = frontmatter.get("created", "")
        if isinstance(created, str) and created:
            created = datetime.fromisoformat(created)
        else:
            created = datetime.now()

        last_updated = frontmatter.get("last_updated", "")
        if isinstance(last_updated, str) and last_updated:
            last_updated = datetime.fromisoformat(last_updated)
        else:
            last_updated = datetime.now()

        return cls(
            session_id=frontmatter.get("session_id", ""),
            query=frontmatter.get("query", ""),
            kb_path=kb_path,
            q_value=frontmatter.get("q_value", DEFAULT_Q_VALUE),
            reward_components=reward,
            update_count=frontmatter.get("update_count", 0),
            pass_number=frontmatter.get("pass_number", 1),
            total_passes=frontmatter.get("total_passes", 1),
            convergence_reason=frontmatter.get("convergence_reason", ""),
            synthesis=content,
            query_embedding_path=frontmatter.get("query_embedding_path", ""),
            created=created,
            last_updated=last_updated,
        )


def parse_kb_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Markdown content with optional frontmatter.

    Returns:
        Tuple of (frontmatter dict, remaining content).
    """
    if not content.startswith("---"):
        return {}, content

    # Find closing ---
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
    if not match:
        return {}, content

    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
        return frontmatter, match.group(2)
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse frontmatter: {e}")
        from gaius.flows.research import MemoryError
        raise MemoryError(
            f"YAML frontmatter parsing failed: {e}",
            guru_code="#RF.00000013.FRONTMATTERFAIL",
            hint="Check YAML syntax in document frontmatter",
        ) from e


async def retrieve_memories(
    query: str,
    kb_root: str = "build/dev",
    semantic_limit: int = 20,
    q_rank_limit: int = 5,
) -> list[ResearchMemory]:
    """MemRL two-phase retrieval: semantic filter -> Q-value ranking.

    Phase A: Use KB search to find semantically similar research memories.
    Phase B: Re-rank by Q-value to prefer high-utility memories.

    Args:
        query: Search query string.
        kb_root: KB root directory (used for file path resolution).
        semantic_limit: Max candidates from semantic search.
        q_rank_limit: Final memories to return after Q-ranking.

    Returns:
        List of ResearchMemory instances, sorted by Q-value descending.
        Empty list is valid for first-time queries with no prior memories.
    """
    from gaius.storage.kb_ops import search_kb, get_kb_root

    # Phase A: Semantic similarity filter
    try:
        results = await search_kb(
            query=query,
            max_results=semantic_limit,
        )
    except Exception as e:
        logger.error(f"Memory retrieval failed: {e}")
        # Empty result is valid for first-time queries - return empty list
        return []

    # Parse results into ResearchMemory instances
    memories: list[ResearchMemory] = []
    # Use the configured KB root for file resolution
    kb_path = get_kb_root()

    for result in results:
        path = result.path
        if not path:
            continue

        full_path = kb_path / path
        if not full_path.exists():
            continue

        try:
            content = full_path.read_text()
            frontmatter, body = parse_kb_frontmatter(content)

            # Only include research_memory type
            if frontmatter.get("type") != "research_memory":
                continue

            memory = ResearchMemory.from_frontmatter(path, frontmatter, body)
            memories.append(memory)
        except Exception as e:
            logger.error(f"Failed to parse memory {path}: {e}")
            from gaius.flows.research import MemoryError
            raise MemoryError(
                f"Research memory parsing failed for {path}: {e}",
                guru_code="#RF.00000014.MEMORYPARSEFAIL",
                hint="/health fix kb",
            ) from e

    # Phase B: Re-rank by Q-value (prefer high-utility memories)
    memories.sort(key=lambda m: m.q_value, reverse=True)

    top_q = memories[0].q_value if memories else 0.0
    logger.info(
        f"Retrieved {len(memories)} memories from {len(results)} candidates "
        f"(top Q={top_q:.3f})"
    )

    return memories[:q_rank_limit]


async def save_memory(
    memory: ResearchMemory,
    kb_root: str = "build/dev",
) -> str:
    """Save a ResearchMemory to the KB as a zettelkasten entry.

    Args:
        memory: ResearchMemory to save.
        kb_root: KB root directory.

    Returns:
        Relative path to the saved entry.
    """
    from gaius.flows.base import GaiusFlow

    # Generate zettelkasten path
    base_flow = GaiusFlow()
    kb_path = base_flow.zettelkasten_path("research", kb_root=kb_root)

    # Write to file
    full_path = Path(kb_root) / kb_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(memory.to_markdown())

    # Update memory with path
    memory.kb_path = kb_path

    logger.info(f"Saved research memory to {kb_path} (Q={memory.q_value:.3f})")

    return kb_path


async def update_related_memories(
    current_memory: ResearchMemory,
    reward: float,
    kb_root: str = "build/dev",
    similarity_threshold: float = 0.7,
    alpha: float = DEFAULT_ALPHA * 0.5,  # Slower update for related memories
) -> int:
    """Update Q-values of related memories (temporal credit assignment).

    When a research pass succeeds, related memories that contributed
    should also get a (smaller) Q-value boost.

    Args:
        current_memory: The memory that just received a reward.
        reward: The reward signal.
        kb_root: KB root directory.
        similarity_threshold: Min similarity to consider related.
        alpha: Learning rate for related memories (default: half of direct).

    Returns:
        Number of related memories updated.
    """
    # Get related memories
    related = await retrieve_memories(
        query=current_memory.query,
        kb_root=kb_root,
        semantic_limit=10,
        q_rank_limit=5,
    )

    updated_count = 0
    for memory in related:
        # Skip self
        if memory.session_id == current_memory.session_id:
            continue

        # Update with discounted reward
        discounted_reward = reward * 0.5  # 50% credit to related
        memory.update_q_value(discounted_reward, alpha=alpha)

        # Save updated memory
        if memory.kb_path:
            try:
                full_path = Path(kb_root) / memory.kb_path
                if full_path.exists():
                    full_path.write_text(memory.to_markdown())
                    updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update related memory {memory.kb_path}: {e}")
                from gaius.flows.research import MemoryError
                raise MemoryError(
                    f"Failed to update related memory {memory.kb_path}: {e}",
                    guru_code="#RF.00000005.QUPDATE",
                    hint="/health fix kb",
                ) from e

    logger.info(f"Updated {updated_count} related memories with discounted reward")
    return updated_count
