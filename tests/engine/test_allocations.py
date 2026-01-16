"""Tests for GPU allocation tracking types.

This module tests the dataclasses used for GPU resource management:
1. AllocationState - Lifecycle states
2. GPUAllocation - GPU assignment with state transitions
3. GPUStatus - Single GPU monitoring
4. AllocationRequest/AllocationResult - Request/response types
5. ResourceUnavailable - Exception type

Critical Path Coverage:
- State transitions (mark_active, mark_failed, mark_releasing)
- Process liveness detection (is_process_alive, is_orphaned)
- GPU availability calculations
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from gaius.engine.resources.allocations import (
    AllocationState,
    GPUAllocation,
    GPUStatus,
    AllocationRequest,
    AllocationResult,
    ResourceUnavailable,
)


# ─────────────────────────────────────────────────────────────────────────────
# AllocationState Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAllocationState:
    """Test AllocationState enum."""

    def test_all_states_defined(self):
        """All allocation states are defined."""
        assert AllocationState.PENDING.value == "pending"
        assert AllocationState.ALLOCATED.value == "allocated"
        assert AllocationState.ACTIVE.value == "active"
        assert AllocationState.RELEASING.value == "releasing"
        assert AllocationState.FAILED.value == "failed"

    def test_state_count(self):
        """Five states in the lifecycle."""
        assert len(AllocationState) == 5


# ─────────────────────────────────────────────────────────────────────────────
# GPUAllocation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGPUAllocation:
    """Test GPUAllocation dataclass."""

    def test_required_fields(self):
        """Allocation requires agent_alias, model, gpu_ids, vram."""
        alloc = GPUAllocation(
            agent_alias="reasoning",
            model="qwen-32b",
            gpu_ids=[0, 1, 2, 3],
            vram_reserved_gb=20.0,
        )

        assert alloc.agent_alias == "reasoning"
        assert alloc.model == "qwen-32b"
        assert alloc.gpu_ids == [0, 1, 2, 3]
        assert alloc.vram_reserved_gb == 20.0

    def test_default_values(self):
        """Allocation has sensible defaults."""
        alloc = GPUAllocation(
            agent_alias="test",
            model="model",
            gpu_ids=[0],
            vram_reserved_gb=16.0,
        )

        assert alloc.state == AllocationState.PENDING
        assert alloc.activated_at is None
        assert alloc.endpoint_port is None
        assert alloc.process_pid is None
        assert alloc.error_message is None

    def test_num_gpus(self):
        """num_gpus property returns count."""
        alloc = GPUAllocation("a", "m", [0, 1, 2], 16.0)
        assert alloc.num_gpus == 3

        alloc_single = GPUAllocation("a", "m", [0], 16.0)
        assert alloc_single.num_gpus == 1

    def test_is_active_false_when_pending(self):
        """is_active is False when PENDING."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.PENDING)
        assert alloc.is_active is False

    def test_is_active_true_when_active(self):
        """is_active is True when ACTIVE."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ACTIVE)
        assert alloc.is_active is True

    def test_is_usable_when_allocated(self):
        """is_usable is True when ALLOCATED."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ALLOCATED)
        assert alloc.is_usable is True

    def test_is_usable_when_active(self):
        """is_usable is True when ACTIVE."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ACTIVE)
        assert alloc.is_usable is True

    def test_is_usable_false_when_pending(self):
        """is_usable is False when PENDING."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.PENDING)
        assert alloc.is_usable is False

    def test_is_usable_false_when_releasing(self):
        """is_usable is False when RELEASING."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.RELEASING)
        assert alloc.is_usable is False

    def test_is_usable_false_when_failed(self):
        """is_usable is False when FAILED."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.FAILED)
        assert alloc.is_usable is False


class TestGPUAllocationStateTransitions:
    """Test state transition methods."""

    def test_mark_active(self):
        """mark_active sets state, port, pid, and activated_at."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ALLOCATED)

        alloc.mark_active(port=8080, pid=12345)

        assert alloc.state == AllocationState.ACTIVE
        assert alloc.endpoint_port == 8080
        assert alloc.process_pid == 12345
        assert alloc.activated_at is not None

    def test_mark_active_without_pid(self):
        """mark_active works without PID."""
        alloc = GPUAllocation("a", "m", [0], 16.0)

        alloc.mark_active(port=8080)

        assert alloc.state == AllocationState.ACTIVE
        assert alloc.endpoint_port == 8080
        assert alloc.process_pid is None

    def test_mark_failed(self):
        """mark_failed sets state and error message."""
        alloc = GPUAllocation("a", "m", [0], 16.0)

        alloc.mark_failed("GPU out of memory")

        assert alloc.state == AllocationState.FAILED
        assert alloc.error_message == "GPU out of memory"

    def test_mark_releasing(self):
        """mark_releasing sets state to RELEASING."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ACTIVE)

        alloc.mark_releasing()

        assert alloc.state == AllocationState.RELEASING


class TestGPUAllocationProcessTracking:
    """Test process liveness detection."""

    def test_is_process_alive_no_pid(self):
        """is_process_alive is False without PID."""
        alloc = GPUAllocation("a", "m", [0], 16.0)
        assert alloc.is_process_alive() is False

    def test_is_process_alive_process_exists(self):
        """is_process_alive is True when process exists."""
        alloc = GPUAllocation("a", "m", [0], 16.0, process_pid=12345)

        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None  # No exception means process exists
            assert alloc.is_process_alive() is True
            mock_kill.assert_called_once_with(12345, 0)

    def test_is_process_alive_process_dead(self):
        """is_process_alive is False when process doesn't exist."""
        alloc = GPUAllocation("a", "m", [0], 16.0, process_pid=12345)

        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError()
            assert alloc.is_process_alive() is False

    def test_is_process_alive_permission_error(self):
        """is_process_alive is True on PermissionError (process exists)."""
        alloc = GPUAllocation("a", "m", [0], 16.0, process_pid=12345)

        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = PermissionError()
            assert alloc.is_process_alive() is True

    def test_is_orphaned_when_pending(self):
        """is_orphaned is False when PENDING."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.PENDING, process_pid=12345)
        assert alloc.is_orphaned() is False

    def test_is_orphaned_when_releasing(self):
        """is_orphaned is False when RELEASING."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.RELEASING, process_pid=12345)
        assert alloc.is_orphaned() is False

    def test_is_orphaned_when_failed(self):
        """is_orphaned is False when FAILED."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.FAILED, process_pid=12345)
        assert alloc.is_orphaned() is False

    def test_is_orphaned_no_pid(self):
        """is_orphaned is False without PID tracking."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ACTIVE)
        assert alloc.is_orphaned() is False

    def test_is_orphaned_process_alive(self):
        """is_orphaned is False when process is alive."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ACTIVE, process_pid=12345)

        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None  # Process exists
            assert alloc.is_orphaned() is False

    def test_is_orphaned_process_dead(self):
        """is_orphaned is True when ACTIVE but process is dead."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ACTIVE, process_pid=12345)

        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError()
            assert alloc.is_orphaned() is True

    def test_is_orphaned_allocated_process_dead(self):
        """is_orphaned is True when ALLOCATED but process is dead."""
        alloc = GPUAllocation("a", "m", [0], 16.0, state=AllocationState.ALLOCATED, process_pid=12345)

        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError()
            assert alloc.is_orphaned() is True


# ─────────────────────────────────────────────────────────────────────────────
# GPUStatus Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGPUStatus:
    """Test GPUStatus dataclass."""

    def test_required_fields(self):
        """Status requires gpu_id and total_vram_gb."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0)

        assert status.gpu_id == 0
        assert status.total_vram_gb == 24.0

    def test_default_values(self):
        """Status has sensible defaults."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0)

        assert status.used_vram_gb == 0.0
        assert status.temperature_c == 0
        assert status.utilization_pct == 0.0
        assert status.allocated_to is None
        assert status.is_reserved is False

    def test_free_vram_gb(self):
        """free_vram_gb calculated correctly."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0, used_vram_gb=8.0)
        assert status.free_vram_gb == 16.0

    def test_free_vram_gb_full(self):
        """free_vram_gb is 0 when fully used."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0, used_vram_gb=24.0)
        assert status.free_vram_gb == 0.0

    def test_is_free_when_unallocated_and_unreserved(self):
        """is_free is True when not allocated and not reserved."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0)
        assert status.is_free is True

    def test_is_free_false_when_allocated(self):
        """is_free is False when allocated."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0, allocated_to="reasoning")
        assert status.is_free is False

    def test_is_free_false_when_reserved(self):
        """is_free is False when reserved."""
        status = GPUStatus(gpu_id=0, total_vram_gb=24.0, is_reserved=True)
        assert status.is_free is False

    def test_full_status(self):
        """Status with all fields populated."""
        status = GPUStatus(
            gpu_id=0,
            total_vram_gb=24.0,
            used_vram_gb=20.0,
            temperature_c=65,
            utilization_pct=85.5,
            allocated_to="reasoning",
            is_reserved=False,
        )

        assert status.free_vram_gb == 4.0
        assert status.is_free is False
        assert status.temperature_c == 65
        assert status.utilization_pct == 85.5


# ─────────────────────────────────────────────────────────────────────────────
# AllocationRequest Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAllocationRequest:
    """Test AllocationRequest dataclass."""

    def test_required_fields(self):
        """Request requires agent_alias and model."""
        request = AllocationRequest(agent_alias="reasoning", model="qwen-32b")

        assert request.agent_alias == "reasoning"
        assert request.model == "qwen-32b"

    def test_default_values(self):
        """Request has sensible defaults."""
        request = AllocationRequest(agent_alias="test", model="model")

        assert request.num_gpus == 1
        assert request.vram_per_gpu_gb == 16.0
        assert request.prefer_contiguous is True
        assert request.priority == 0
        assert request.timeout_seconds == 30

    def test_custom_values(self):
        """Request accepts custom values."""
        request = AllocationRequest(
            agent_alias="reasoning",
            model="qwen-32b",
            num_gpus=4,
            vram_per_gpu_gb=20.0,
            prefer_contiguous=True,
            priority=10,
            timeout_seconds=60,
        )

        assert request.num_gpus == 4
        assert request.vram_per_gpu_gb == 20.0
        assert request.priority == 10
        assert request.timeout_seconds == 60


# ─────────────────────────────────────────────────────────────────────────────
# AllocationResult Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAllocationResult:
    """Test AllocationResult dataclass."""

    def test_success_result(self):
        """Successful allocation result."""
        alloc = GPUAllocation("reasoning", "qwen-32b", [0, 1, 2, 3], 20.0)
        result = AllocationResult(success=True, allocation=alloc, wait_time_ms=150)

        assert result.success is True
        assert result.allocation is not None
        assert result.allocation.agent_alias == "reasoning"
        assert result.error is None
        assert result.wait_time_ms == 150

    def test_failure_result(self):
        """Failed allocation result."""
        result = AllocationResult(
            success=False,
            error="Insufficient GPU memory",
            wait_time_ms=5000,
        )

        assert result.success is False
        assert result.allocation is None
        assert result.error == "Insufficient GPU memory"

    def test_default_values(self):
        """Result has sensible defaults."""
        result = AllocationResult(success=True)

        assert result.allocation is None
        assert result.error is None
        assert result.wait_time_ms == 0


# ─────────────────────────────────────────────────────────────────────────────
# ResourceUnavailable Exception Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResourceUnavailable:
    """Test ResourceUnavailable exception."""

    def test_basic_exception(self):
        """Exception with message only."""
        exc = ResourceUnavailable("No GPUs available")

        assert str(exc) == "No GPUs available"
        assert exc.required_gpus == 0
        assert exc.available_gpus == 0

    def test_exception_with_counts(self):
        """Exception with GPU counts."""
        exc = ResourceUnavailable(
            "Need 4 GPUs, only 2 available",
            required_gpus=4,
            available_gpus=2,
        )

        assert exc.required_gpus == 4
        assert exc.available_gpus == 2

    def test_exception_is_raisable(self):
        """Exception can be raised and caught."""
        with pytest.raises(ResourceUnavailable) as exc_info:
            raise ResourceUnavailable("Test error", required_gpus=4, available_gpus=1)

        assert exc_info.value.required_gpus == 4
        assert exc_info.value.available_gpus == 1


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests - Allocation Lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class TestAllocationLifecycle:
    """Test complete allocation lifecycle."""

    def test_full_lifecycle(self):
        """Test PENDING → ALLOCATED → ACTIVE → RELEASING transitions."""
        # Create allocation in PENDING state
        alloc = GPUAllocation(
            agent_alias="reasoning",
            model="qwen-32b",
            gpu_ids=[0, 1, 2, 3],
            vram_reserved_gb=20.0,
        )
        assert alloc.state == AllocationState.PENDING
        assert alloc.is_usable is False

        # Transition to ALLOCATED
        alloc.state = AllocationState.ALLOCATED
        assert alloc.is_usable is True
        assert alloc.is_active is False

        # Transition to ACTIVE
        alloc.mark_active(port=8080, pid=12345)
        assert alloc.state == AllocationState.ACTIVE
        assert alloc.is_usable is True
        assert alloc.is_active is True
        assert alloc.endpoint_port == 8080

        # Transition to RELEASING
        alloc.mark_releasing()
        assert alloc.state == AllocationState.RELEASING
        assert alloc.is_usable is False
        assert alloc.is_active is False

    def test_failure_path(self):
        """Test PENDING → FAILED transition."""
        alloc = GPUAllocation(
            agent_alias="reasoning",
            model="qwen-32b",
            gpu_ids=[0, 1, 2, 3],
            vram_reserved_gb=20.0,
        )

        alloc.mark_failed("CUDA out of memory")

        assert alloc.state == AllocationState.FAILED
        assert alloc.error_message == "CUDA out of memory"
        assert alloc.is_usable is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
