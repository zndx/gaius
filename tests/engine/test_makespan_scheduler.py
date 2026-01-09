"""Tests for MakespanScheduler - GPU transition optimization.

This module tests the CP-SAT based scheduler that optimizes GPU allocation
transitions. The scheduler is a pure algorithmic component - no GPU hardware
or mocking is required.

Test Categories:
1. Basic operations (no-change, simple start, simple stop)
2. GPU constraints (reserved GPUs, contiguity, insufficient resources)
3. Transition planning (dependency ordering, parallel stops)
4. Error handling (OR-Tools unavailable, infeasible plans)
"""

import pytest

from gaius.engine.scheduling.types import (
    SchedulingTask,
    TransitionType,
)
from gaius.engine.scheduling.makespan_scheduler import (
    MakespanScheduler,
    ORTOOLS_AVAILABLE,
    LOAD_TIME_MS,
    UNLOAD_TIME_MS,
)


# Skip all tests if OR-Tools is not available
pytestmark = pytest.mark.skipif(
    not ORTOOLS_AVAILABLE,
    reason="OR-Tools not installed (uv sync --extra scheduler)"
)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Initialization Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMakespanSchedulerInit:
    """Test scheduler initialization."""

    def test_default_initialization(self):
        """Scheduler initializes with defaults."""
        scheduler = MakespanScheduler(total_gpus=4)

        assert scheduler.total_gpus == 4
        assert scheduler.reserved_gpus == set()
        assert scheduler.max_solve_time_s == 5.0

    def test_with_reserved_gpus(self):
        """Scheduler can reserve GPUs."""
        scheduler = MakespanScheduler(total_gpus=6, reserved_gpus={0, 5})

        assert scheduler.reserved_gpus == {0, 5}

    def test_custom_solve_time(self):
        """Solver timeout is configurable."""
        scheduler = MakespanScheduler(total_gpus=4, max_solve_time_s=10.0)

        assert scheduler.max_solve_time_s == 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Basic Operation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBasicOperations:
    """Test basic scheduler operations."""

    def test_empty_to_empty(self):
        """No-op when both current and target are empty."""
        scheduler = MakespanScheduler(total_gpus=4)

        result = scheduler.plan_transition([], [])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert len(result.plan.steps) == 0

    def test_keep_same_endpoint(self):
        """No-op when endpoint remains the same."""
        scheduler = MakespanScheduler(total_gpus=4)

        task = SchedulingTask(
            task_id="fast",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
            fixed_gpu_ids=[0],
        )

        result = scheduler.plan_transition([task], [task])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert len(result.plan.steps) == 0
        # No new GPU assignments needed - existing allocation is unchanged
        # The scheduler doesn't re-report unchanged allocations
        assert result.plan.gpu_assignments == {}

    def test_simple_start(self):
        """Start a new endpoint on idle GPUs."""
        scheduler = MakespanScheduler(total_gpus=4)

        target = SchedulingTask(
            task_id="fast",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
        )

        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert len(result.plan.steps) == 1
        assert result.plan.steps[0].transition_type == TransitionType.START_ENDPOINT
        assert result.plan.steps[0].endpoint_name == "fast"
        assert len(result.plan.gpu_assignments["fast"]) == 1

    def test_simple_stop(self):
        """Stop an endpoint, freeing GPUs."""
        scheduler = MakespanScheduler(total_gpus=4)

        current = SchedulingTask(
            task_id="fast",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
            fixed_gpu_ids=[0],
        )

        result = scheduler.plan_transition([current], [])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert len(result.plan.steps) == 1
        assert result.plan.steps[0].transition_type == TransitionType.STOP_ENDPOINT
        assert "fast" in result.plan.evicted_endpoints

    def test_start_multi_gpu_endpoint(self):
        """Start endpoint requiring multiple GPUs."""
        scheduler = MakespanScheduler(total_gpus=6)

        target = SchedulingTask(
            task_id="reasoning",
            endpoint_name="reasoning",
            model_id="qwen-32b",
            required_gpus=4,
        )

        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert len(result.plan.gpu_assignments["reasoning"]) == 4


# ─────────────────────────────────────────────────────────────────────────────
# GPU Constraint Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGPUConstraints:
    """Test GPU allocation constraints."""

    def test_respects_reserved_gpus(self):
        """Scheduler never allocates reserved GPUs."""
        scheduler = MakespanScheduler(total_gpus=4, reserved_gpus={0, 1})

        target = SchedulingTask(
            task_id="fast",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
        )

        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assigned_gpus = result.plan.gpu_assignments["fast"]
        assert 0 not in assigned_gpus
        assert 1 not in assigned_gpus
        # Should be assigned to GPU 2 or 3
        assert assigned_gpus[0] in {2, 3}

    def test_contiguous_gpu_allocation(self):
        """Tensor parallelism requires contiguous GPUs."""
        scheduler = MakespanScheduler(total_gpus=6)

        target = SchedulingTask(
            task_id="reasoning",
            endpoint_name="reasoning",
            model_id="qwen-32b",
            required_gpus=4,
            prefer_contiguous=True,
        )

        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        gpus = result.plan.gpu_assignments["reasoning"]
        assert len(gpus) == 4
        # Verify contiguity: GPUs should be consecutive
        assert gpus == list(range(gpus[0], gpus[0] + 4))

    def test_non_contiguous_allowed(self):
        """Non-contiguous allocation when prefer_contiguous=False."""
        scheduler = MakespanScheduler(total_gpus=6)

        # Two single-GPU endpoints on non-adjacent GPUs
        current = [
            SchedulingTask("a", "a", "m", 1, fixed_gpu_ids=[0]),
            SchedulingTask("b", "b", "m", 1, fixed_gpu_ids=[2]),
        ]

        target = SchedulingTask(
            task_id="coding",
            endpoint_name="coding",
            model_id="model",
            required_gpus=2,
            prefer_contiguous=False,
        )

        # Keep current plus add new
        result = scheduler.plan_transition(current, current + [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        # Coding should get GPUs 1, 3, 4, or 5 (not 0 or 2)
        coding_gpus = result.plan.gpu_assignments["coding"]
        assert len(coding_gpus) == 2
        assert 0 not in coding_gpus
        assert 2 not in coding_gpus

    def test_insufficient_gpus(self):
        """Fails when not enough GPUs available."""
        scheduler = MakespanScheduler(total_gpus=4)

        target = SchedulingTask(
            task_id="huge",
            endpoint_name="huge",
            model_id="model",
            required_gpus=6,
        )

        result = scheduler.plan_transition([], [target])

        assert not result.success
        assert result.error is not None  # Type narrowing
        assert "SCH.00000002" in result.error  # NOFEASIBLE

    def test_insufficient_after_reservations(self):
        """Fails when reserved GPUs leave insufficient capacity."""
        scheduler = MakespanScheduler(total_gpus=4, reserved_gpus={0, 1, 2})

        target = SchedulingTask(
            task_id="coding",
            endpoint_name="coding",
            model_id="model",
            required_gpus=2,  # Need 2 but only 1 available
        )

        result = scheduler.plan_transition([], [target])

        assert not result.success


# ─────────────────────────────────────────────────────────────────────────────
# Transition Planning Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTransitionPlanning:
    """Test multi-step transition planning."""

    def test_evict_before_start(self):
        """Must stop endpoints before starting new ones on their GPUs."""
        scheduler = MakespanScheduler(total_gpus=4)

        # Current: fast on GPU 0
        current = SchedulingTask(
            task_id="fast",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
            fixed_gpu_ids=[0],
        )

        # Target: coding needs 2 GPUs
        target = SchedulingTask(
            task_id="coding",
            endpoint_name="coding",
            model_id="model",
            required_gpus=2,
        )

        result = scheduler.plan_transition([current], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing

        # Should have stop step before start step
        stop_steps = [s for s in result.plan.steps if s.transition_type == TransitionType.STOP_ENDPOINT]
        start_steps = [s for s in result.plan.steps if s.transition_type == TransitionType.START_ENDPOINT]

        assert len(stop_steps) == 1
        assert len(start_steps) == 1
        assert stop_steps[0].endpoint_name == "fast"
        assert start_steps[0].endpoint_name == "coding"

    def test_dependency_on_gpu_freeing(self):
        """Start depends on stop when using same GPU."""
        scheduler = MakespanScheduler(total_gpus=2)

        # Current: fast on GPU 0
        current = SchedulingTask(
            task_id="fast",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
            fixed_gpu_ids=[0],
        )

        # Target: coding needs 2 GPUs (must use GPU 0)
        target = SchedulingTask(
            task_id="coding",
            endpoint_name="coding",
            model_id="model",
            required_gpus=2,
        )

        result = scheduler.plan_transition([current], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing

        stop_step = next(s for s in result.plan.steps if s.transition_type == TransitionType.STOP_ENDPOINT)
        start_step = next(s for s in result.plan.steps if s.transition_type == TransitionType.START_ENDPOINT)

        # Start must depend on stop (since coding needs GPU 0)
        assert stop_step.step_id in start_step.depends_on

    def test_parallel_stops(self):
        """Multiple stops can happen in parallel."""
        scheduler = MakespanScheduler(total_gpus=6)

        current = [
            SchedulingTask("fast", "fast", "m", 1, fixed_gpu_ids=[0]),
            SchedulingTask("coding", "coding", "m", 2, fixed_gpu_ids=[1, 2]),
        ]

        result = scheduler.plan_transition(current, [])

        assert result.success
        assert result.plan is not None  # Type narrowing
        # Both stops should have no dependencies (can run in parallel)
        for step in result.plan.steps:
            assert step.depends_on == []

    def test_keep_endpoints_preserved(self):
        """Endpoints in both current and target are preserved."""
        scheduler = MakespanScheduler(total_gpus=6)

        fast = SchedulingTask("fast", "fast", "m", 1, fixed_gpu_ids=[0])
        coding = SchedulingTask("coding", "coding", "m", 2, fixed_gpu_ids=[1, 2])
        new_endpoint = SchedulingTask("new", "new", "m", 1)

        result = scheduler.plan_transition(
            [fast, coding],  # Current
            [fast, coding, new_endpoint],  # Target: keep both, add new
        )

        assert result.success
        assert result.plan is not None  # Type narrowing
        # No stop steps (nothing evicted)
        stop_steps = [s for s in result.plan.steps if s.transition_type == TransitionType.STOP_ENDPOINT]
        assert len(stop_steps) == 0
        # Preserved endpoints in assignments
        assert result.plan.gpu_assignments["fast"] == [0]
        assert result.plan.gpu_assignments["coding"] == [1, 2]


# ─────────────────────────────────────────────────────────────────────────────
# Makespan Calculation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMakespanCalculation:
    """Test makespan (total transition time) calculations."""

    def test_stop_only_makespan(self):
        """Stops-only makespan is max of individual stop times."""
        scheduler = MakespanScheduler(total_gpus=6)

        current = [
            SchedulingTask("fast", "fast", "m", 1, fixed_gpu_ids=[0]),
            SchedulingTask("reasoning", "reasoning", "m", 4, fixed_gpu_ids=[1, 2, 3, 4]),
        ]

        result = scheduler.plan_transition(current, [])

        assert result.success
        assert result.plan is not None  # Type narrowing
        # Makespan should be max of the two stop durations
        # fast: 5000ms, reasoning: 15000ms
        # Since they run in parallel, makespan = max = 15000
        expected_makespan = max(
            UNLOAD_TIME_MS.get("fast", 10000),
            UNLOAD_TIME_MS.get("reasoning", 10000),
        )
        assert result.plan.total_makespan_ms == expected_makespan

    def test_start_duration_in_plan(self):
        """Start steps have correct duration estimates."""
        scheduler = MakespanScheduler(total_gpus=4)

        target = SchedulingTask("reasoning", "reasoning", "m", 4)

        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        start_step = result.plan.steps[0]
        assert start_step.estimated_duration_ms == LOAD_TIME_MS["reasoning"]

    def test_solve_time_recorded(self):
        """Solver time is recorded in result."""
        scheduler = MakespanScheduler(total_gpus=4)

        target = SchedulingTask("fast", "fast", "m", 1)
        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert result.solve_time_ms >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Solver Status Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSolverStatus:
    """Test solver status reporting."""

    def test_optimal_status(self):
        """Simple problems report OPTIMAL status."""
        scheduler = MakespanScheduler(total_gpus=4)

        target = SchedulingTask("fast", "fast", "m", 1)
        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        # Could be OPTIMAL or FEASIBLE depending on solver
        assert result.solver_status in ("OPTIMAL", "FEASIBLE")

    def test_infeasible_status(self):
        """Infeasible problems report appropriate status."""
        scheduler = MakespanScheduler(total_gpus=2)

        target = SchedulingTask("huge", "huge", "m", 4)
        result = scheduler.plan_transition([], [target])

        assert not result.success
        assert "INFEASIBLE" in result.solver_status

    def test_stops_only_status(self):
        """Stops-only transitions report special status."""
        scheduler = MakespanScheduler(total_gpus=4)

        current = SchedulingTask("fast", "fast", "m", 1, fixed_gpu_ids=[0])
        result = scheduler.plan_transition([current], [])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert result.solver_status == "STOPS_ONLY"


# ─────────────────────────────────────────────────────────────────────────────
# Edge Cases
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_all_gpus_reserved(self):
        """Fails when all GPUs are reserved."""
        scheduler = MakespanScheduler(total_gpus=4, reserved_gpus={0, 1, 2, 3})

        target = SchedulingTask("fast", "fast", "m", 1)
        result = scheduler.plan_transition([], [target])

        assert not result.success

    def test_single_gpu_system(self):
        """Works on single-GPU system."""
        scheduler = MakespanScheduler(total_gpus=1)

        target = SchedulingTask("fast", "fast", "m", 1)
        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert result.plan.gpu_assignments["fast"] == [0]

    def test_swap_endpoints(self):
        """Replace one endpoint with another."""
        scheduler = MakespanScheduler(total_gpus=2)

        current = SchedulingTask("fast", "fast", "m", 1, fixed_gpu_ids=[0])
        target = SchedulingTask("coding", "coding", "m", 1)

        result = scheduler.plan_transition([current], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        assert "fast" in result.plan.evicted_endpoints
        assert "coding" in result.plan.target_endpoints

    def test_unknown_endpoint_times(self):
        """Uses default times for unknown endpoints."""
        scheduler = MakespanScheduler(total_gpus=4)

        # Unknown endpoint name not in LOAD_TIME_MS
        target = SchedulingTask("custom", "custom", "m", 1)
        result = scheduler.plan_transition([], [target])

        assert result.success
        assert result.plan is not None  # Type narrowing
        # Default load time is 60000ms
        assert result.plan.steps[0].estimated_duration_ms == 60000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
