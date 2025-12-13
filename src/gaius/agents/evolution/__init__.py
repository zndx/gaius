"""Evolution module for Agent0-style autonomous self-improvement.

Provides Atropos-compatible RL environment for agent evolution:
- EvolutionEngine: Central loop with proper GPU management
- AgentRunner: Validated inference via engine scheduler
- GaiusEvolutionEnv: Atropos BaseEnv adapter
- EvolutionDaemon: Background processing

All evolution happens in the engine, enabling deployment to
GPU-rich remote environments.

Usage:
    from gaius.agents.evolution import get_evolution_daemon, get_engine

    # Background evolution
    daemon = get_evolution_daemon()
    await daemon.start()

    # Direct engine access
    engine = await get_engine()
    result = await engine.run_evolution_cycle("leader")

    # Atropos-compatible interface
    from gaius.agents.evolution import GaiusEvolutionEnv
    env = GaiusEvolutionEnv("leader")
    item = await env.get_next_item()
"""

from .preemption import PreemptedError, PreemptionManager
from .daemon import (
    EvolutionDaemon,
    EvolutionConfig,
    EvolutionCycleResult,
    get_evolution_daemon,
)
from .runner import AgentRunner, AgentResult, get_runner
from .engine import (
    EvolutionEngine,
    TaskItem,
    Trajectory,
    CycleResult,
    get_engine,
)
from .atropos_env import (
    GaiusEvolutionEnv,
    ScoredDataItem,
    ScoredDataGroup,
    BaseEnv,
)
from .curriculum import CurriculumAgent, EvolutionTask
from .collector import TrainingCollector
from .reasoning_tasks import (
    ReasoningTask,
    load_reasoning_tasks,
    populate_held_out_from_reasoning_tasks,
    get_task_items_for_agent,
)
from .evaluation import (
    HeldOutManager,
    DailyEvaluator,
    ReportGenerator,
    DailyEvalSummary,
    get_held_out_manager,
    get_daily_evaluator,
    get_report_generator,
)
from .task_authoring import (
    ReasoningTaskDraft,
    TaskExample,
    TaskAuthor,
    get_task_author,
)
from .task_ideation import (
    TaskIdeationAgent,
    TaskConcept,
    GapAnalysis,
    get_task_ideation_agent,
)
from .merge_coordinator import (
    MergeCoordinator,
    MergeCoordinatorConfig,
    MergeCycleResult,
    get_merge_coordinator,
)

__all__ = [
    # Core preemption
    "PreemptedError",
    "PreemptionManager",
    # Daemon
    "EvolutionDaemon",
    "EvolutionConfig",
    "EvolutionCycleResult",
    "get_evolution_daemon",
    # Runner (validated inference)
    "AgentRunner",
    "AgentResult",
    "get_runner",
    # Engine (central loop)
    "EvolutionEngine",
    "TaskItem",
    "Trajectory",
    "CycleResult",
    "get_engine",
    # Atropos compatibility
    "GaiusEvolutionEnv",
    "ScoredDataItem",
    "ScoredDataGroup",
    "BaseEnv",
    # Curriculum
    "CurriculumAgent",
    "EvolutionTask",
    "TrainingCollector",
    # Nous Research reasoning tasks
    "ReasoningTask",
    "load_reasoning_tasks",
    "populate_held_out_from_reasoning_tasks",
    "get_task_items_for_agent",
    # Evaluation
    "HeldOutManager",
    "DailyEvaluator",
    "ReportGenerator",
    "DailyEvalSummary",
    "get_held_out_manager",
    "get_daily_evaluator",
    "get_report_generator",
    # Task authoring (for upstream contribution)
    "ReasoningTaskDraft",
    "TaskExample",
    "TaskAuthor",
    "get_task_author",
    # Task ideation (autonomous task generation)
    "TaskIdeationAgent",
    "TaskConcept",
    "GapAnalysis",
    "get_task_ideation_agent",
    # Model merging
    "MergeCoordinator",
    "MergeCoordinatorConfig",
    "MergeCycleResult",
    "get_merge_coordinator",
]
