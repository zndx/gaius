"""Reasoning task authoring for Nous Research Open-Reasoning-Tasks format.

Provides tools for creating, validating, and managing new reasoning tasks
that can be submitted upstream to expand the LLM reasoning benchmark.

Usage:
    from gaius.agents.evolution.task_authoring import (
        ReasoningTaskDraft,
        TaskAuthor,
        get_task_author,
    )

    author = await get_task_author()

    # Create a new task draft
    draft = await author.create_draft(
        name="Constraint Relaxation Reasoning",
        description="Systematically relaxing constraints to find solutions",
        tags=["Problem Solving", "Constraint Satisfaction"],
    )

    # Add examples
    await author.add_example(draft, input_text, output_text)

    # Validate and save
    if await author.validate(draft):
        await author.save_draft(draft)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .reasoning_tasks import ReasoningTask, CACHE_DIR
from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)

# Local storage for authored tasks
AUTHORED_DIR = Path("build/dev/reasoning")


@dataclass
class TaskExample:
    """A single input/output example for a reasoning task."""

    input: str
    output: str

    def to_dict(self) -> dict[str, str]:
        return {"input": self.input, "output": self.output}

    def to_nested(self) -> list[dict[str, str]]:
        """Convert to Nous format (nested array)."""
        return [self.to_dict()]


@dataclass
class ReasoningTaskDraft:
    """A draft reasoning task being authored.

    Tracks creation metadata and validation state alongside the task content.
    """

    name: str
    description: str
    tags: list[str]
    examples: list[TaskExample] = field(default_factory=list)
    modality: str = "Text only"
    diagram: Optional[str] = None
    citations: Optional[str] = None

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    author: str = "gaius"
    validation_scores: list[float] = field(default_factory=list)
    status: str = "draft"  # draft, validated, submitted

    @property
    def slug(self) -> str:
        """Generate filename-safe slug from name."""
        return self.name.lower().replace(" ", "-").replace("_", "-")

    def to_json(self) -> dict[str, Any]:
        """Convert to Nous Research JSON format."""
        return {
            "name": self.name,
            "description": self.description,
            "modality": self.modality,
            "diagram": self.diagram,
            "citations": self.citations,
            "examples": [ex.to_nested() for ex in self.examples],
            "tags": self.tags,
        }

    def to_markdown(self) -> str:
        """Convert to Nous Research markdown format."""
        lines = [
            f"# {self.name}",
            "",
            "## Description:",
            self.description,
            "",
            "## Modality:",
            self.modality,
            "",
            "## Examples:",
        ]

        for i, ex in enumerate(self.examples, 1):
            lines.extend([
                "",
                f"### Example {i}:",
                "",
                "Input:",
                "",
                "```",
                ex.input,
                "```",
                "",
                "Output:",
                "",
                "```",
                ex.output,
                "```",
            ])
            if i < len(self.examples):
                lines.extend(["", "---"])

        lines.extend([
            "",
            "## Tags:",
        ])
        for tag in self.tags:
            lines.append(f"- {tag}")

        return "\n".join(lines)

    def to_task(self) -> ReasoningTask:
        """Convert to ReasoningTask for evolution integration."""
        return ReasoningTask(
            name=self.name,
            description=self.description,
            examples=[ex.to_dict() for ex in self.examples],
            tags=self.tags,
            modality=self.modality,
            citations=self.citations,
        )

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ReasoningTaskDraft":
        """Load from stored JSON."""
        examples = []
        for nested in data.get("examples", []):
            if isinstance(nested, list) and nested:
                ex = nested[0] if isinstance(nested[0], dict) else nested
                if isinstance(ex, dict):
                    examples.append(TaskExample(
                        input=ex.get("input", ""),
                        output=ex.get("output", ""),
                    ))

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            examples=examples,
            modality=data.get("modality", "Text only"),
            diagram=data.get("diagram"),
            citations=data.get("citations"),
            status=data.get("_status", "draft"),
            validation_scores=data.get("_validation_scores", []),
        )


class TaskAuthor:
    """Creates and manages reasoning task drafts.

    Provides workflow for:
    1. Creating new task drafts
    2. Generating examples via LLM
    3. Validating tasks through evolution
    4. Exporting for upstream submission
    """

    def __init__(self):
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create storage directories if needed."""
        for subdir in ["drafts", "validated", "submitted", "metrics"]:
            (AUTHORED_DIR / subdir).mkdir(parents=True, exist_ok=True)

    async def create_draft(
        self,
        name: str,
        description: str,
        tags: list[str],
        generate_examples: bool = False,
    ) -> ReasoningTaskDraft:
        """Create a new reasoning task draft.

        Args:
            name: Task name in title case
            description: Clear description of reasoning capability tested
            tags: Category tags (include "Synthetic" for AI-generated)
            generate_examples: If True, use LLM to generate initial examples

        Returns:
            New ReasoningTaskDraft
        """
        # Ensure Synthetic tag for AI-generated tasks
        if "Synthetic" not in tags:
            tags = tags + ["Synthetic"]

        draft = ReasoningTaskDraft(
            name=name,
            description=description,
            tags=tags,
        )

        if generate_examples:
            examples = await self._generate_examples(draft, count=2)
            draft.examples.extend(examples)

        logger.info(f"Created draft: {draft.name}")
        return draft

    async def _generate_examples(
        self,
        draft: ReasoningTaskDraft,
        count: int = 2,
    ) -> list[TaskExample]:
        """Generate examples using LLM.

        Args:
            draft: Task draft to generate examples for
            count: Number of examples to generate

        Returns:
            List of generated TaskExample
        """
        try:
            from ...mcp.operations import ask_reasoning

            prompt = f"""Generate {count} diverse examples for this reasoning task:

Task: {draft.name}
Description: {draft.description}
Tags: {', '.join(draft.tags)}

For each example, provide:
1. A clear INPUT prompt that tests this reasoning capability
2. A detailed OUTPUT showing the complete reasoning process

Format your response as JSON:
{{
  "examples": [
    {{"input": "...", "output": "..."}},
    {{"input": "...", "output": "..."}}
  ]
}}

Requirements:
- Examples should be diverse in context/domain
- Outputs should show full reasoning chains, not just answers
- Difficulty should challenge but not stump current LLMs
- Each output should be 200-500 words"""

            result = await ask_reasoning(
                question=prompt,
                system_prompt="You are creating high-quality LLM reasoning benchmark examples.",
                max_tokens=REASONING_MAX_TOKENS,
            )

            # Parse JSON from response
            content = result.get("content", "")

            # Find JSON in response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                return [
                    TaskExample(input=ex["input"], output=ex["output"])
                    for ex in data.get("examples", [])
                ]

        except Exception as e:
            logger.warning(f"Example generation failed: {e}")

        return []

    def add_example(
        self,
        draft: ReasoningTaskDraft,
        input_text: str,
        output_text: str,
    ) -> TaskExample:
        """Add a manually created example to a draft.

        Args:
            draft: Task draft to add example to
            input_text: The prompt/question
            output_text: The expected reasoning output

        Returns:
            The created TaskExample
        """
        example = TaskExample(input=input_text, output=output_text)
        draft.examples.append(example)
        return example

    async def validate(
        self,
        draft: ReasoningTaskDraft,
        cycles: int = 5,
    ) -> bool:
        """Validate task through evolution cycles.

        Runs the task examples through agent evolution to verify:
        - Examples produce meaningful score variance
        - Average scores indicate reasonable difficulty
        - Task discriminates between agent versions

        Args:
            draft: Task draft to validate
            cycles: Number of evolution cycles to run

        Returns:
            True if validation passes
        """
        if len(draft.examples) < 2:
            logger.warning("Task needs at least 2 examples for validation")
            return False

        try:
            from .engine import TaskItem, get_engine

            engine = await get_engine()

            # Convert examples to TaskItems
            items = [
                TaskItem(
                    id=f"{draft.slug}_{i}",
                    prompt=ex.input,
                    expected_output=ex.output,
                    domain="reasoning",
                    category=draft.tags[0].lower().replace(" ", "_") if draft.tags else "reasoning",
                    context=draft.description,
                )
                for i, ex in enumerate(draft.examples)
            ]

            # Run validation cycles
            scores = []
            for cycle in range(cycles):
                for item in items:
                    # Get current agent config
                    from ...models.versioning import get_version_manager

                    manager = get_version_manager()
                    version = await manager.get_active_version("leader")
                    if not version:
                        continue
                    config = version.config

                    trajectory = await engine.run_trajectory(config, item)
                    scores.append(trajectory.score)

            if not scores:
                logger.warning("No scores collected during validation")
                return False

            # Validation criteria
            avg_score = sum(scores) / len(scores)
            score_variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)

            draft.validation_scores = scores

            # Criteria:
            # - Average score 0.3-0.8 (not too easy, not too hard)
            # - Some variance (task discriminates)
            passes = 0.3 <= avg_score <= 0.8 and score_variance > 0.01

            if passes:
                draft.status = "validated"
                logger.info(
                    f"Validation passed: avg={avg_score:.2f}, var={score_variance:.3f}"
                )
            else:
                logger.info(
                    f"Validation failed: avg={avg_score:.2f}, var={score_variance:.3f}"
                )

            return passes

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False

    def save_draft(self, draft: ReasoningTaskDraft) -> Path:
        """Save draft to local storage.

        Args:
            draft: Task draft to save

        Returns:
            Path to saved file
        """
        # Determine directory based on status
        if draft.status == "validated":
            subdir = "validated"
        elif draft.status == "submitted":
            subdir = "submitted"
        else:
            subdir = "drafts"

        # Save JSON
        path = AUTHORED_DIR / subdir / f"{draft.slug}.json"
        data = draft.to_json()

        # Add metadata
        data["_status"] = draft.status
        data["_validation_scores"] = draft.validation_scores
        data["_created_at"] = draft.created_at.isoformat()
        data["_author"] = draft.author

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved draft to {path}")
        return path

    def save_markdown(self, draft: ReasoningTaskDraft) -> Path:
        """Save draft as markdown for human review.

        Args:
            draft: Task draft to save

        Returns:
            Path to saved file
        """
        path = AUTHORED_DIR / "drafts" / f"{draft.slug}.md"
        with open(path, "w") as f:
            f.write(draft.to_markdown())

        logger.info(f"Saved markdown to {path}")
        return path

    def list_drafts(self, status: Optional[str] = None) -> list[ReasoningTaskDraft]:
        """List all task drafts.

        Args:
            status: Filter by status (draft, validated, submitted)

        Returns:
            List of ReasoningTaskDraft
        """
        drafts = []

        # Determine directories to search
        if status:
            dirs = [AUTHORED_DIR / status]
        else:
            dirs = [
                AUTHORED_DIR / "drafts",
                AUTHORED_DIR / "validated",
                AUTHORED_DIR / "submitted",
            ]

        for dir_path in dirs:
            if not dir_path.exists():
                continue

            for path in dir_path.glob("*.json"):
                try:
                    with open(path) as f:
                        data = json.load(f)
                    draft = ReasoningTaskDraft.from_json(data)
                    drafts.append(draft)
                except Exception as e:
                    logger.debug(f"Error loading {path}: {e}")

        return drafts

    def load_draft(self, slug: str) -> Optional[ReasoningTaskDraft]:
        """Load a specific draft by slug.

        Args:
            slug: Task slug (filename without extension)

        Returns:
            ReasoningTaskDraft or None if not found
        """
        for subdir in ["drafts", "validated", "submitted"]:
            path = AUTHORED_DIR / subdir / f"{slug}.json"
            if path.exists():
                try:
                    with open(path) as f:
                        data = json.load(f)
                    return ReasoningTaskDraft.from_json(data)
                except Exception as e:
                    logger.error(f"Error loading {path}: {e}")

        return None

    async def add_to_held_out(self, draft: ReasoningTaskDraft) -> int:
        """Add validated task examples to held-out pool.

        Args:
            draft: Validated task draft

        Returns:
            Number of examples added
        """
        if draft.status != "validated":
            logger.warning("Only validated tasks should be added to held-out pool")

        from .evaluation import get_held_out_manager

        manager = get_held_out_manager()
        added = 0

        for i, ex in enumerate(draft.examples):
            query_id = await manager.add_query(
                input_prompt=ex.input,
                expected_output=ex.output,
                context=draft.description,
                domain="reasoning",
                category=draft.tags[0].lower().replace(" ", "_") if draft.tags else "reasoning",
                difficulty=0.6,
                source_type="local_authored",
                source_id=f"{draft.slug}_{i}",
            )
            if query_id:
                added += 1

        logger.info(f"Added {added} examples from {draft.name} to held-out pool")
        return added

    def export_for_submission(self, draft: ReasoningTaskDraft) -> dict[str, str]:
        """Export task for upstream submission.

        Args:
            draft: Task to export

        Returns:
            Dict with 'json' and 'markdown' content
        """
        return {
            "json": json.dumps(draft.to_json(), indent=2),
            "markdown": draft.to_markdown(),
            "slug": draft.slug,
        }


# Module-level singleton
_author: Optional[TaskAuthor] = None


async def get_task_author() -> TaskAuthor:
    """Get or create the TaskAuthor singleton.

    Returns:
        TaskAuthor instance
    """
    global _author
    if _author is None:
        _author = TaskAuthor()
    return _author


def reset_task_author() -> None:
    """Reset the author singleton (for testing)."""
    global _author
    _author = None
