"""Tests for reconciliation FSM types and state machine logic.

This module tests the core reconciliation logic that:
1. Determines actual endpoint state from observations
2. Detects drift between expected and actual states
3. Identifies orphaned processes and port conflicts

Critical Path Coverage:
1. EndpointState and InfraProcessState enums
2. EndpointObservation and InfraProcessObservation dataclasses
3. reconcile_state() - the core FSM transition function
4. ReconciliationResult and RemediationAction types
"""

import pytest
from datetime import datetime

from gaius.engine.resources.reconciliation import (
    # Enums
    EndpointState,
    InfraProcessState,
    # Observation dataclasses
    EndpointObservation,
    InfraProcessObservation,
    # Result dataclasses
    ReconciliationResult,
    InfraReconciliationResult,
    RemediationAction,
    RemediationResult,
    # Core logic
    reconcile_state,
)


# ─────────────────────────────────────────────────────────────────────────────
# EndpointState Enum Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEndpointState:
    """Test EndpointState enum values."""

    def test_all_states_defined(self):
        """All expected states are defined."""
        assert EndpointState.ABSENT.value == "absent"
        assert EndpointState.ALLOCATED.value == "allocated"
        assert EndpointState.STARTING.value == "starting"
        assert EndpointState.HEALTHY.value == "healthy"
        assert EndpointState.UNHEALTHY.value == "unhealthy"
        assert EndpointState.STOPPING.value == "stopping"
        assert EndpointState.ORPHANED.value == "orphaned"
        assert EndpointState.CONFLICT.value == "conflict"
        assert EndpointState.FAILED.value == "failed"

    def test_state_count(self):
        """Nine states total in the FSM."""
        assert len(EndpointState) == 9


class TestInfraProcessState:
    """Test InfraProcessState enum values."""

    def test_all_states_defined(self):
        """All expected states are defined."""
        assert InfraProcessState.ABSENT.value == "absent"
        assert InfraProcessState.RUNNING.value == "running"
        assert InfraProcessState.ORPHANED.value == "orphaned"
        assert InfraProcessState.CONFLICT.value == "conflict"

    def test_state_count(self):
        """Four states for infrastructure processes."""
        assert len(InfraProcessState) == 4


# ─────────────────────────────────────────────────────────────────────────────
# EndpointObservation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEndpointObservation:
    """Test EndpointObservation dataclass and properties."""

    def test_default_values(self):
        """Observation has sensible defaults."""
        obs = EndpointObservation(name="test")

        assert obs.name == "test"
        assert obs.expected_state == EndpointState.ABSENT
        assert obs.expected_port is None
        assert obs.expected_gpus == []
        assert obs.expected_model is None
        assert obs.gpu_pids == set()
        assert obs.gpu_memory_mb == {}
        assert obs.port_pid is None
        assert obs.port_in_use is False
        assert obs.tracked_pid is None
        assert obs.tracked_pid_alive is False
        assert obs.health_ok is False
        assert obs.health_latency_ms == 0
        assert obs.model_loaded is None

    def test_has_gpu_memory_false_when_empty(self):
        """has_gpu_memory is False with no memory usage."""
        obs = EndpointObservation(name="test", gpu_memory_mb={})
        assert obs.has_gpu_memory is False

    def test_has_gpu_memory_false_when_low(self):
        """has_gpu_memory is False with low memory (<= 100MB)."""
        obs = EndpointObservation(name="test", gpu_memory_mb={0: 50, 1: 100})
        assert obs.has_gpu_memory is False

    def test_has_gpu_memory_true_when_significant(self):
        """has_gpu_memory is True with significant memory (> 100MB)."""
        obs = EndpointObservation(name="test", gpu_memory_mb={0: 101})
        assert obs.has_gpu_memory is True

    def test_has_gpu_memory_true_any_gpu(self):
        """has_gpu_memory is True if any GPU has significant memory."""
        obs = EndpointObservation(name="test", gpu_memory_mb={0: 50, 1: 200, 2: 80})
        assert obs.has_gpu_memory is True

    def test_has_orphan_process_false_when_port_not_in_use(self):
        """has_orphan_process is False when port not in use."""
        obs = EndpointObservation(name="test", port_in_use=False, tracked_pid_alive=False)
        assert obs.has_orphan_process is False

    def test_has_orphan_process_false_when_pid_alive(self):
        """has_orphan_process is False when tracked PID is alive."""
        obs = EndpointObservation(name="test", port_in_use=True, tracked_pid_alive=True)
        assert obs.has_orphan_process is False

    def test_has_orphan_process_true(self):
        """has_orphan_process is True when port in use but PID not tracked."""
        obs = EndpointObservation(name="test", port_in_use=True, tracked_pid_alive=False)
        assert obs.has_orphan_process is True

    def test_full_observation(self):
        """Observation with all fields populated."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.HEALTHY,
            expected_port=8080,
            expected_gpus=[0, 1, 2, 3],
            expected_model="qwen-32b",
            gpu_pids={12345, 12346},
            gpu_memory_mb={0: 8000, 1: 8000, 2: 8000, 3: 8000},
            port_pid=12345,
            port_in_use=True,
            tracked_pid=12345,
            tracked_pid_alive=True,
            health_ok=True,
            health_latency_ms=50,
            model_loaded="qwen-32b",
        )

        assert obs.has_gpu_memory is True
        assert obs.has_orphan_process is False


# ─────────────────────────────────────────────────────────────────────────────
# InfraProcessObservation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestInfraProcessObservation:
    """Test InfraProcessObservation dataclass and methods."""

    def test_default_values(self):
        """Observation has sensible defaults."""
        obs = InfraProcessObservation(name="test")

        assert obs.name == "test"
        assert obs.expected_ports == []
        assert obs.port_pids == {}
        assert obs.port_process_names == {}
        assert obs.pid_ppids == {}
        assert obs.pid_cmdlines == {}

    def test_get_orphan_pids_empty(self):
        """No orphans when no ports configured."""
        obs = InfraProcessObservation(name="test", expected_ports=[])
        assert obs.get_orphan_pids() == []

    def test_get_orphan_pids_no_orphans(self):
        """No orphans when all processes have parent."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000, 9001],
            port_pids={9000: 1234, 9001: 1235},
            pid_ppids={1234: 500, 1235: 500},  # PPID != 1
        )
        assert obs.get_orphan_pids() == []

    def test_get_orphan_pids_detects_orphan(self):
        """Detects orphan when PPID is 1 (init)."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000, 9001],
            port_pids={9000: 1234, 9001: 1235},
            pid_ppids={1234: 1, 1235: 500},  # 1234 is orphaned
        )
        assert obs.get_orphan_pids() == [1234]

    def test_get_orphan_pids_multiple(self):
        """Detects multiple orphans."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000, 9001, 9002],
            port_pids={9000: 1234, 9001: 1235, 9002: 1236},
            pid_ppids={1234: 1, 1235: 1, 1236: 500},  # Two orphans
        )
        orphans = obs.get_orphan_pids()
        assert 1234 in orphans
        assert 1235 in orphans
        assert 1236 not in orphans

    def test_get_orphan_pids_ignores_empty_ports(self):
        """No orphan reported for ports without listeners."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000, 9001],
            port_pids={9000: None, 9001: 1235},  # 9000 has no listener
            pid_ppids={1235: 1},
        )
        assert obs.get_orphan_pids() == [1235]

    def test_get_conflict_ports_empty(self):
        """No conflicts when no ports configured."""
        obs = InfraProcessObservation(name="test", expected_ports=[])
        assert obs.get_conflict_ports() == {}

    def test_get_conflict_ports_no_conflicts(self):
        """No conflicts when ports are unused or expected."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000, 9001],
            port_pids={9000: None, 9001: 1234},
            pid_ppids={1234: 500},  # Has parent (not orphan)
            pid_cmdlines={1234: "metaflow some-args"},  # Name matches
        )
        assert obs.get_conflict_ports() == {}

    def test_get_conflict_ports_ignores_orphans(self):
        """Orphans are not conflicts (handled separately)."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000],
            port_pids={9000: 1234},
            pid_ppids={1234: 1},  # PPID=1 means orphan
            port_process_names={9000: "stale-process"},
        )
        # Orphans are handled by get_orphan_pids, not conflicts
        assert obs.get_conflict_ports() == {}

    def test_get_conflict_ports_detects_conflict(self):
        """Detects conflict when unknown process holds port."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000],
            port_pids={9000: 1234},
            pid_ppids={1234: 500},  # Not orphan
            port_process_names={9000: "redis-server"},  # Different process
            pid_cmdlines={1234: "redis-server --port 9000"},  # Doesn't match
        )
        conflicts = obs.get_conflict_ports()
        assert conflicts == {9000: 1234}

    def test_get_conflict_ports_allows_kubectl(self):
        """kubectl port-forward is not a conflict."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000],
            port_pids={9000: 1234},
            pid_ppids={1234: 500},
            port_process_names={9000: "kubectl"},
            pid_cmdlines={1234: "kubectl port-forward svc/metaflow 9000:9000"},
        )
        assert obs.get_conflict_ports() == {}

    def test_get_conflict_ports_allows_tilt(self):
        """tilt is not a conflict (dev environment manager)."""
        obs = InfraProcessObservation(
            name="metaflow",
            expected_ports=[9000],
            port_pids={9000: 1234},
            pid_ppids={1234: 500},
            port_process_names={9000: "tilt"},
            pid_cmdlines={1234: "tilt up"},
        )
        assert obs.get_conflict_ports() == {}


# ─────────────────────────────────────────────────────────────────────────────
# reconcile_state() Tests - Core FSM Logic
# ─────────────────────────────────────────────────────────────────────────────


class TestReconcileStateHealthy:
    """Test reconcile_state when expected state is HEALTHY."""

    def test_healthy_and_responding(self):
        """HEALTHY stays HEALTHY when health check passes."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.HEALTHY,
            health_ok=True,
            tracked_pid_alive=True,
        )
        assert reconcile_state(obs) == EndpointState.HEALTHY

    def test_healthy_but_not_responding_pid_dead_gpu_held(self):
        """HEALTHY → ORPHANED when PID dead but GPU memory held."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.HEALTHY,
            health_ok=False,
            tracked_pid_alive=False,
            gpu_memory_mb={0: 8000},  # GPU memory still held
        )
        assert reconcile_state(obs) == EndpointState.ORPHANED

    def test_healthy_but_not_responding_pid_dead_gpu_free(self):
        """HEALTHY → ABSENT when PID dead and GPU free."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.HEALTHY,
            health_ok=False,
            tracked_pid_alive=False,
            gpu_memory_mb={},  # No GPU memory
        )
        assert reconcile_state(obs) == EndpointState.ABSENT

    def test_healthy_but_not_responding_pid_alive(self):
        """HEALTHY → UNHEALTHY when PID alive but not responding."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.HEALTHY,
            health_ok=False,
            tracked_pid_alive=True,
        )
        assert reconcile_state(obs) == EndpointState.UNHEALTHY


class TestReconcileStateAbsent:
    """Test reconcile_state when expected state is ABSENT."""

    def test_absent_is_absent(self):
        """ABSENT stays ABSENT when nothing running."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ABSENT,
            port_in_use=False,
            gpu_memory_mb={},
        )
        assert reconcile_state(obs) == EndpointState.ABSENT

    def test_absent_but_gpu_held(self):
        """ABSENT → ORPHANED when GPU memory held but no process."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ABSENT,
            tracked_pid_alive=False,
            gpu_memory_mb={0: 8000},
        )
        assert reconcile_state(obs) == EndpointState.ORPHANED

    def test_absent_but_port_used_correct_model(self):
        """ABSENT → HEALTHY when externally started with correct model."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ABSENT,
            expected_model="qwen-32b",
            port_in_use=True,
            model_loaded="qwen-32b",
        )
        assert reconcile_state(obs) == EndpointState.HEALTHY

    def test_absent_but_port_used_wrong_model(self):
        """ABSENT → CONFLICT when port used by wrong model."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ABSENT,
            expected_model="qwen-32b",
            port_in_use=True,
            model_loaded="llama-7b",  # Wrong model
        )
        assert reconcile_state(obs) == EndpointState.CONFLICT


class TestReconcileStateStarting:
    """Test reconcile_state when expected state is STARTING."""

    def test_starting_pid_died(self):
        """STARTING → FAILED when PID dies during startup."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.STARTING,
            tracked_pid_alive=False,
        )
        assert reconcile_state(obs) == EndpointState.FAILED

    def test_starting_now_healthy(self):
        """STARTING → HEALTHY when health check passes."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.STARTING,
            tracked_pid_alive=True,
            health_ok=True,
        )
        assert reconcile_state(obs) == EndpointState.HEALTHY

    def test_starting_still_starting(self):
        """STARTING stays STARTING while loading."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.STARTING,
            tracked_pid_alive=True,
            health_ok=False,
        )
        assert reconcile_state(obs) == EndpointState.STARTING


class TestReconcileStateUnhealthy:
    """Test reconcile_state when expected state is UNHEALTHY."""

    def test_unhealthy_pid_died(self):
        """UNHEALTHY → ABSENT when PID dies."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.UNHEALTHY,
            tracked_pid_alive=False,
        )
        assert reconcile_state(obs) == EndpointState.ABSENT

    def test_unhealthy_recovered(self):
        """UNHEALTHY → HEALTHY when health check passes."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.UNHEALTHY,
            tracked_pid_alive=True,
            health_ok=True,
        )
        assert reconcile_state(obs) == EndpointState.HEALTHY

    def test_unhealthy_still_unhealthy(self):
        """UNHEALTHY stays UNHEALTHY when still not responding."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.UNHEALTHY,
            tracked_pid_alive=True,
            health_ok=False,
        )
        assert reconcile_state(obs) == EndpointState.UNHEALTHY


class TestReconcileStateStopping:
    """Test reconcile_state when expected state is STOPPING."""

    def test_stopping_completed(self):
        """STOPPING → ABSENT when fully stopped."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.STOPPING,
            tracked_pid_alive=False,
            gpu_memory_mb={},  # GPU freed
        )
        assert reconcile_state(obs) == EndpointState.ABSENT

    def test_stopping_still_running(self):
        """STOPPING stays STOPPING while shutdown in progress."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.STOPPING,
            tracked_pid_alive=True,
        )
        assert reconcile_state(obs) == EndpointState.STOPPING

    def test_stopping_gpu_still_held(self):
        """STOPPING stays STOPPING while GPU memory held."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.STOPPING,
            tracked_pid_alive=False,
            gpu_memory_mb={0: 8000},  # GPU not freed yet
        )
        assert reconcile_state(obs) == EndpointState.STOPPING


class TestReconcileStateAllocated:
    """Test reconcile_state when expected state is ALLOCATED."""

    def test_allocated_stays_allocated(self):
        """ALLOCATED stays ALLOCATED when not started."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ALLOCATED,
            port_in_use=False,
        )
        assert reconcile_state(obs) == EndpointState.ALLOCATED

    def test_allocated_unexpectedly_healthy(self):
        """ALLOCATED → HEALTHY when externally started."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ALLOCATED,
            port_in_use=True,
            health_ok=True,
        )
        assert reconcile_state(obs) == EndpointState.HEALTHY


class TestReconcileStateOrphanedConflict:
    """Test reconcile_state when expected state is ORPHANED or CONFLICT."""

    def test_orphaned_resolved(self):
        """ORPHANED → ABSENT when cleaned up."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ORPHANED,
            gpu_memory_mb={},  # No GPU memory
            port_in_use=False,
        )
        assert reconcile_state(obs) == EndpointState.ABSENT

    def test_orphaned_still_orphaned(self):
        """ORPHANED stays ORPHANED when not cleaned."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.ORPHANED,
            gpu_memory_mb={0: 8000},  # GPU still held
        )
        assert reconcile_state(obs) == EndpointState.ORPHANED

    def test_conflict_resolved(self):
        """CONFLICT → ABSENT when port freed."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.CONFLICT,
            port_in_use=False,
        )
        assert reconcile_state(obs) == EndpointState.ABSENT

    def test_conflict_still_blocked(self):
        """CONFLICT stays CONFLICT when port still in use."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.CONFLICT,
            port_in_use=True,
        )
        assert reconcile_state(obs) == EndpointState.CONFLICT


# ─────────────────────────────────────────────────────────────────────────────
# Result Dataclass Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestReconciliationResult:
    """Test ReconciliationResult dataclass."""

    def test_no_drift(self):
        """Result with no drift."""
        result = ReconciliationResult(
            endpoint="reasoning",
            expected_state=EndpointState.HEALTHY,
            actual_state=EndpointState.HEALTHY,
            is_drifted=False,
        )

        assert result.is_drifted is False
        assert "OK" in result.drift_description
        assert "healthy" in result.drift_description

    def test_with_drift(self):
        """Result with drift detected."""
        result = ReconciliationResult(
            endpoint="reasoning",
            expected_state=EndpointState.HEALTHY,
            actual_state=EndpointState.UNHEALTHY,
            is_drifted=True,
        )

        assert result.is_drifted is True
        assert "DRIFT" in result.drift_description
        assert "expected=healthy" in result.drift_description
        assert "actual=unhealthy" in result.drift_description

    def test_with_action_taken(self):
        """Result with remediation action."""
        result = ReconciliationResult(
            endpoint="reasoning",
            expected_state=EndpointState.HEALTHY,
            actual_state=EndpointState.UNHEALTHY,
            is_drifted=True,
            action_taken="restart_endpoint",
        )

        assert result.action_taken == "restart_endpoint"


class TestInfraReconciliationResult:
    """Test InfraReconciliationResult dataclass."""

    def test_success(self):
        """Successful reconciliation."""
        result = InfraReconciliationResult(
            name="metaflow",
            state=InfraProcessState.RUNNING,
            success=True,
            message="Process running normally",
        )

        assert result.success is True
        assert result.state == InfraProcessState.RUNNING

    def test_with_orphans_killed(self):
        """Result with orphans killed."""
        result = InfraReconciliationResult(
            name="metaflow",
            state=InfraProcessState.ABSENT,
            orphan_pids_killed=[1234, 1235],
            action_taken="kill_orphans",
            success=True,
            message="Killed 2 orphaned processes",
        )

        assert result.orphan_pids_killed == [1234, 1235]
        assert result.action_taken == "kill_orphans"

    def test_with_conflicts(self):
        """Result with port conflicts."""
        result = InfraReconciliationResult(
            name="metaflow",
            state=InfraProcessState.CONFLICT,
            conflict_ports={9000: 5678},
            success=False,
            message="Port 9000 blocked by PID 5678",
        )

        assert result.conflict_ports == {9000: 5678}
        assert result.success is False


class TestRemediationAction:
    """Test RemediationAction dataclass."""

    def test_default_values(self):
        """Action has sensible defaults."""
        action = RemediationAction(
            action_type="kill_process",
            target="1234",
        )

        assert action.action_type == "kill_process"
        assert action.target == "1234"
        assert action.severity == "warning"
        assert action.requires_approval is False
        assert action.description == ""

    def test_critical_action(self):
        """Critical action requiring approval."""
        action = RemediationAction(
            action_type="kill_unknown_service",
            target="redis",
            severity="critical",
            requires_approval=True,
            description="Kill unknown service blocking port 9000",
        )

        assert action.severity == "critical"
        assert action.requires_approval is True


class TestRemediationResult:
    """Test RemediationResult dataclass."""

    def test_success(self):
        """Successful remediation."""
        action = RemediationAction("restart", "reasoning")
        result = RemediationResult(
            action=action,
            success=True,
            message="Restarted successfully",
            new_state=EndpointState.HEALTHY,
        )

        assert result.success is True
        assert result.new_state == EndpointState.HEALTHY

    def test_failure(self):
        """Failed remediation."""
        action = RemediationAction("clear_gpu", "reasoning")
        result = RemediationResult(
            action=action,
            success=False,
            message="GPU memory still held",
            new_state=EndpointState.ORPHANED,
        )

        assert result.success is False
        assert result.new_state == EndpointState.ORPHANED


# ─────────────────────────────────────────────────────────────────────────────
# Edge Cases and Boundary Conditions
# ─────────────────────────────────────────────────────────────────────────────


class TestReconcileStateEdgeCases:
    """Test edge cases in reconcile_state."""

    def test_healthy_health_ok_overrides_pid_tracking(self):
        """Health check is ultimate source of truth, even if PID tracking fails."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.HEALTHY,
            health_ok=True,
            tracked_pid_alive=False,  # PID tracking failed but service responding
        )
        # Health check passing means it's HEALTHY, regardless of PID tracking
        assert reconcile_state(obs) == EndpointState.HEALTHY

    def test_failed_state_defaults_to_expected(self):
        """FAILED state returns expected state (no auto-recovery)."""
        obs = EndpointObservation(
            name="reasoning",
            expected_state=EndpointState.FAILED,
        )
        # FAILED is a terminal state that requires manual intervention
        assert reconcile_state(obs) == EndpointState.FAILED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
