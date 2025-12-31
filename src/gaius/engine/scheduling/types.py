"""Type definitions for GPU makespan scheduling.

This module defines the data structures used by the MakespanScheduler
to model GPU workload transitions as a job shop scheduling problem.

Machines = GPUs
Jobs = Model endpoints (orchestrator, fast, coding, reasoning)
Operations = Start/stop endpoints
Objective = Minimize makespan (total transition time)
"""

from dataclasses import dataclass, field
from enum import Enum


class TransitionType(Enum):
    """Types of GPU state transitions."""

    STOP_ENDPOINT = "stop"
    START_ENDPOINT = "start"


@dataclass
class SchedulingTask:
    """A GPU workload with resource requirements.

    Represents a model endpoint that requires GPU resources. Used by
    the scheduler to determine optimal allocation and eviction plans.

    Attributes:
        task_id: Unique identifier for this task
        endpoint_name: Name of the endpoint (e.g., "fast", "coding", "reasoning")
        model_id: HuggingFace model ID or path
        required_gpus: Number of GPUs needed for this task
        salience: Priority weight for objective function (higher = more important)
        capability: TaskType value this endpoint provides (e.g., "REASONING")
        prefer_contiguous: Whether GPUs should be contiguous (for tensor parallelism)
        fixed_gpu_ids: If set, task must use exactly these GPUs (for current allocations)
        is_current: Whether this task is already running
        memory_mb: Estimated VRAM usage in MB
    """

    task_id: str
    endpoint_name: str
    model_id: str
    required_gpus: int
    salience: float = 1.0
    capability: str | None = None
    prefer_contiguous: bool = True
    fixed_gpu_ids: list[int] | None = None
    is_current: bool = False
    memory_mb: int = 0


@dataclass
class TransitionStep:
    """Single step in a transition plan.

    Represents one atomic operation in the GPU state transition,
    either stopping an endpoint (freeing GPUs) or starting one (allocating GPUs).

    Attributes:
        step_id: Unique identifier within the plan
        transition_type: STOP_ENDPOINT or START_ENDPOINT
        endpoint_name: Which endpoint this step affects
        gpu_ids: GPUs involved in this step
        estimated_duration_ms: Expected time to complete
        depends_on: List of step_ids that must complete before this step
    """

    step_id: int
    transition_type: TransitionType
    endpoint_name: str
    gpu_ids: list[int]
    estimated_duration_ms: int
    depends_on: list[int] = field(default_factory=list)


@dataclass
class TransitionPlan:
    """Complete GPU transition plan.

    Contains the ordered sequence of steps to transition from
    current GPU state to target state, with makespan optimization.

    Attributes:
        plan_id: Unique identifier for this plan
        steps: Ordered list of transition steps
        total_makespan_ms: Optimized total transition time
        evicted_endpoints: Endpoints that were stopped
        target_endpoints: Endpoints that will be running after transition
        gpu_assignments: Mapping of endpoint -> GPU IDs after transition
        restore_plan: Endpoints to restart after workload completes
    """

    plan_id: str
    steps: list[TransitionStep]
    total_makespan_ms: int
    evicted_endpoints: list[str]
    target_endpoints: list[str]
    gpu_assignments: dict[str, list[int]]
    restore_plan: list[str]


@dataclass
class SchedulingResult:
    """Result of makespan optimization.

    Returned by MakespanScheduler.plan_transition() with either
    a feasible plan or an error explaining why planning failed.

    Attributes:
        success: Whether a feasible plan was found
        plan: The transition plan (if success=True)
        error: Error message with Guru Meditation code (if success=False)
        solver_status: OR-Tools solver status string
        solve_time_ms: Time spent in the solver
    """

    success: bool
    plan: TransitionPlan | None = None
    error: str | None = None
    solver_status: str = ""
    solve_time_ms: int = 0
