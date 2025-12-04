"""Evolution module for Agent0-style autonomous self-improvement.

Provides background daemon for evolving agent prompts using:
- Curriculum agent that proposes challenging tasks
- Executor that attempts tasks with tool access
- Symbiotic competition loop for continuous improvement
- Preemption support for interactive requests

Usage:
    from gaius.agents.evolution import EvolutionDaemon, get_evolution_daemon

    daemon = get_evolution_daemon()
    await daemon.start()

    # Daemon runs in background, preempts for interactive requests
    # Manual trigger:
    result = await daemon.force_evolution_cycle("leader")
"""

from .preemption import PreemptedError, PreemptionManager
from .daemon import (
    EvolutionDaemon,
    EvolutionConfig,
    EvolutionCycleResult,
    get_evolution_daemon,
)
from .curriculum import CurriculumAgent, EvolutionTask
from .collector import TrainingCollector

__all__ = [
    "PreemptedError",
    "PreemptionManager",
    "EvolutionDaemon",
    "EvolutionConfig",
    "EvolutionCycleResult",
    "get_evolution_daemon",
    "CurriculumAgent",
    "EvolutionTask",
    "TrainingCollector",
]
