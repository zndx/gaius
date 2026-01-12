"""GPU Makespan Scheduling with OR-Tools.

This module provides optimal GPU allocation scheduling using Google OR-Tools
CP-SAT solver. It models the problem as a job shop scheduling problem where:

- Machines = GPUs (6x RTX 4090)
- Jobs = Model endpoints (orchestrator, instruct, reasoning)
- Operations = Start/stop endpoints, serve inference
- Objective = Minimize makespan (total transition time)

Usage:
    from gaius.engine.scheduling import MakespanScheduler, SchedulingTask

    scheduler = MakespanScheduler(total_gpus=6)

    current = [
        SchedulingTask("instruct", "instruct", "model", required_gpus=4, fixed_gpu_ids=[0,1,2,3]),
    ]

    target = [
        SchedulingTask("reasoning", "reasoning", "model", required_gpus=4),
    ]

    result = scheduler.plan_transition(current, target)
    if result.success:
        for step in result.plan.steps:
            await execute_step(step)
"""

from .types import (
    TransitionType,
    SchedulingTask,
    TransitionStep,
    TransitionPlan,
    SchedulingResult,
)
from .makespan_scheduler import (
    MakespanScheduler,
    ORTOOLS_AVAILABLE,
    LOAD_TIME_MS,
    UNLOAD_TIME_MS,
)

__all__ = [
    # Types
    "TransitionType",
    "SchedulingTask",
    "TransitionStep",
    "TransitionPlan",
    "SchedulingResult",
    # Scheduler
    "MakespanScheduler",
    "ORTOOLS_AVAILABLE",
    # Constants
    "LOAD_TIME_MS",
    "UNLOAD_TIME_MS",
]
