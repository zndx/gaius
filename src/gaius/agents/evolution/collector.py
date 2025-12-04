"""Training example collector for evolution.

Collects high-quality training examples from successful
interactions for use in agent optimization.

Sources:
- High-rated swarm outputs (via evaluator scores)
- Acknowledged cognition thoughts
- Successful reflection outputs
- Research outputs
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskExample:
    """A training example for agent optimization.

    Matches the format expected by APO/GEPA optimizer.
    """

    input_prompt: str
    expected_output: str | None = None
    context: str = ""
    evaluation_criteria: str = ""
    reference_score: float | None = None
    source_type: str = ""  # swarm, cognition, reflection, research
    source_id: str = ""


class TrainingCollector:
    """Collects high-quality training examples from interactions.

    Gathers examples from multiple sources:
    1. High-scoring swarm outputs
    2. Cognition thoughts (CURIOSITY, PATTERN, CONNECTION)
    3. Successful reflection outputs
    4. Research outputs

    Examples are filtered by quality (minimum score threshold)
    and recency (configurable time window).
    """

    # Minimum score to consider an example high-quality
    MIN_SCORE_THRESHOLD = 0.7

    # Time window for recent examples (days)
    RECENT_WINDOW_DAYS = 7

    def __init__(self, db_url: str | None = None):
        """Initialize training collector.

        Args:
            db_url: PostgreSQL connection URL (defaults to env)
        """
        self.db_url = db_url or os.getenv("DATABASE_URL", "")
        self._conn = None

    async def collect_examples(
        self,
        agent_id: str,
        max_examples: int = 20,
        min_score: float | None = None,
    ) -> list[TaskExample]:
        """Collect training examples for an agent.

        Args:
            agent_id: Agent to collect examples for
            max_examples: Maximum examples to return
            min_score: Minimum quality score (default: MIN_SCORE_THRESHOLD)

        Returns:
            List of TaskExamples suitable for optimization
        """
        min_score = min_score or self.MIN_SCORE_THRESHOLD
        examples = []

        # 1. Get high-scoring swarm outputs
        swarm_examples = await self._get_swarm_examples(
            agent_id=agent_id,
            max_examples=max_examples // 2,
            min_score=min_score,
        )
        examples.extend(swarm_examples)
        logger.debug(f"Collected {len(swarm_examples)} swarm examples")

        # 2. Get cognition thoughts
        thought_examples = await self._get_thought_examples(
            agent_id=agent_id,
            max_examples=max_examples // 4,
        )
        examples.extend(thought_examples)
        logger.debug(f"Collected {len(thought_examples)} thought examples")

        # 3. Get research outputs
        research_examples = await self._get_research_examples(
            max_examples=max_examples // 4,
        )
        examples.extend(research_examples)
        logger.debug(f"Collected {len(research_examples)} research examples")

        # Shuffle to avoid ordering bias
        import random
        random.shuffle(examples)

        logger.info(f"Collected {len(examples)} total examples for {agent_id}")
        return examples[:max_examples]

    async def _get_swarm_examples(
        self,
        agent_id: str,
        max_examples: int,
        min_score: float,
    ) -> list[TaskExample]:
        """Get examples from high-scoring swarm runs.

        Args:
            agent_id: Agent role to filter by
            max_examples: Maximum to return
            min_score: Minimum score threshold

        Returns:
            List of TaskExamples
        """
        try:
            if not self.db_url:
                return []

            import asyncpg

            conn = await asyncpg.connect(self.db_url)
            try:
                # Query activity_events for swarm runs
                cutoff = datetime.now() - timedelta(days=self.RECENT_WINDOW_DAYS)

                rows = await conn.fetch(
                    """
                    SELECT
                        e.details->>'domain' as domain,
                        e.details->>'context' as context,
                        e.details->>'output' as output,
                        e.details->>'score' as score,
                        e.id as event_id
                    FROM activity_events e
                    WHERE e.event_type = 'swarm_run'
                      AND e.details->>'agent_role' = $1
                      AND (e.details->>'score')::float >= $2
                      AND e.created_at > $3
                    ORDER BY (e.details->>'score')::float DESC
                    LIMIT $4
                    """,
                    agent_id,
                    min_score,
                    cutoff,
                    max_examples,
                )

                examples = []
                for row in rows:
                    # Reconstruct input prompt from domain/context
                    domain = row["domain"] or ""
                    context = row["context"] or ""
                    output = row["output"] or ""

                    if not output:
                        continue

                    input_prompt = f"Analyze the domain: {domain}"
                    if context:
                        input_prompt += f"\n\nContext:\n{context}"

                    examples.append(TaskExample(
                        input_prompt=input_prompt,
                        expected_output=output,
                        context=context,
                        reference_score=float(row["score"]) if row["score"] else None,
                        source_type="swarm",
                        source_id=str(row["event_id"]),
                    ))

                return examples

            finally:
                await conn.close()

        except ImportError:
            logger.debug("asyncpg not available for swarm examples")
            return []
        except Exception as e:
            logger.warning(f"Failed to get swarm examples: {e}")
            return []

    async def _get_thought_examples(
        self,
        agent_id: str,
        max_examples: int,
    ) -> list[TaskExample]:
        """Get examples from cognition thoughts.

        Converts high-quality thoughts into training examples.

        Args:
            agent_id: Agent to get thoughts for
            max_examples: Maximum to return

        Returns:
            List of TaskExamples
        """
        try:
            # Try to get thoughts from cognition agent
            from ..cognition import get_cognition_agent, ThoughtType

            agent = get_cognition_agent()
            thoughts = await agent.get_active_thoughts(limit=max_examples * 2)

            examples = []
            for thought in thoughts[:max_examples]:
                # Convert thought type to task
                if thought.thought_type == ThoughtType.CURIOSITY:
                    input_prompt = thought.title
                    criteria = "Provide a thoughtful, specific, actionable answer"
                elif thought.thought_type == ThoughtType.PATTERN:
                    input_prompt = f"Analyze: {thought.title}"
                    criteria = "Explain implications and suggest concrete next steps"
                elif thought.thought_type == ThoughtType.CONNECTION:
                    input_prompt = f"Explore connection: {thought.title}"
                    criteria = "Deepen the connection and identify practical applications"
                else:
                    input_prompt = thought.title
                    criteria = "Provide a comprehensive analysis"

                examples.append(TaskExample(
                    input_prompt=input_prompt,
                    context=thought.content,
                    evaluation_criteria=criteria,
                    source_type="cognition",
                    source_id=thought.id if hasattr(thought, "id") else "",
                ))

            return examples

        except ImportError:
            logger.debug("Cognition agent not available")
            return []
        except Exception as e:
            logger.warning(f"Failed to get thought examples: {e}")
            return []

    async def _get_research_examples(
        self,
        max_examples: int,
    ) -> list[TaskExample]:
        """Get examples from successful research outputs.

        Args:
            max_examples: Maximum to return

        Returns:
            List of TaskExamples
        """
        try:
            if not self.db_url:
                return []

            import asyncpg

            conn = await asyncpg.connect(self.db_url)
            try:
                cutoff = datetime.now() - timedelta(days=self.RECENT_WINDOW_DAYS)

                rows = await conn.fetch(
                    """
                    SELECT
                        e.details->>'topic' as topic,
                        e.details->>'domain' as domain,
                        e.details->>'summary' as summary,
                        e.id as event_id
                    FROM activity_events e
                    WHERE e.event_type = 'research_complete'
                      AND e.details->>'summary' IS NOT NULL
                      AND LENGTH(e.details->>'summary') > 100
                      AND e.created_at > $1
                    ORDER BY e.created_at DESC
                    LIMIT $2
                    """,
                    cutoff,
                    max_examples,
                )

                examples = []
                for row in rows:
                    topic = row["topic"] or "general topic"
                    domain = row["domain"] or ""
                    summary = row["summary"] or ""

                    if not summary:
                        continue

                    input_prompt = f"Research the topic: {topic}"
                    if domain:
                        input_prompt += f" in the context of {domain}"

                    examples.append(TaskExample(
                        input_prompt=input_prompt,
                        expected_output=summary,
                        context=f"Domain: {domain}" if domain else "",
                        evaluation_criteria="Provide comprehensive, accurate research with citations",
                        source_type="research",
                        source_id=str(row["event_id"]),
                    ))

                return examples

            finally:
                await conn.close()

        except ImportError:
            logger.debug("asyncpg not available for research examples")
            return []
        except Exception as e:
            logger.warning(f"Failed to get research examples: {e}")
            return []

    async def _get_reflection_examples(
        self,
        max_examples: int,
    ) -> list[TaskExample]:
        """Get examples from reflection outputs.

        Args:
            max_examples: Maximum to return

        Returns:
            List of TaskExamples
        """
        try:
            if not self.db_url:
                return []

            import asyncpg

            conn = await asyncpg.connect(self.db_url)
            try:
                cutoff = datetime.now() - timedelta(days=self.RECENT_WINDOW_DAYS)

                rows = await conn.fetch(
                    """
                    SELECT
                        e.details->>'topic' as topic,
                        e.details->>'depth' as depth,
                        e.details->>'synthesis' as synthesis,
                        e.id as event_id
                    FROM activity_events e
                    WHERE e.event_type = 'reflection_complete'
                      AND e.details->>'synthesis' IS NOT NULL
                      AND LENGTH(e.details->>'synthesis') > 100
                      AND e.created_at > $1
                    ORDER BY e.created_at DESC
                    LIMIT $2
                    """,
                    cutoff,
                    max_examples,
                )

                examples = []
                for row in rows:
                    topic = row["topic"] or "accumulated knowledge"
                    depth = row["depth"] or "moderate"
                    synthesis = row["synthesis"] or ""

                    if not synthesis:
                        continue

                    input_prompt = f"Reflect on: {topic} (depth: {depth})"

                    examples.append(TaskExample(
                        input_prompt=input_prompt,
                        expected_output=synthesis,
                        evaluation_criteria="Provide deep, insightful reflection with actionable recommendations",
                        source_type="reflection",
                        source_id=str(row["event_id"]),
                    ))

                return examples

            finally:
                await conn.close()

        except ImportError:
            logger.debug("asyncpg not available for reflection examples")
            return []
        except Exception as e:
            logger.warning(f"Failed to get reflection examples: {e}")
            return []


# Module-level singleton
_training_collector: TrainingCollector | None = None


def get_training_collector() -> TrainingCollector:
    """Get or create training collector singleton."""
    global _training_collector
    if _training_collector is None:
        _training_collector = TrainingCollector()
    return _training_collector
