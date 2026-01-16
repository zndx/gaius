"""Tests for scheduling type definitions.

Tests the dataclasses used by the MakespanScheduler:
- SchedulingTask: GPU workload with resource requirements
- TransitionStep: Single step in a transition plan
- TransitionPlan: Complete GPU transition plan
- SchedulingResult: Result of makespan optimization
"""

import pytest

from gaius.engine.scheduling.types import (
    SchedulingTask,
    TransitionStep,
    TransitionPlan,
    SchedulingResult,
    TransitionType,
)


# ─────────────────────────────────────────────────────────────────────────────
# SchedulingTask Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSchedulingTask:
    """Test SchedulingTask dataclass."""

    def test_required_fields(self):
        """Task requires task_id, endpoint_name, model_id, required_gpus."""
        task = SchedulingTask(
            task_id="t1",
            endpoint_name="fast",
            model_id="model-v1",
            required_gpus=1,
        )

        assert task.task_id == "t1"
        assert task.endpoint_name == "fast"
        assert task.model_id == "model-v1"
        assert task.required_gpus == 1

    def test_default_values(self):
        """Task has sensible defaults for optional fields."""
        task = SchedulingTask(
            task_id="t1",
            endpoint_name="fast",
            model_id="model",
            required_gpus=1,
        )

        assert task.salience == 1.0
        assert task.capability is None
        assert task.prefer_contiguous is True
        assert task.fixed_gpu_ids is None
        assert task.is_current is False
        assert task.memory_mb == 0

    def test_with_fixed_gpus(self):
        """Task can have fixed GPU assignments (for current allocations)."""
        task = SchedulingTask(
            task_id="t1",
            endpoint_name="reasoning",
            model_id="qwen-32b",
            required_gpus=4,
            fixed_gpu_ids=[0, 1, 2, 3],
            is_current=True,
        )

        assert task.fixed_gpu_ids == [0, 1, 2, 3]
        assert task.is_current is True

    def test_with_salience(self):
        """Task can have priority salience weight."""
        task = SchedulingTask(
            task_id="t1",
            endpoint_name="reasoning",
            model_id="model",
            required_gpus=4,
            salience=2.5,
        )

        assert task.salience == 2.5

    def test_non_contiguous_allowed(self):
        """Task can opt out of contiguous GPU requirement."""
        task = SchedulingTask(
            task_id="t1",
            endpoint_name="coding",
            model_id="model",
            required_gpus=2,
            prefer_contiguous=False,
        )

        assert task.prefer_contiguous is False


# ─────────────────────────────────────────────────────────────────────────────
# TransitionType Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTransitionType:
    """Test TransitionType enum."""

    def test_stop_value(self):
        """STOP_ENDPOINT has value 'stop'."""
        assert TransitionType.STOP_ENDPOINT.value == "stop"

    def test_start_value(self):
        """START_ENDPOINT has value 'start'."""
        assert TransitionType.START_ENDPOINT.value == "start"

    def test_enum_members(self):
        """Only two transition types exist."""
        assert len(TransitionType) == 2


# ─────────────────────────────────────────────────────────────────────────────
# TransitionStep Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTransitionStep:
    """Test TransitionStep dataclass."""

    def test_stop_step(self):
        """Stop step frees GPUs."""
        step = TransitionStep(
            step_id=0,
            transition_type=TransitionType.STOP_ENDPOINT,
            endpoint_name="fast",
            gpu_ids=[0],
            estimated_duration_ms=5000,
        )

        assert step.step_id == 0
        assert step.transition_type == TransitionType.STOP_ENDPOINT
        assert step.endpoint_name == "fast"
        assert step.gpu_ids == [0]
        assert step.estimated_duration_ms == 5000
        assert step.depends_on == []

    def test_start_step_with_dependencies(self):
        """Start step can depend on prior stops."""
        step = TransitionStep(
            step_id=1,
            transition_type=TransitionType.START_ENDPOINT,
            endpoint_name="coding",
            gpu_ids=[0, 1],
            estimated_duration_ms=45000,
            depends_on=[0],  # Depends on step 0 completing
        )

        assert step.step_id == 1
        assert step.transition_type == TransitionType.START_ENDPOINT
        assert step.depends_on == [0]

    def test_default_no_dependencies(self):
        """Steps default to no dependencies."""
        step = TransitionStep(
            step_id=0,
            transition_type=TransitionType.STOP_ENDPOINT,
            endpoint_name="fast",
            gpu_ids=[0],
            estimated_duration_ms=5000,
        )

        assert step.depends_on == []


# ─────────────────────────────────────────────────────────────────────────────
# TransitionPlan Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTransitionPlan:
    """Test TransitionPlan dataclass."""

    def test_empty_plan(self):
        """Empty plan when no transitions needed."""
        plan = TransitionPlan(
            plan_id="test-001",
            steps=[],
            total_makespan_ms=0,
            evicted_endpoints=[],
            target_endpoints=["fast"],
            gpu_assignments={"fast": [0]},
            restore_plan=[],
        )

        assert plan.plan_id == "test-001"
        assert len(plan.steps) == 0
        assert plan.total_makespan_ms == 0

    def test_plan_with_steps(self):
        """Plan with stop and start steps."""
        stop_step = TransitionStep(
            step_id=0,
            transition_type=TransitionType.STOP_ENDPOINT,
            endpoint_name="fast",
            gpu_ids=[0],
            estimated_duration_ms=5000,
        )
        start_step = TransitionStep(
            step_id=1,
            transition_type=TransitionType.START_ENDPOINT,
            endpoint_name="coding",
            gpu_ids=[0, 1],
            estimated_duration_ms=45000,
            depends_on=[0],
        )

        plan = TransitionPlan(
            plan_id="test-002",
            steps=[stop_step, start_step],
            total_makespan_ms=50000,
            evicted_endpoints=["fast"],
            target_endpoints=["coding"],
            gpu_assignments={"coding": [0, 1]},
            restore_plan=["fast"],
        )

        assert len(plan.steps) == 2
        assert plan.evicted_endpoints == ["fast"]
        assert plan.target_endpoints == ["coding"]
        assert plan.gpu_assignments["coding"] == [0, 1]
        assert plan.restore_plan == ["fast"]

    def test_gpu_assignments_mapping(self):
        """GPU assignments map endpoint names to GPU IDs."""
        plan = TransitionPlan(
            plan_id="test-003",
            steps=[],
            total_makespan_ms=0,
            evicted_endpoints=[],
            target_endpoints=["fast", "coding"],
            gpu_assignments={
                "fast": [0],
                "coding": [1, 2],
            },
            restore_plan=[],
        )

        assert plan.gpu_assignments["fast"] == [0]
        assert plan.gpu_assignments["coding"] == [1, 2]


# ─────────────────────────────────────────────────────────────────────────────
# SchedulingResult Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSchedulingResult:
    """Test SchedulingResult dataclass."""

    def test_success_result(self):
        """Successful result includes plan."""
        plan = TransitionPlan(
            plan_id="test",
            steps=[],
            total_makespan_ms=0,
            evicted_endpoints=[],
            target_endpoints=["fast"],
            gpu_assignments={"fast": [0]},
            restore_plan=[],
        )

        result = SchedulingResult(
            success=True,
            plan=plan,
            solver_status="OPTIMAL",
            solve_time_ms=50,
        )

        assert result.success is True
        assert result.plan is not None
        assert result.error is None
        assert result.solver_status == "OPTIMAL"
        assert result.solve_time_ms == 50

    def test_failure_result(self):
        """Failed result includes error message."""
        result = SchedulingResult(
            success=False,
            error="Not enough GPUs. Guru Meditation: #SCH.00000002.NOFEASIBLE",
            solver_status="INFEASIBLE_RESOURCES",
            solve_time_ms=10,
        )

        assert result.success is False
        assert result.plan is None
        assert result.error is not None  # Type narrowing
        assert "NOFEASIBLE" in result.error
        assert result.solver_status == "INFEASIBLE_RESOURCES"

    def test_default_values(self):
        """Result has sensible defaults."""
        result = SchedulingResult(success=True)

        assert result.plan is None
        assert result.error is None
        assert result.solver_status == ""
        assert result.solve_time_ms == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
