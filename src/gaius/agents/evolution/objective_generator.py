"""Objective-based task generator for evolution.

Generates TaskItems from KB objectives for the evolution engine.
This bridges the RASE objective system to the Atropos-style training loop.

Key concepts:
- Objectives define what we want to achieve and how to verify it
- TaskItems are training examples derived from objectives
- Verification provides intrinsic reward signal

Usage:
    generator = ObjectiveTaskGenerator(kb_root="build/dev")

    # Generate tasks from all objectives
    tasks = await generator.generate_tasks()

    # Use in evolution engine
    engine = await get_engine()
    for task in tasks:
        result = await engine.run_evolution_cycle(agent_id, tasks=[task])
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .engine import TaskItem

logger = logging.getLogger(__name__)


@dataclass
class ObjectiveTask:
    """A task derived from a KB objective.

    Extends TaskItem with objective-specific metadata for
    traceability and intrinsic verification.
    """

    objective_name: str
    objective_path: str
    gate_levels: list[str] = field(default_factory=list)
    document_path: str | None = None

    # Reference to RASE objective for verification
    verification_case_id: str | None = None


def objective_to_task_item(
    objective_name: str,
    objective_path: str,
    document_path: str | None,
    domain: str = "kb",
) -> TaskItem:
    """Convert an objective to a TaskItem for evolution.

    The task prompt instructs the agent to verify the objective,
    and the evaluation uses intrinsic verification as the reward signal.

    Args:
        objective_name: Name of the objective
        objective_path: Path to objective file
        document_path: Path to document to verify (if applicable)
        domain: Domain category

    Returns:
        TaskItem ready for evolution engine
    """
    task_id = f"obj_{objective_name}_{uuid.uuid4().hex[:8]}"

    # Build prompt that instructs agent to verify objective
    if document_path:
        prompt = (
            f"Verify that the document at '{document_path}' satisfies "
            f"the '{objective_name}' objective.\n\n"
            f"The objective is defined at '{objective_path}' and includes "
            f"verification gates for syntactic, semantic, and empirical checks.\n\n"
            f"Analyze the document and determine if it passes all gates. "
            f"For each gate, explain whether it passes or fails and why."
        )
    else:
        prompt = (
            f"Verify the '{objective_name}' objective against the current KB state.\n\n"
            f"The objective is defined at '{objective_path}' and specifies "
            f"what the KB should contain and how to verify it.\n\n"
            f"Analyze the objective gates and determine if the current state "
            f"satisfies all requirements. Report the verification result."
        )

    evaluation_criteria = (
        f"Task success is determined by intrinsic verification of the objective. "
        f"The agent output is evaluated against the actual gate results:\n"
        f"- Gate-accurate: Agent's assessment matches actual gate outcomes\n"
        f"- Reasoning-quality: Explanation is clear and correct\n"
        f"- Completeness: All gates are addressed\n\n"
        f"The final score combines gate accuracy (60%) with reasoning quality (40%)."
    )

    return TaskItem(
        id=task_id,
        prompt=prompt,
        domain=domain,
        category="objective_verification",
        expected_output=None,  # Determined by intrinsic verification
        context=f"objective:{objective_name}",
        evaluation_criteria=evaluation_criteria,
        reference_score=None,  # Will be computed from verification
    )


class ObjectiveTaskGenerator:
    """Generates training tasks from KB objectives.

    Scans the KB for objective documents and generates TaskItems
    that can be used for agent evolution. The key innovation is
    using intrinsic verification as the reward signal rather than
    external model evaluation.

    Design:
    1. Load objectives from KB (current/objectives/*.md)
    2. For each objective, generate verification tasks
    3. Optionally pair with target documents to verify
    4. Return TaskItems for evolution engine
    """

    def __init__(
        self,
        kb_root: str = "build/dev",
        objectives_path: str = "current/objectives",
        max_tasks_per_objective: int = 5,
    ):
        """Initialize the generator.

        Args:
            kb_root: KB root directory
            objectives_path: Path to objectives within KB
            max_tasks_per_objective: Max tasks to generate per objective
        """
        self.kb_root = Path(kb_root)
        self.objectives_path = objectives_path
        self.max_tasks_per_objective = max_tasks_per_objective

    async def list_objectives(self) -> list[dict[str, Any]]:
        """List all objectives in the KB.

        Returns:
            List of objective metadata dicts
        """
        objectives_dir = self.kb_root / self.objectives_path
        if not objectives_dir.exists():
            logger.warning(f"Objectives directory not found: {objectives_dir}")
            return []

        objectives = []
        for md_file in objectives_dir.glob("*.md"):
            if md_file.name.startswith("_"):  # Skip private files
                continue

            try:
                # Parse frontmatter to get objective metadata
                content = md_file.read_text()
                from gaius.storage.filesystem import parse_frontmatter

                frontmatter, body = parse_frontmatter(content)

                objectives.append({
                    "name": frontmatter.get("name", md_file.stem),
                    "path": str(md_file.relative_to(self.kb_root)),
                    "type": frontmatter.get("type", "unknown"),
                    "domain": frontmatter.get("domain", "kb"),
                    "priority": frontmatter.get("priority", "normal"),
                    "gates": frontmatter.get("gates", []),
                })

            except Exception as e:
                logger.warning(f"Failed to parse objective {md_file}: {e}")
                continue

        return objectives

    async def find_target_documents(
        self,
        objective: dict[str, Any],
    ) -> list[str]:
        """Find documents that should be verified against an objective.

        Uses the objective's domain and allowed_dirs to find candidates.

        Args:
            objective: Objective metadata dict

        Returns:
            List of document paths relative to KB root
        """
        candidates = []
        domain = objective.get("domain", "kb")

        # Domain-specific search patterns
        if domain == "kb":
            # KB objectives apply to various document types
            search_dirs = ["scratch", "current/topics", "current/projects"]
        else:
            search_dirs = [f"current/{domain}"]

        for search_dir in search_dirs:
            dir_path = self.kb_root / search_dir
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                rel_path = str(md_file.relative_to(self.kb_root))
                candidates.append(rel_path)

        # Limit candidates
        return candidates[:10]  # Don't generate too many tasks

    async def generate_tasks(
        self,
        objective_names: list[str] | None = None,
    ) -> list[TaskItem]:
        """Generate TaskItems from objectives.

        Args:
            objective_names: Specific objectives to use (None = all)

        Returns:
            List of TaskItems for evolution
        """
        objectives = await self.list_objectives()

        if objective_names:
            objectives = [o for o in objectives if o["name"] in objective_names]

        tasks = []

        for objective in objectives:
            # Generate task for objective verification
            task = objective_to_task_item(
                objective_name=objective["name"],
                objective_path=objective["path"],
                document_path=None,  # Self-verification first
                domain=objective.get("domain", "kb"),
            )
            tasks.append(task)

            # Generate tasks for document verification
            target_docs = await self.find_target_documents(objective)
            for doc_path in target_docs[:self.max_tasks_per_objective]:
                doc_task = objective_to_task_item(
                    objective_name=objective["name"],
                    objective_path=objective["path"],
                    document_path=doc_path,
                    domain=objective.get("domain", "kb"),
                )
                tasks.append(doc_task)

        logger.info(
            f"Generated {len(tasks)} tasks from {len(objectives)} objectives"
        )
        return tasks

    async def get_held_out_tasks(
        self,
        sample_size: int = 10,
    ) -> list[TaskItem]:
        """Get held-out tasks for evaluation.

        Returns a sample of tasks that weren't used for training.

        Args:
            sample_size: Number of tasks to return

        Returns:
            List of TaskItems for evaluation
        """
        all_tasks = await self.generate_tasks()

        # Use every Nth task for evaluation
        # This ensures held-out tasks come from different objectives
        held_out = all_tasks[::3][:sample_size]

        logger.info(f"Selected {len(held_out)} held-out tasks for evaluation")
        return held_out


# Singleton instance
_generator: ObjectiveTaskGenerator | None = None


def get_objective_generator(
    kb_root: str | None = None,
) -> ObjectiveTaskGenerator:
    """Get or create the objective generator singleton.

    Args:
        kb_root: KB root (only used on first call)

    Returns:
        ObjectiveTaskGenerator instance
    """
    global _generator
    if _generator is None:
        kb_root = kb_root or "build/dev"
        _generator = ObjectiveTaskGenerator(kb_root=kb_root)
    return _generator


__all__ = [
    "ObjectiveTask",
    "objective_to_task_item",
    "ObjectiveTaskGenerator",
    "get_objective_generator",
]
