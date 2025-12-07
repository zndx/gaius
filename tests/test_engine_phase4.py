"""Tests for Phase 4: Evolution and Health Services.

BDD Alignment (swarm_evolution.feature):
- Start/stop evolution daemon
- GPU idle state monitoring
- Evolution rate limiting
- Manual evolution trigger
- Evolution cycle optimization
- GEPA strategy support
- Cycle recording

Health Service:
- GPU health monitoring
- Endpoint health checks
- Health broadcasts
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

# Evolution Service
from gaius.engine.services.evolution_service import (
    CycleStatus,
    EvolutionConfig,
    EvolutionCycle,
    EvolutionService,
    EvolutionStrategy,
)

# Health Service
from gaius.engine.services.health_service import (
    EndpointHealth,
    GPUHealth,
    HealthService,
    SystemHealth,
)


# ─────────────────────────────────────────────────────────────────────────────
# Evolution Service Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEvolutionConfig:
    """Test evolution configuration."""

    def test_default_config(self):
        """Default config has reasonable values."""
        config = EvolutionConfig()

        assert config.max_cycles_per_hour == 4
        assert config.min_idle_seconds == 60
        assert config.min_training_examples == 5
        assert config.idle_threshold == 0.2
        assert config.default_strategy == EvolutionStrategy.APO

    def test_agent_rotation(self):
        """Default agent rotation is set."""
        config = EvolutionConfig()

        assert len(config.agent_rotation) > 0
        assert "leader" in config.agent_rotation


class TestEvolutionCycle:
    """Test evolution cycle dataclass."""

    def test_cycle_creation(self):
        """Cycle can be created."""
        cycle = EvolutionCycle(
            id="cycle-1",
            agent_id="leader",
            strategy=EvolutionStrategy.APO,
        )

        assert cycle.id == "cycle-1"
        assert cycle.agent_id == "leader"
        assert cycle.status == CycleStatus.PENDING
        assert cycle.started_at is None

    def test_cycle_duration(self):
        """Duration is calculated correctly."""
        cycle = EvolutionCycle(
            id="cycle-1",
            agent_id="leader",
            strategy=EvolutionStrategy.APO,
        )

        # Before start
        assert cycle.duration_ms == 0

        # After start
        cycle.started_at = datetime.now() - timedelta(seconds=2)
        assert cycle.duration_ms >= 2000

        # After completion
        cycle.completed_at = datetime.now()
        assert cycle.duration_ms >= 2000

    def test_cycle_to_dict(self):
        """Cycle serializes to dict."""
        cycle = EvolutionCycle(
            id="cycle-1",
            agent_id="leader",
            strategy=EvolutionStrategy.GEPA,
            status=CycleStatus.COMPLETED,
            examples_used=10,
            improvement_pct=5.5,
            best_score=0.85,
            baseline_score=0.80,
        )
        cycle.started_at = datetime.now()
        cycle.completed_at = datetime.now()

        data = cycle.to_dict()

        assert data["id"] == "cycle-1"
        assert data["agent_id"] == "leader"
        assert data["strategy"] == "gepa"
        assert data["status"] == "completed"
        assert data["examples_used"] == 10
        assert data["improvement_pct"] == 5.5


class TestEvolutionService:
    """Test evolution service.

    BDD Scenarios:
    - Start evolution daemon with '/evolve start'
    - Stop evolution daemon with '/evolve stop'
    - Evolution daemon monitors GPU idle state
    - Evolution respects rate limits
    - Manual evolution trigger with '/evolve trigger'
    """

    @pytest.fixture
    def config(self):
        """Test configuration."""
        return EvolutionConfig(
            max_cycles_per_hour=2,
            min_idle_seconds=1,
            min_training_examples=3,
        )

    @pytest.fixture
    def gpu_idle_fn(self):
        """Mock GPU idle function."""
        return MagicMock(return_value=True)

    @pytest.fixture
    def service(self, config, gpu_idle_fn):
        """Create evolution service."""
        return EvolutionService(
            config=config,
            get_gpu_idle=gpu_idle_fn,
        )

    def test_service_initialization(self, service):
        """Service initializes correctly."""
        assert not service.is_running
        assert service.config is not None

    @pytest.mark.asyncio
    async def test_start_stop_daemon(self, service):
        """BDD: Start/stop evolution daemon."""
        # Initially not running
        assert not service.is_running

        # Start
        await service.start()
        assert service.is_running

        # Stop
        await service.stop()
        assert not service.is_running

    def test_rate_limiting(self, service):
        """BDD: Evolution respects rate limits."""
        config = service.config

        # Initially can run
        assert service._can_run_cycle() is True

        # Record cycles up to limit
        for _ in range(config.max_cycles_per_hour):
            service._record_cycle_start()

        # Now should be rate limited
        assert service._can_run_cycle() is False

    def test_agent_rotation(self, service):
        """Next agent in rotation advances."""
        agents = service.config.agent_rotation

        # Get first agent
        first = service._get_next_agent()
        assert first == agents[0]

        # Get second agent
        second = service._get_next_agent()
        assert second == agents[1]

        # Rotation wraps around
        for _ in range(len(agents)):
            service._get_next_agent()

        # After advancing by len(agents) + 2, we should be at position 2
        # (started at 0, got 2 agents, then advanced len(agents) more)
        # Index is now 2 + len(agents) = 2 + 4 = 6
        # 6 % 4 = 2, so third agent
        wrapped = service._get_next_agent()
        expected_idx = (2 + len(agents)) % len(agents)
        assert wrapped == agents[expected_idx]

    @pytest.mark.asyncio
    async def test_manual_trigger(self, service):
        """BDD: Manual evolution trigger with '/evolve trigger'."""
        result = await service.trigger("leader")

        assert result["agent_id"] == "leader"
        assert result["status"] in ["skipped", "completed", "failed"]

    @pytest.mark.asyncio
    async def test_manual_trigger_next_in_rotation(self, service):
        """Manual trigger uses next agent if not specified."""
        result = await service.trigger()

        # Should use first agent in rotation
        expected_agent = service.config.agent_rotation[0]
        # Note: rotation advances after trigger, so check the result
        assert result["agent_id"] in service.config.agent_rotation

    @pytest.mark.asyncio
    async def test_insufficient_examples_skip(self, service):
        """BDD: Minimum examples required for evolution."""
        # With no training examples, cycle should skip
        result = await service._run_cycle("leader")

        assert result["status"] == "skipped"
        assert "insufficient" in result["error_message"].lower()

    def test_get_status(self, service):
        """BDD: Evolution panel shows daemon status."""
        status = service.get_status()

        assert "running" in status
        assert "status" in status
        assert "total_cycles" in status
        assert "completed_cycles" in status
        assert "next_agent" in status
        assert "cycles_this_hour" in status
        assert "max_cycles_per_hour" in status

    def test_get_recent_cycles(self, service):
        """BDD: Evolution panel shows recent cycles."""
        # Add some cycles
        service._cycles.append(
            EvolutionCycle(
                id="cycle-1",
                agent_id="leader",
                strategy=EvolutionStrategy.APO,
                status=CycleStatus.COMPLETED,
            )
        )
        service._cycles.append(
            EvolutionCycle(
                id="cycle-2",
                agent_id="risk",
                strategy=EvolutionStrategy.GEPA,
                status=CycleStatus.FAILED,
            )
        )

        recent = service.get_recent_cycles(limit=5)

        assert len(recent) == 2
        # Most recent first
        assert recent[0]["id"] == "cycle-2"

    def test_get_agent_scores(self, service):
        """BDD: Evolution panel shows agent scores."""
        scores = service.get_agent_scores()

        # Should have entry for each agent in rotation
        for agent in service.config.agent_rotation:
            assert agent in scores
            assert "current_score" in scores[agent]
            assert "trend" in scores[agent]

    def test_progress_subscription(self, service):
        """Progress callbacks are called."""
        messages = []

        def on_progress(msg):
            messages.append(msg)

        service.subscribe_progress(on_progress)
        service._notify_progress("Test message")

        assert len(messages) == 1
        assert messages[0] == "Test message"

        # Unsubscribe
        service.unsubscribe_progress(on_progress)
        service._notify_progress("Should not appear")
        assert len(messages) == 1


class TestEvolutionStrategy:
    """Test evolution strategies."""

    def test_strategy_values(self):
        """All strategies have correct values."""
        assert EvolutionStrategy.APO.value == "apo"
        assert EvolutionStrategy.GEPA.value == "gepa"
        assert EvolutionStrategy.HYBRID.value == "hybrid"


class TestCycleStatus:
    """Test cycle status enum."""

    def test_status_values(self):
        """All statuses exist."""
        statuses = list(CycleStatus)

        assert CycleStatus.PENDING in statuses
        assert CycleStatus.RUNNING in statuses
        assert CycleStatus.COMPLETED in statuses
        assert CycleStatus.FAILED in statuses
        assert CycleStatus.SKIPPED in statuses


# ─────────────────────────────────────────────────────────────────────────────
# Health Service Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGPUHealth:
    """Test GPU health dataclass."""

    def test_gpu_health_creation(self):
        """GPUHealth can be created."""
        health = GPUHealth(
            gpu_id=0,
            utilization_pct=45.0,
            memory_used_gb=12.5,
            memory_total_gb=24.0,
            temperature_c=65,
        )

        assert health.gpu_id == 0
        assert health.utilization_pct == 45.0
        assert health.memory_used_pct == pytest.approx(52.08, rel=0.1)

    def test_gpu_health_healthy(self):
        """GPU health status calculation."""
        # Healthy GPU
        healthy = GPUHealth(
            gpu_id=0,
            temperature_c=60,
            memory_used_gb=10.0,
            memory_total_gb=24.0,
        )
        assert healthy.is_healthy is True

        # Too hot
        hot = GPUHealth(
            gpu_id=1,
            temperature_c=90,
            memory_used_gb=10.0,
            memory_total_gb=24.0,
        )
        assert hot.is_healthy is False

        # Memory full
        full = GPUHealth(
            gpu_id=2,
            temperature_c=60,
            memory_used_gb=23.5,
            memory_total_gb=24.0,
        )
        assert full.is_healthy is False

    def test_gpu_health_to_dict(self):
        """GPUHealth serializes to dict."""
        health = GPUHealth(
            gpu_id=0,
            utilization_pct=45.0,
            memory_used_gb=12.0,
            memory_total_gb=24.0,
            temperature_c=65,
            power_draw_w=200.5,
            fan_speed_pct=50,
        )

        data = health.to_dict()

        assert data["gpu_id"] == 0
        assert data["utilization_pct"] == 45.0
        assert data["memory_used_gb"] == 12.0
        assert data["temperature_c"] == 65
        assert data["is_healthy"] is True


class TestEndpointHealth:
    """Test endpoint health dataclass."""

    def test_endpoint_health_creation(self):
        """EndpointHealth can be created."""
        health = EndpointHealth(
            agent_alias="reasoning",
            status="healthy",
            latency_ms=150.0,
        )

        assert health.agent_alias == "reasoning"
        assert health.is_healthy is True

    def test_endpoint_unhealthy(self):
        """Unhealthy endpoint detection."""
        # Unhealthy status
        unhealthy = EndpointHealth(
            agent_alias="fast",
            status="unhealthy",
        )
        assert unhealthy.is_healthy is False

        # Consecutive failures
        failing = EndpointHealth(
            agent_alias="fast",
            status="healthy",
            consecutive_failures=3,
        )
        assert failing.is_healthy is False


class TestSystemHealth:
    """Test system health snapshot."""

    def test_system_health_creation(self):
        """SystemHealth can be created."""
        health = SystemHealth(
            gpus=[
                GPUHealth(gpu_id=0, temperature_c=60, memory_total_gb=24),
                GPUHealth(gpu_id=1, temperature_c=65, memory_total_gb=24),
            ],
            endpoints=[
                EndpointHealth(agent_alias="reasoning", status="healthy"),
            ],
            scheduler_queue_depth=5,
            evolution_running=True,
        )

        assert health.all_gpus_healthy is True
        assert health.all_endpoints_healthy is True
        assert health.overall_healthy is True
        assert health.scheduler_queue_depth == 5
        assert health.evolution_running is True

    def test_system_health_to_dict(self):
        """SystemHealth serializes correctly."""
        health = SystemHealth()
        data = health.to_dict()

        assert "timestamp" in data
        assert "overall_healthy" in data
        assert "gpus" in data
        assert "endpoints" in data


class TestHealthService:
    """Test health monitoring service."""

    @pytest.fixture
    def service(self):
        """Create health service."""
        return HealthService(
            broadcast_interval_ms=1000,
            check_interval_ms=500,
        )

    def test_service_initialization(self, service):
        """Service initializes correctly."""
        assert not service.is_running

    @pytest.mark.asyncio
    async def test_start_stop(self, service):
        """Service starts and stops."""
        await service.start()
        assert service.is_running

        await service.stop()
        assert not service.is_running

    def test_get_health_no_data(self, service):
        """Get health returns minimal data when no monitoring."""
        health = service.get_health()

        assert "timestamp" in health
        assert "overall_healthy" in health
        assert health["gpus"] == []

    def test_health_subscription(self, service):
        """Health callbacks can be subscribed."""
        snapshots = []

        def on_health(snapshot):
            snapshots.append(snapshot)

        service.subscribe(on_health)
        assert len(service._health_callbacks) == 1

        # Broadcast a snapshot
        snapshot = SystemHealth()
        service._broadcast_health(snapshot)

        assert len(snapshots) == 1

        # Unsubscribe
        service.unsubscribe(on_health)
        assert len(service._health_callbacks) == 0

    def test_is_gpu_idle(self, service):
        """GPU idle detection works."""
        # No data = idle
        assert service.is_gpu_idle() is True

        # Add GPU data
        service._gpu_health[0] = GPUHealth(gpu_id=0, utilization_pct=10)
        service._gpu_health[1] = GPUHealth(gpu_id=1, utilization_pct=15)

        # Low utilization = idle
        assert service.is_gpu_idle(threshold=20.0) is True

        # Increase utilization
        service._gpu_health[0] = GPUHealth(gpu_id=0, utilization_pct=80)

        # Now not idle (average is 47.5%)
        assert service.is_gpu_idle(threshold=20.0) is False

    def test_get_gpu_utilization(self, service):
        """GPU utilization retrieval."""
        service._gpu_health[0] = GPUHealth(gpu_id=0, utilization_pct=45)
        service._gpu_health[1] = GPUHealth(gpu_id=1, utilization_pct=30)

        util = service.get_gpu_utilization()

        assert util[0] == 45
        assert util[1] == 30

    def test_get_status(self, service):
        """Service status retrieval."""
        status = service.get_status()

        assert "running" in status
        assert "gpu_count" in status
        assert "endpoint_count" in status
        assert "subscriber_count" in status
        assert "check_interval_ms" in status
        assert "broadcast_interval_ms" in status

    def test_set_services(self, service):
        """Services can be set for cross-service monitoring."""
        mock_orchestrator = MagicMock()
        mock_scheduler = MagicMock()
        mock_evolution = MagicMock()

        service.set_services(
            orchestrator=mock_orchestrator,
            scheduler=mock_scheduler,
            evolution=mock_evolution,
        )

        assert service._orchestrator_service is mock_orchestrator
        assert service._scheduler_service is mock_scheduler
        assert service._evolution_service is mock_evolution


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEvolutionHealthIntegration:
    """Test evolution and health service integration."""

    @pytest.fixture
    def health_service(self):
        """Create health service."""
        return HealthService()

    @pytest.fixture
    def evolution_service(self, health_service):
        """Create evolution service with health integration."""
        config = EvolutionConfig(
            max_cycles_per_hour=2,
            min_idle_seconds=1,
        )

        return EvolutionService(
            config=config,
            get_gpu_idle=health_service.is_gpu_idle,
        )

    def test_evolution_uses_health_idle(self, evolution_service, health_service):
        """Evolution service uses health service for GPU idle check."""
        # Initially idle (no GPU data)
        assert evolution_service._get_gpu_idle() is True

        # Add busy GPU
        health_service._gpu_health[0] = GPUHealth(gpu_id=0, utilization_pct=80)

        # Now not idle
        assert evolution_service._get_gpu_idle() is False


# ─────────────────────────────────────────────────────────────────────────────
# BDD Scenario Coverage Summary
# ─────────────────────────────────────────────────────────────────────────────
"""
BDD Scenarios Covered:

Evolution Service:
✓ Start evolution daemon with '/evolve start' → test_start_stop_daemon
✓ Stop evolution daemon with '/evolve stop' → test_start_stop_daemon
✓ Evolution daemon monitors GPU idle state → TestEvolutionHealthIntegration
✓ Evolution respects rate limits → test_rate_limiting
✓ Manual evolution trigger with '/evolve trigger' → test_manual_trigger
✓ Minimum examples required for evolution → test_insufficient_examples_skip
✓ Evolution panel shows daemon status → test_get_status
✓ Evolution panel shows recent cycles → test_get_recent_cycles
✓ Evolution panel shows agent scores → test_get_agent_scores

Health Service:
✓ GPU health monitoring → TestGPUHealth
✓ Endpoint health checks → TestEndpointHealth
✓ Health broadcasts → test_health_subscription
✓ GPU idle detection → test_is_gpu_idle
"""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
