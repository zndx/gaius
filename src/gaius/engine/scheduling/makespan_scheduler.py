"""OR-Tools CP-SAT scheduler for GPU makespan optimization.

This module implements a job shop scheduling solver using Google OR-Tools
CP-SAT (Constraint Programming - Satisfiability) solver. The problem is:

Given:
- Current GPU allocations (which endpoints are running on which GPUs)
- Target GPU allocations (which endpoints should be running)

Find:
- Optimal eviction order (which endpoints to stop)
- Optimal allocation order (which endpoints to start)
- GPU assignments that satisfy contiguity constraints
- Minimum makespan (total transition time)

The solver uses interval variables to model timing and boolean variables
to model GPU-to-task assignments.
"""

import logging
import time
from typing import TYPE_CHECKING, Any

from .types import (
    SchedulingTask,
    TransitionStep,
    TransitionPlan,
    SchedulingResult,
    TransitionType,
)

logger = logging.getLogger(__name__)

# Import OR-Tools with availability check - fail-fast if not available
try:
    from ortools.sat.python import cp_model  # type: ignore[import-not-found] - ortools is optional dependency for scheduling

    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False
    cp_model = None  # type: ignore[assignment] - Module or None for optional dependency

# Import types for static analysis when OR-Tools is available
if TYPE_CHECKING:
    from ortools.sat.python.cp_model import CpModel, CpSolver, CpSolverStatus, IntVar  # type: ignore[import-not-found] - ortools is optional dependency for scheduling


# Model load/unload time estimates (empirical, in milliseconds)
# These could be refined with actual measurements over time
LOAD_TIME_MS: dict[str, int] = {
    "orchestrator": 45_000,  # 45s for 8B model on 2 GPUs
    "thinking": 60_000,  # 60s for Qwen3.8-27B on 4 GPUs
    "reasoning": 120_000,  # 120s for 32B on 4 GPUs
    "cap_reasoning": 120_000,  # Same as reasoning
    "embedding": 20_000,  # 20s for embedding model
}

UNLOAD_TIME_MS: dict[str, int] = {
    "orchestrator": 10_000,
    "thinking": 10_000,
    "reasoning": 15_000,
    "cap_reasoning": 15_000,
    "embedding": 5_000,
}


class MakespanScheduler:
    """CP-SAT based GPU scheduler with salience-weighted objectives.

    This scheduler models GPU allocation as a constraint satisfaction problem:

    Decision Variables:
    - x[task, gpu] = 1 if task uses GPU
    - start_time[task] = when task starts loading
    - end_time[task] = when task finishes loading

    Constraints:
    - Each task gets exactly required_gpus GPUs
    - Each GPU assigned to at most one task
    - Contiguous GPUs for tensor parallelism (TP>1)
    - Precedence: can't start until stopped tasks free GPUs

    Objective:
    - Minimize makespan (max end_time across all start operations)

    Example:
        scheduler = MakespanScheduler(total_gpus=6)

        current = [
            SchedulingTask("thinking", "thinking", "model", 4, fixed_gpu_ids=[0,1,2,3]),
        ]

        target = [
            SchedulingTask("reasoning", "reasoning", "model", 4, prefer_contiguous=True),
        ]

        result = scheduler.plan_transition(current, target)
        if result.success:
            print(f"Makespan: {result.plan.total_makespan_ms}ms")
            print(f"GPU assignments: {result.plan.gpu_assignments}")
    """

    def __init__(
        self,
        total_gpus: int = 6,
        reserved_gpus: set[int] | None = None,
        max_solve_time_s: float = 5.0,
    ):
        """Initialize the scheduler.

        Args:
            total_gpus: Total number of GPUs available
            reserved_gpus: Set of GPU IDs that cannot be allocated
            max_solve_time_s: Maximum time for solver (seconds)
        """
        self.total_gpus = total_gpus
        self.reserved_gpus = reserved_gpus or set()
        self.max_solve_time_s = max_solve_time_s

    def plan_transition(
        self,
        current_tasks: list[SchedulingTask],
        target_tasks: list[SchedulingTask],
    ) -> SchedulingResult:
        """Plan optimal GPU transition using CP-SAT.

        This is the main entry point. Given the current state and desired
        target state, compute an optimal transition plan.

        Args:
            current_tasks: Tasks currently running (with fixed_gpu_ids set)
            target_tasks: Tasks we want running after transition

        Returns:
            SchedulingResult with plan if feasible, error otherwise

        Raises:
            RuntimeError: If OR-Tools is not available (fail-fast)
        """
        if not ORTOOLS_AVAILABLE:
            raise RuntimeError(
                "OR-Tools not available.\n"
                "  Install: uv sync --extra scheduler\n"
                "  Guru Meditation: #SCH.00000001.NOORDEPS"
            )

        assert cp_model is not None  # Guaranteed by ORTOOLS_AVAILABLE check

        start_time = time.time()
        model = cp_model.CpModel()

        # Determine what needs to change
        current_by_name = {t.endpoint_name: t for t in current_tasks}
        target_by_name = {t.endpoint_name: t for t in target_tasks}

        to_stop = [t for t in current_tasks if t.endpoint_name not in target_by_name]
        to_start = [t for t in target_tasks if t.endpoint_name not in current_by_name]
        to_keep = [t for t in current_tasks if t.endpoint_name in target_by_name]

        logger.info(
            f"Planning transition: stop={[t.endpoint_name for t in to_stop]}, "
            f"start={[t.endpoint_name for t in to_start]}, "
            f"keep={[t.endpoint_name for t in to_keep]}"
        )

        # GPUs held by kept endpoints (cannot be reassigned)
        keep_gpus: set[int] = set()
        for task in to_keep:
            if task.fixed_gpu_ids:
                keep_gpus.update(task.fixed_gpu_ids)

        # GPUs that will be available after stops complete
        available_gpus = [
            g
            for g in range(self.total_gpus)
            if g not in self.reserved_gpus and g not in keep_gpus
        ]

        logger.debug(
            f"Available GPUs after transition: {available_gpus}, "
            f"reserved: {self.reserved_gpus}, kept: {keep_gpus}"
        )

        # Check if we have enough GPUs
        total_required = sum(t.required_gpus for t in to_start)
        if total_required > len(available_gpus):
            return SchedulingResult(
                success=False,
                error=f"Not enough GPUs. Need {total_required}, have {len(available_gpus)} available.\n"
                f"  Current: {[f'{t.endpoint_name}={t.fixed_gpu_ids}' for t in current_tasks]}\n"
                f"  Target: {[f'{t.endpoint_name}:{t.required_gpus}' for t in to_start]}\n"
                f"  Guru Meditation: #SCH.00000002.NOFEASIBLE",
                solver_status="INFEASIBLE_RESOURCES",
                solve_time_ms=int((time.time() - start_time) * 1000),
            )

        # If nothing to start, just plan the stops
        if not to_start:
            return self._plan_stops_only(to_stop, start_time)

        # Build CP-SAT model
        # Decision variables: x[task_id, gpu] = 1 if task uses GPU
        x: dict[tuple[str, int], "IntVar"] = {}
        for task in to_start:
            for gpu in available_gpus:
                x[task.task_id, gpu] = model.NewBoolVar(f"x_{task.task_id}_{gpu}")

        # Constraint: Each task gets exactly required_gpus
        for task in to_start:
            model.Add(
                sum(x[task.task_id, g] for g in available_gpus) == task.required_gpus
            )

        # Constraint: Each GPU assigned to at most one task
        for gpu in available_gpus:
            model.Add(sum(x[task.task_id, gpu] for task in to_start) <= 1)

        # Constraint: Contiguous GPUs for tensor parallelism
        for task in to_start:
            if task.required_gpus > 1 and task.prefer_contiguous:
                self._add_contiguity_constraint(model, x, task, available_gpus)

        # Timing variables for makespan calculation
        HORIZON = 1_000_000  # 1000 seconds in ms

        # Stop end times (when GPU memory is freed)
        stop_end: dict[str, "IntVar"] = {}
        for task in to_stop:
            duration = UNLOAD_TIME_MS.get(task.endpoint_name, 10_000)
            stop_end[task.task_id] = model.NewIntVar(
                0, HORIZON, f"stop_end_{task.task_id}"
            )
            # Stops start at time 0 and take their duration
            model.Add(stop_end[task.task_id] >= duration)

        # Start begin/end times
        start_begin: dict[str, "IntVar"] = {}
        start_end: dict[str, "IntVar"] = {}
        for task in to_start:
            duration = LOAD_TIME_MS.get(task.endpoint_name, 60_000)
            start_begin[task.task_id] = model.NewIntVar(
                0, HORIZON, f"start_begin_{task.task_id}"
            )
            start_end[task.task_id] = model.NewIntVar(
                0, HORIZON, f"start_end_{task.task_id}"
            )
            model.Add(start_end[task.task_id] == start_begin[task.task_id] + duration)

        # Precedence: Can't start until required GPUs are freed
        for task in to_start:
            for gpu in available_gpus:
                for stopped in to_stop:
                    if stopped.fixed_gpu_ids and gpu in stopped.fixed_gpu_ids:
                        # If we're using this GPU, must wait for stop to complete
                        model.Add(
                            start_begin[task.task_id] >= stop_end[stopped.task_id]
                        ).OnlyEnforceIf(x[task.task_id, gpu])

        # Objective: Minimize makespan (when all starts complete)
        makespan = model.NewIntVar(0, HORIZON, "makespan")
        for task in to_start:
            model.Add(makespan >= start_end[task.task_id])

        model.Minimize(makespan)

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.max_solve_time_s
        status = solver.Solve(model)

        solve_time_ms = int((time.time() - start_time) * 1000)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return SchedulingResult(
                success=False,
                error=f"No feasible schedule found. Status: {solver.StatusName(status)}\n"
                f"  Guru Meditation: #SCH.00000002.NOFEASIBLE",
                solver_status=solver.StatusName(status),
                solve_time_ms=solve_time_ms,
            )

        # Extract solution
        return self._extract_solution(
            solver, status, x, to_stop, to_start, to_keep, available_gpus, solve_time_ms
        )

    def _add_contiguity_constraint(
        self,
        model: "CpModel",
        x: dict[tuple[str, int], "IntVar"],
        task: SchedulingTask,
        available_gpus: list[int],
    ) -> None:
        """Add constraint requiring contiguous GPU assignment.

        For tensor parallelism (TP>1), GPUs must be contiguous for
        efficient NVLink communication.

        Args:
            model: The CP-SAT model
            x: Decision variables x[task_id, gpu]
            task: The task requiring contiguous GPUs
            available_gpus: List of available GPU IDs
        """
        available_set = set(available_gpus)
        valid_starts: list[int] = []

        # Find all valid contiguous ranges
        for start in available_gpus:
            if all((start + i) in available_set for i in range(task.required_gpus)):
                valid_starts.append(start)

        if not valid_starts:
            logger.warning(
                f"No contiguous range of {task.required_gpus} GPUs available for {task.endpoint_name}"
            )
            return  # Will be infeasible

        # Auxiliary variable: which contiguous block is selected
        y: dict[int, "IntVar"] = {
            s: model.NewBoolVar(f"contig_{task.task_id}_{s}") for s in valid_starts
        }
        model.AddExactlyOne(y.values())

        # If block starting at s is selected, use GPUs s, s+1, ..., s+required-1
        for start in valid_starts:
            for offset in range(task.required_gpus):
                model.Add(x[task.task_id, start + offset] == 1).OnlyEnforceIf(y[start])

    def _plan_stops_only(
        self, to_stop: list[SchedulingTask], start_time: float
    ) -> SchedulingResult:
        """Create a plan when only stops are needed (no starts)."""
        steps: list[TransitionStep] = []

        for i, task in enumerate(to_stop):
            duration = UNLOAD_TIME_MS.get(task.endpoint_name, 10_000)
            steps.append(
                TransitionStep(
                    step_id=i,
                    transition_type=TransitionType.STOP_ENDPOINT,
                    endpoint_name=task.endpoint_name,
                    gpu_ids=task.fixed_gpu_ids or [],
                    estimated_duration_ms=duration,
                    depends_on=[],
                )
            )

        # Makespan is max of stop durations (they run in parallel)
        makespan = max(
            UNLOAD_TIME_MS.get(t.endpoint_name, 10_000) for t in to_stop
        ) if to_stop else 0

        plan = TransitionPlan(
            plan_id=f"transition-{int(time.time())}",
            steps=steps,
            total_makespan_ms=makespan,
            evicted_endpoints=[t.endpoint_name for t in to_stop],
            target_endpoints=[],
            gpu_assignments={},
            restore_plan=[t.endpoint_name for t in to_stop],
        )

        return SchedulingResult(
            success=True,
            plan=plan,
            solver_status="STOPS_ONLY",
            solve_time_ms=int((time.time() - start_time) * 1000),
        )

    def _extract_solution(
        self,
        solver: "CpSolver",
        status: "CpSolverStatus",
        x: dict[tuple[str, int], "IntVar"],
        to_stop: list[SchedulingTask],
        to_start: list[SchedulingTask],
        to_keep: list[SchedulingTask],
        available_gpus: list[int],
        solve_time_ms: int,
    ) -> SchedulingResult:
        """Extract the solution from the solved model."""
        steps: list[TransitionStep] = []
        step_id = 0

        # Stop steps (can run in parallel - no dependencies)
        for task in to_stop:
            duration = UNLOAD_TIME_MS.get(task.endpoint_name, 10_000)
            steps.append(
                TransitionStep(
                    step_id=step_id,
                    transition_type=TransitionType.STOP_ENDPOINT,
                    endpoint_name=task.endpoint_name,
                    gpu_ids=task.fixed_gpu_ids or [],
                    estimated_duration_ms=duration,
                    depends_on=[],
                )
            )
            step_id += 1

        # Start steps with computed GPU assignments
        gpu_assignments: dict[str, list[int]] = {}

        # Include kept endpoints in assignments
        for task in to_keep:
            if task.fixed_gpu_ids:
                gpu_assignments[task.endpoint_name] = task.fixed_gpu_ids

        for task in to_start:
            # Extract assigned GPUs from solver
            assigned = sorted(
                [g for g in available_gpus if solver.Value(x[task.task_id, g]) == 1]
            )
            gpu_assignments[task.endpoint_name] = assigned

            duration = LOAD_TIME_MS.get(task.endpoint_name, 60_000)

            # Compute dependencies: which stops free our GPUs
            deps: list[int] = []
            for i, stopped in enumerate(to_stop):
                if stopped.fixed_gpu_ids and set(stopped.fixed_gpu_ids) & set(assigned):
                    deps.append(i)

            steps.append(
                TransitionStep(
                    step_id=step_id,
                    transition_type=TransitionType.START_ENDPOINT,
                    endpoint_name=task.endpoint_name,
                    gpu_ids=assigned,
                    estimated_duration_ms=duration,
                    depends_on=deps,
                )
            )
            step_id += 1

            logger.info(
                f"Assigned {task.endpoint_name} to GPUs {assigned} "
                f"(contiguous={task.prefer_contiguous}, deps={deps})"
            )

        # Get makespan from solver
        makespan_var = solver.ObjectiveValue()

        plan = TransitionPlan(
            plan_id=f"transition-{int(time.time())}",
            steps=steps,
            total_makespan_ms=int(makespan_var),
            evicted_endpoints=[t.endpoint_name for t in to_stop],
            target_endpoints=[t.endpoint_name for t in to_start]
            + [t.endpoint_name for t in to_keep],
            gpu_assignments=gpu_assignments,
            restore_plan=[t.endpoint_name for t in to_stop],
        )

        logger.info(
            f"Found feasible plan: makespan={plan.total_makespan_ms}ms, "
            f"evicted={plan.evicted_endpoints}, "
            f"assignments={gpu_assignments}"
        )

        return SchedulingResult(
            success=True,
            plan=plan,
            solver_status=solver.StatusName(status),
            solve_time_ms=solve_time_ms,
        )
