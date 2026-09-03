"""Task ideation agent for autonomous reasoning task generation.

Generates new reasoning tasks by:
1. Analyzing gaps in existing task coverage
2. Brainstorming concepts via swarm/reasoning model
3. Creating drafts using TaskAuthor
4. Validating novelty and quality

Integrates with:
- CognitionAgent: Generates TASK_IDEA thoughts
- TaskAuthor: Creates drafts from concepts
- DailyEvaluator: Validates task effectiveness
- EvolutionDaemon: Triggered during idle periods

Usage:
    from gaius.agents.evolution.task_ideation import (
        TaskIdeationAgent,
        get_task_ideation_agent,
    )

    agent = await get_task_ideation_agent()

    # Run full ideation cycle
    drafts = await agent.run_ideation_cycle()

    # Or step by step
    gaps = await agent.identify_gaps()
    concept = await agent.generate_task_concept(gaps[0])
    draft = await agent.concept_to_draft(concept)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .reasoning_tasks import load_reasoning_tasks, ReasoningTask
from .task_authoring import (
    ReasoningTaskDraft,
    TaskExample,
    TaskAuthor,
    get_task_author,
)
from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)


@dataclass
class TaskConcept:
    """A concept for a new reasoning task before full draft creation."""

    capability: str  # The reasoning capability being tested
    name: str  # Proposed task name
    description: str  # What the task evaluates
    tags: list[str]  # Proposed tags
    rationale: str  # Why this task is needed
    example_domains: list[str]  # Domains for example generation
    estimated_difficulty: float = 0.6  # Target difficulty
    novelty_score: float = 0.0  # How novel vs existing tasks
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "capability": self.capability,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "rationale": self.rationale,
            "example_domains": self.example_domains,
            "estimated_difficulty": self.estimated_difficulty,
            "novelty_score": self.novelty_score,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class GapAnalysis:
    """Result of analyzing gaps in reasoning task coverage."""

    existing_categories: set[str]
    existing_capabilities: set[str]
    identified_gaps: list[str]
    gap_rationales: dict[str, str]  # gap -> why it matters
    analysis_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TaskIdeationAgent:
    """Generates new reasoning task ideas autonomously.

    The agent follows a systematic process:
    1. Gap Analysis: Compare existing Nous tasks against reasoning taxonomy
    2. Concept Generation: Use swarm/reasoning to design new tasks
    3. Novelty Validation: Ensure task is distinct from existing ones
    4. Draft Creation: Create full task with examples
    5. Quality Validation: Run through evolution to verify effectiveness
    """

    # Reasoning capability taxonomy (what LLMs should be able to do)
    CAPABILITY_TAXONOMY = {
        "logical": [
            "deductive_reasoning",
            "inductive_reasoning",
            "abductive_reasoning",
            "syllogistic_reasoning",
            "propositional_logic",
            "predicate_logic",
            "modal_reasoning",
        ],
        "mathematical": [
            "arithmetic_reasoning",
            "algebraic_reasoning",
            "geometric_reasoning",
            "probabilistic_reasoning",
            "statistical_inference",
            "optimization_reasoning",
        ],
        "causal": [
            "causal_inference",
            "counterfactual_reasoning",
            "intervention_analysis",
            "mechanism_identification",
            "causal_chain_construction",
        ],
        "analogical": [
            "structural_mapping",
            "relational_reasoning",
            "cross_domain_transfer",
            "metaphor_interpretation",
        ],
        "temporal": [
            "sequence_reasoning",
            "temporal_ordering",
            "duration_estimation",
            "timeline_construction",
            "temporal_constraint_satisfaction",
        ],
        "spatial": [
            "spatial_reasoning",
            "navigation_planning",
            "geometric_transformation",
            "spatial_relationship_description",
        ],
        "meta_cognitive": [
            "uncertainty_quantification",
            "confidence_calibration",
            "error_detection",
            "assumption_identification",
            "limitation_awareness",
        ],
        "constraint_based": [
            "constraint_satisfaction",
            "constraint_relaxation",
            "constraint_propagation",
            "resource_allocation",
            "scheduling_reasoning",
        ],
        "strategic": [
            "game_theoretic_reasoning",
            "adversarial_thinking",
            "negotiation_strategy",
            "risk_assessment",
            "decision_under_uncertainty",
        ],
        "explanatory": [
            "explanation_generation",
            "simplification_reasoning",
            "analogy_creation",
            "conceptual_decomposition",
        ],
    }

    def __init__(self):
        self._author: Optional[TaskAuthor] = None
        self._cached_tasks: Optional[list[ReasoningTask]] = None
        self._last_gap_analysis: Optional[GapAnalysis] = None

    async def _get_author(self) -> TaskAuthor:
        """Get or create TaskAuthor instance."""
        if self._author is None:
            self._author = await get_task_author()
        return self._author

    async def _get_existing_tasks(self, refresh: bool = False) -> list[ReasoningTask]:
        """Load existing Nous Research tasks."""
        if self._cached_tasks is None or refresh:
            self._cached_tasks = await load_reasoning_tasks(max_tasks=100)
        return self._cached_tasks

    async def identify_gaps(self, refresh: bool = False) -> GapAnalysis:
        """Analyze gaps in existing reasoning task coverage.

        Compares existing Nous tasks against the capability taxonomy
        to identify underrepresented reasoning capabilities.

        Args:
            refresh: Force reload of existing tasks

        Returns:
            GapAnalysis with identified gaps and rationales
        """
        if self._last_gap_analysis and not refresh:
            # Cache for 1 hour
            age = (datetime.now(timezone.utc) - self._last_gap_analysis.analysis_timestamp).seconds
            if age < 3600:
                return self._last_gap_analysis

        tasks = await self._get_existing_tasks(refresh)

        # Extract existing categories and capabilities
        existing_categories: set[str] = set()
        existing_capabilities: set[str] = set()

        for task in tasks:
            for tag in task.tags:
                tag_lower = tag.lower().replace(" ", "_").replace("-", "_")
                existing_categories.add(tag_lower)

                # Map tags to capabilities
                for category, capabilities in self.CAPABILITY_TAXONOMY.items():
                    for cap in capabilities:
                        if cap in tag_lower or tag_lower in cap:
                            existing_capabilities.add(cap)

        # Find gaps
        all_capabilities = set()
        for capabilities in self.CAPABILITY_TAXONOMY.values():
            all_capabilities.update(capabilities)

        gaps = all_capabilities - existing_capabilities

        # Generate rationales for top gaps
        gap_rationales = {}
        priority_gaps = []

        for gap in gaps:
            # Find category
            for category, capabilities in self.CAPABILITY_TAXONOMY.items():
                if gap in capabilities:
                    rationale = self._generate_gap_rationale(gap, category, existing_capabilities)
                    gap_rationales[gap] = rationale
                    priority_gaps.append(gap)
                    break

        self._last_gap_analysis = GapAnalysis(
            existing_categories=existing_categories,
            existing_capabilities=existing_capabilities,
            identified_gaps=priority_gaps,
            gap_rationales=gap_rationales,
        )

        logger.info(
            f"Gap analysis complete: {len(existing_capabilities)} existing, "
            f"{len(priority_gaps)} gaps identified"
        )

        return self._last_gap_analysis

    def _generate_gap_rationale(
        self,
        gap: str,
        category: str,
        existing: set[str],
    ) -> str:
        """Generate rationale for why a gap matters."""
        # Check if related capabilities exist
        related = [c for c in self.CAPABILITY_TAXONOMY.get(category, []) if c in existing]

        if related:
            return (
                f"The {category} category has {len(related)} existing tasks "
                f"({', '.join(related[:2])}...) but lacks {gap.replace('_', ' ')}. "
                f"Adding this would provide more complete coverage."
            )
        else:
            return (
                f"The {category} category is underrepresented in existing tasks. "
                f"{gap.replace('_', ' ').title()} is a fundamental capability that "
                f"would expand benchmark diversity."
            )

    async def generate_task_concept(
        self,
        capability: str,
        use_swarm: bool = False,
    ) -> TaskConcept:
        """Generate a task concept for a given capability.

        Args:
            capability: The reasoning capability to design a task for
            use_swarm: If True, use swarm analysis for richer ideation

        Returns:
            TaskConcept with proposed task design
        """
        # Get gap rationale if available
        rationale = ""
        if self._last_gap_analysis:
            rationale = self._last_gap_analysis.gap_rationales.get(capability, "")

        # Generate concept via reasoning model
        prompt = f"""Design a reasoning task for evaluating LLM capability: {capability.replace('_', ' ')}

Context: {rationale}

Provide a JSON response with:
{{
    "name": "Task Name in Title Case",
    "description": "Clear description of what reasoning capability this tests",
    "tags": ["Tag1", "Tag2", "Tag3", "Tag4", "Synthetic"],
    "example_domains": ["domain1", "domain2", "domain3"],
    "rationale": "Why this task is valuable for LLM evaluation",
    "estimated_difficulty": 0.6
}}

Requirements:
- Task should be text-only (no images/diagrams required)
- Should have clear evaluation criteria
- Should challenge but not stump current LLMs
- Examples should be drawable from diverse real-world domains"""

        try:
            if use_swarm:
                from ...mcp.operations import run_swarm
                result = await run_swarm(query=prompt, domain="reasoning", num_agents=5)
                content = result.get("synthesis", "")
            else:
                from ...mcp.operations import ask_reasoning
                result = await ask_reasoning(
                    question=prompt,
                    system_prompt="You are designing LLM reasoning benchmarks.",
                    max_tokens=REASONING_MAX_TOKENS,
                )
                content = result.get("content", "")

            # Parse JSON from response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])

                concept = TaskConcept(
                    capability=capability,
                    name=data.get("name", capability.replace("_", " ").title()),
                    description=data.get("description", ""),
                    tags=data.get("tags", [capability.replace("_", " ").title(), "Synthetic"]),
                    rationale=data.get("rationale", rationale),
                    example_domains=data.get("example_domains", []),
                    estimated_difficulty=data.get("estimated_difficulty", 0.6),
                )

                # Calculate novelty score
                concept.novelty_score = await self._calculate_novelty(concept)

                logger.info(f"Generated concept: {concept.name} (novelty: {concept.novelty_score:.2f})")
                return concept

        except Exception as e:
            logger.warning(f"Concept generation failed: {e}")

        # Fallback to basic concept
        return TaskConcept(
            capability=capability,
            name=capability.replace("_", " ").title(),
            description=f"Evaluate {capability.replace('_', ' ')} capability",
            tags=[capability.replace("_", " ").title(), "Reasoning", "Synthetic"],
            rationale=rationale or f"Tests {capability.replace('_', ' ')} reasoning",
            example_domains=["general", "technical", "everyday"],
            estimated_difficulty=0.6,
        )

    async def _calculate_novelty(self, concept: TaskConcept) -> float:
        """Calculate how novel a concept is vs existing tasks.

        Returns:
            Novelty score 0.0-1.0 (higher = more novel)
        """
        tasks = await self._get_existing_tasks()

        # Check name similarity
        concept_words = set(concept.name.lower().split())
        max_name_overlap = 0.0

        for task in tasks:
            task_words = set(task.name.lower().split())
            if concept_words and task_words:
                overlap = len(concept_words & task_words) / len(concept_words | task_words)
                max_name_overlap = max(max_name_overlap, overlap)

        # Check tag overlap
        concept_tags = set(t.lower() for t in concept.tags)
        max_tag_overlap = 0.0

        for task in tasks:
            task_tags = set(t.lower() for t in task.tags)
            if concept_tags and task_tags:
                overlap = len(concept_tags & task_tags) / len(concept_tags | task_tags)
                max_tag_overlap = max(max_tag_overlap, overlap)

        # Novelty is inverse of similarity
        name_novelty = 1.0 - max_name_overlap
        tag_novelty = 1.0 - max_tag_overlap

        # Weight name more heavily
        return 0.6 * name_novelty + 0.4 * tag_novelty

    async def validate_novelty(self, concept: TaskConcept, threshold: float = 0.5) -> bool:
        """Check if concept is sufficiently novel.

        Args:
            concept: Task concept to validate
            threshold: Minimum novelty score (0.0-1.0)

        Returns:
            True if novel enough for draft creation
        """
        if concept.novelty_score == 0.0:
            concept.novelty_score = await self._calculate_novelty(concept)

        is_novel = concept.novelty_score >= threshold
        logger.info(
            f"Novelty check for '{concept.name}': "
            f"{concept.novelty_score:.2f} {'≥' if is_novel else '<'} {threshold}"
        )
        return is_novel

    async def concept_to_draft(
        self,
        concept: TaskConcept,
        generate_examples: bool = True,
        num_examples: int = 2,
    ) -> ReasoningTaskDraft:
        """Convert a concept into a full task draft.

        Args:
            concept: Task concept to expand
            generate_examples: Whether to generate examples via LLM
            num_examples: Number of examples to generate

        Returns:
            ReasoningTaskDraft ready for validation
        """
        author = await self._get_author()

        # Create draft
        draft = await author.create_draft(
            name=concept.name,
            description=concept.description,
            tags=concept.tags,
            generate_examples=False,  # We'll do custom generation
        )

        if generate_examples:
            examples = await self._generate_examples(concept, num_examples)
            draft.examples.extend(examples)

        return draft

    async def _generate_examples(
        self,
        concept: TaskConcept,
        count: int = 2,
    ) -> list[TaskExample]:
        """Generate examples for a task concept.

        Uses the concept's example_domains for diversity.
        """
        examples = []

        prompt = f"""Generate {count} diverse examples for this reasoning task:

Task: {concept.name}
Description: {concept.description}
Capability being tested: {concept.capability.replace('_', ' ')}
Suggested domains: {', '.join(concept.example_domains)}

For each example provide:
1. INPUT: A clear prompt that tests the reasoning capability
2. OUTPUT: A detailed response showing the full reasoning process

Format as JSON:
{{
    "examples": [
        {{"input": "...", "output": "..."}},
        {{"input": "...", "output": "..."}}
    ]
}}

Requirements:
- Each example should be from a different domain
- Outputs should show step-by-step reasoning
- Difficulty should be challenging but achievable
- Outputs should be 200-500 words"""

        try:
            from ...mcp.operations import ask_reasoning

            result = await ask_reasoning(
                question=prompt,
                system_prompt="You are creating high-quality LLM reasoning benchmark examples.",
                max_tokens=REASONING_MAX_TOKENS,
            )

            content = result.get("content", "")

            # Parse JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
                data = json.loads(json_str)

                for ex in data.get("examples", []):
                    if ex.get("input") and ex.get("output"):
                        examples.append(TaskExample(
                            input=ex["input"],
                            output=ex["output"],
                        ))

        except Exception as e:
            logger.warning(f"Example generation failed: {e}")

        logger.info(f"Generated {len(examples)} examples for '{concept.name}'")
        return examples

    async def run_ideation_cycle(
        self,
        max_concepts: int = 3,
        novelty_threshold: float = 0.5,
        save_drafts: bool = True,
    ) -> list[ReasoningTaskDraft]:
        """Run a full ideation cycle.

        1. Identify gaps in existing tasks
        2. Generate concepts for top gaps
        3. Validate novelty
        4. Create drafts with examples
        5. Save drafts for validation

        Args:
            max_concepts: Maximum concepts to generate
            novelty_threshold: Minimum novelty score
            save_drafts: Whether to save drafts to disk

        Returns:
            List of created ReasoningTaskDraft
        """
        logger.info("Starting task ideation cycle")

        # Step 1: Gap analysis
        analysis = await self.identify_gaps(refresh=True)

        if not analysis.identified_gaps:
            logger.info("No gaps identified - existing tasks have good coverage")
            return []

        # Step 2: Generate concepts for top gaps
        concepts = []
        for gap in analysis.identified_gaps[:max_concepts * 2]:  # Generate extra for filtering
            try:
                concept = await self.generate_task_concept(gap)
                concepts.append(concept)
            except Exception as e:
                logger.warning(f"Failed to generate concept for {gap}: {e}")

            if len(concepts) >= max_concepts * 2:
                break

        # Step 3: Filter by novelty
        novel_concepts = []
        for concept in concepts:
            if await self.validate_novelty(concept, novelty_threshold):
                novel_concepts.append(concept)
                if len(novel_concepts) >= max_concepts:
                    break

        if not novel_concepts:
            logger.info("No sufficiently novel concepts generated")
            return []

        # Step 4: Create drafts
        drafts = []
        author = await self._get_author()

        for concept in novel_concepts:
            try:
                draft = await self.concept_to_draft(concept)

                if draft.examples:  # Only keep drafts with examples
                    if save_drafts:
                        author.save_draft(draft)
                        author.save_markdown(draft)

                    drafts.append(draft)
                    logger.info(f"Created draft: {draft.name}")

            except Exception as e:
                logger.warning(f"Failed to create draft for {concept.name}: {e}")

        logger.info(f"Ideation cycle complete: {len(drafts)} drafts created")
        return drafts

    async def evaluate_draft_effectiveness(
        self,
        draft: ReasoningTaskDraft,
        cycles: int = 5,
    ) -> dict:
        """Evaluate if a draft task is effective for evolution.

        Runs the task through evolution to check:
        - Does it discriminate between agent versions?
        - Is difficulty appropriate (~70% success)?
        - Do scores have reasonable variance?

        Args:
            draft: Task draft to evaluate
            cycles: Number of evaluation cycles

        Returns:
            Dict with evaluation metrics
        """
        author = await self._get_author()

        # Use author's validate method
        passed = await author.validate(draft, cycles=cycles)

        scores = draft.validation_scores
        metrics = {
            "passed": passed,
            "cycles_run": cycles,
            "scores": scores,
        }

        if scores:
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)

            metrics.update({
                "avg_score": avg,
                "variance": variance,
                "min_score": min(scores),
                "max_score": max(scores),
                "discriminates": variance > 0.01,
                "appropriate_difficulty": 0.3 <= avg <= 0.8,
            })

        return metrics

    def get_status(self) -> dict:
        """Get current ideation status."""
        return {
            "cached_tasks": len(self._cached_tasks) if self._cached_tasks else 0,
            "last_gap_analysis": (
                self._last_gap_analysis.analysis_timestamp.isoformat()
                if self._last_gap_analysis else None
            ),
            "gaps_identified": (
                len(self._last_gap_analysis.identified_gaps)
                if self._last_gap_analysis else 0
            ),
            "taxonomy_categories": len(self.CAPABILITY_TAXONOMY),
            "total_capabilities": sum(
                len(caps) for caps in self.CAPABILITY_TAXONOMY.values()
            ),
        }


# Module-level singleton
_ideation_agent: Optional[TaskIdeationAgent] = None


async def get_task_ideation_agent() -> TaskIdeationAgent:
    """Get or create the TaskIdeationAgent singleton.

    Returns:
        TaskIdeationAgent instance
    """
    global _ideation_agent
    if _ideation_agent is None:
        _ideation_agent = TaskIdeationAgent()
    return _ideation_agent


def reset_ideation_agent() -> None:
    """Reset the ideation agent singleton (for testing)."""
    global _ideation_agent
    _ideation_agent = None
