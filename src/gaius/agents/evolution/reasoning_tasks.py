"""Integration with Nous Research Open-Reasoning-Tasks.

Loads reasoning tasks from the NousResearch/Open-Reasoning-Tasks repository
to populate the held-out evaluation pool with high-quality, diverse tasks.

Repository: https://github.com/NousResearch/Open-Reasoning-Tasks
Format: JSON files with name, description, examples, and tags

Usage:
    from gaius.agents.evolution.reasoning_tasks import (
        load_reasoning_tasks,
        populate_held_out_from_reasoning_tasks,
    )

    # Load tasks from repo
    tasks = await load_reasoning_tasks()

    # Populate held-out pool
    count = await populate_held_out_from_reasoning_tasks(max_tasks=100)
    print(f"Added {count} reasoning tasks to held-out pool")
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import aiohttp

from .engine import TaskItem

logger = logging.getLogger(__name__)

# Repository URLs
REPO_RAW_BASE = "https://raw.githubusercontent.com/NousResearch/Open-Reasoning-Tasks/main"
TASKS_JSON_URL = f"{REPO_RAW_BASE}/tasks-json"
TASK_LIST_URL = f"{REPO_RAW_BASE}/tasks.md"

# Local cache path
CACHE_DIR = Path.home() / ".cache" / "gaius" / "reasoning-tasks"


@dataclass
class ReasoningTask:
    """A reasoning task from the Open-Reasoning-Tasks repository."""

    name: str
    description: str
    examples: list[dict[str, str]]  # List of {input, output}
    tags: list[str]
    modality: str = "Text only"
    citations: Optional[str] = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ReasoningTask":
        """Parse from JSON, handling nested example format.

        The repo format nests examples: [[{input, output}], [{input, output}], ...]
        We flatten this to: [{input, output}, {input, output}, ...]
        """
        raw_examples = data.get("examples", [])
        examples = []

        for item in raw_examples:
            # Handle nested list format: [[{input, output}]]
            if isinstance(item, list) and item:
                for subitem in item:
                    if isinstance(subitem, dict):
                        examples.append(subitem)
            elif isinstance(item, dict):
                examples.append(item)

        return cls(
            name=data.get("name", "unknown"),
            description=data.get("description", ""),
            examples=examples,
            tags=data.get("tags", []),
            modality=data.get("modality", "Text only"),
            citations=data.get("citations"),
        )

    @property
    def category(self) -> str:
        """Derive category from tags."""
        if not self.tags:
            return "reasoning"
        return self.tags[0].lower().replace(" ", "_")

    def to_task_items(self) -> list[TaskItem]:
        """Convert to TaskItem instances for evolution."""
        items = []
        for i, example in enumerate(self.examples):
            items.append(TaskItem(
                id=f"{self.name.lower().replace(' ', '_')}_{i}",
                prompt=example.get("input", ""),
                domain="reasoning",
                category=self.category,
                expected_output=example.get("output"),
                context=self.description,
                evaluation_criteria=f"Task: {self.name}. Tags: {', '.join(self.tags)}",
            ))
        return items


async def fetch_task_json(task_name: str) -> Optional[dict[str, Any]]:
    """Fetch a single task JSON from the repository.

    Args:
        task_name: Task filename (without .json extension)

    Returns:
        Parsed JSON dict or None if fetch failed
    """
    url = f"{TASKS_JSON_URL}/{task_name}.json"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    # GitHub raw URLs return text/plain, so allow any content type
                    return await response.json(content_type=None)
                else:
                    logger.debug(f"Failed to fetch {url}: {response.status}")
                    return None
    except Exception as e:
        logger.debug(f"Error fetching {url}: {e}")
        return None


async def list_available_tasks() -> list[str]:
    """List available task names from the repository.

    Returns:
        List of task filenames (without .json extension)
    """
    # Try to fetch the task list markdown
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TASK_LIST_URL, timeout=30) as response:
                if response.status != 200:
                    return _get_default_task_list()

                content = await response.text()

                # Parse task names from markdown table
                # Format: | [Task Name](link) | Description | Tags |
                tasks = []
                for line in content.split("\n"):
                    if line.startswith("|") and "[" in line:
                        # Extract task name from markdown link
                        start = line.find("[") + 1
                        end = line.find("]")
                        if start > 0 and end > start:
                            task_name = line[start:end]
                            # Convert to filename format
                            filename = task_name.lower().replace(" ", "-")
                            tasks.append(filename)

                return tasks if tasks else _get_default_task_list()

    except Exception as e:
        logger.debug(f"Error listing tasks: {e}")
        return _get_default_task_list()


def _get_default_task_list() -> list[str]:
    """Default list of known reasoning tasks."""
    return [
        "describing-spatial-relationships",
        "logical-fallacy-detection",
        "causal-chain-construction",
        "analogical-reasoning",
        "temporal-sequence-ordering",
        "argument-evaluation",
        "counterfactual-reasoning",
        "probabilistic-inference",
        "pattern-recognition-in-sequences",
        "diagrammatic-reasoning",
        "ethical-dilemma-analysis",
        "hypothesis-generation",
        "abstract-reasoning",
        "deductive-reasoning",
        "inductive-reasoning",
        "abductive-reasoning",
        "multi-step-mathematical-reasoning",
        "constraint-satisfaction",
        "classification-reasoning",
        "comparative-analysis",
    ]


async def load_reasoning_tasks(
    max_tasks: int = 50,
    use_cache: bool = True,
) -> list[ReasoningTask]:
    """Load reasoning tasks from the repository.

    Args:
        max_tasks: Maximum number of tasks to load
        use_cache: Whether to use local cache

    Returns:
        List of ReasoningTask objects
    """
    tasks = []

    # Check cache first
    if use_cache:
        cached = _load_from_cache()
        if cached:
            logger.info(f"Loaded {len(cached)} tasks from cache")
            return cached[:max_tasks]

    # Get task list
    task_names = await list_available_tasks()
    logger.info(f"Found {len(task_names)} available reasoning tasks")

    # Fetch tasks
    for task_name in task_names[:max_tasks]:
        data = await fetch_task_json(task_name)
        if data:
            try:
                # Use from_json to handle nested example format
                task = ReasoningTask.from_json(data)
                if task.examples:  # Only add if has examples
                    tasks.append(task)
            except Exception as e:
                logger.debug(f"Error parsing task {task_name}: {e}")

    # Cache results
    if use_cache and tasks:
        _save_to_cache(tasks)

    logger.info(f"Loaded {len(tasks)} reasoning tasks")
    return tasks


def _load_from_cache() -> Optional[list[ReasoningTask]]:
    """Load tasks from local cache."""
    cache_file = CACHE_DIR / "tasks.json"
    if not cache_file.exists():
        return None

    try:
        # Check cache age (1 day max)
        import time
        age = time.time() - cache_file.stat().st_mtime
        if age > 86400:  # 24 hours
            return None

        with open(cache_file) as f:
            data = json.load(f)

        return [
            ReasoningTask(**task_data)
            for task_data in data
        ]
    except Exception as e:
        logger.debug(f"Cache load error: {e}")
        return None


def _save_to_cache(tasks: list[ReasoningTask]) -> None:
    """Save tasks to local cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / "tasks.json"

        data = [
            {
                "name": t.name,
                "description": t.description,
                "examples": t.examples,
                "tags": t.tags,
                "modality": t.modality,
                "citations": t.citations,
            }
            for t in tasks
        ]

        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)

        logger.debug(f"Cached {len(tasks)} tasks to {cache_file}")
    except Exception as e:
        logger.debug(f"Cache save error: {e}")


async def populate_held_out_from_reasoning_tasks(
    max_tasks: int = 50,
    max_examples_per_task: int = 3,
) -> int:
    """Populate the held-out pool with reasoning tasks.

    Loads tasks from NousResearch/Open-Reasoning-Tasks and adds
    their examples to the held-out evaluation pool.

    Args:
        max_tasks: Maximum task types to load
        max_examples_per_task: Maximum examples per task type

    Returns:
        Number of examples added
    """
    from .evaluation import get_held_out_manager

    manager = get_held_out_manager()
    tasks = await load_reasoning_tasks(max_tasks)

    added = 0
    for task in tasks:
        for i, example in enumerate(task.examples[:max_examples_per_task]):
            input_prompt = example.get("input", "")
            if not input_prompt:
                continue

            query_id = await manager.add_query(
                input_prompt=input_prompt,
                expected_output=example.get("output"),
                context=task.description,
                domain="reasoning",
                category=task.category,
                difficulty=0.6,  # Reasoning tasks are typically challenging
                source_type="nous_reasoning",
                source_id=f"{task.name}_{i}",
            )

            if query_id:
                added += 1

    logger.info(f"Added {added} reasoning task examples to held-out pool")
    return added


async def get_task_items_for_agent(
    agent_type: str,
    count: int = 10,
) -> list[TaskItem]:
    """Get reasoning task items suitable for a specific agent type.

    Maps agent roles to appropriate reasoning task categories:
    - leader: strategic reasoning, planning
    - critic: argument evaluation, logical fallacy detection
    - risk: probabilistic inference, counterfactual reasoning
    - opportunity: pattern recognition, hypothesis generation
    - domain: classification, comparative analysis

    Args:
        agent_type: Agent role (leader, critic, risk, etc.)
        count: Number of items to return

    Returns:
        List of TaskItem for evaluation
    """
    # Map agents to suitable task categories
    agent_task_map = {
        "leader": [
            "strategic-planning",
            "multi-step-reasoning",
            "causal-chain-construction",
            "decision-making",
        ],
        "critic": [
            "logical-fallacy-detection",
            "argument-evaluation",
            "deductive-reasoning",
            "error-identification",
        ],
        "risk": [
            "probabilistic-inference",
            "counterfactual-reasoning",
            "risk-assessment",
            "uncertainty-quantification",
        ],
        "opportunity": [
            "pattern-recognition",
            "hypothesis-generation",
            "analogical-reasoning",
            "trend-identification",
        ],
        "domain": [
            "classification-reasoning",
            "comparative-analysis",
            "concept-abstraction",
            "knowledge-integration",
        ],
    }

    preferred_categories = agent_task_map.get(agent_type, [])

    tasks = await load_reasoning_tasks(max_tasks=100)
    items = []

    # First try preferred categories
    for task in tasks:
        if any(cat in task.category for cat in preferred_categories):
            items.extend(task.to_task_items())
            if len(items) >= count:
                break

    # If not enough, add general reasoning tasks
    if len(items) < count:
        for task in tasks:
            if task.category not in [item.category for item in items]:
                items.extend(task.to_task_items())
                if len(items) >= count:
                    break

    return items[:count]
