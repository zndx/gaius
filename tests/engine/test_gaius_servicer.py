"""Tests for the GaiusServicer gRPC handler.

This is the central nervous system of Gaius - the gRPC servicer that
handles all client requests. Testing here ensures the engine responds
correctly to service calls.

Critical Path Coverage:
1. Orchestrator methods (status, start/stop endpoints)
2. Scheduler methods (complete, status)
3. Health and status mapping
4. Error handling for missing services
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass
from typing import Optional, cast, TYPE_CHECKING
from google.protobuf import empty_pb2

if TYPE_CHECKING:
    from gaius.engine.grpc.server import ServiceRegistry

# Generated protobuf messages
from gaius.engine.generated import (
    ProcessStatus,
    PROCESS_STATUS_UNSPECIFIED,
    PROCESS_STATUS_STOPPED,
    PROCESS_STATUS_STARTING,
    PROCESS_STATUS_HEALTHY,
    PROCESS_STATUS_UNHEALTHY,
    PROCESS_STATUS_FAILED,
    PROCESS_STATUS_PENDING,
    OrchestratorStatusResponse,
    StartEndpointRequest,
    StopEndpointRequest,
    RestartEndpointRequest,
    CleanStartRequest,
    EndpointResponse,
    CompleteRequest,
    CompleteResponse,
    SchedulerStatusResponse,
)

from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer, _status_to_enum


# ─────────────────────────────────────────────────────────────────────────────
# Status Mapping Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusMapping:
    """Test string-to-enum status conversion."""

    def test_status_to_enum_healthy(self):
        """'healthy' maps to PROCESS_STATUS_HEALTHY."""
        assert _status_to_enum("healthy") == PROCESS_STATUS_HEALTHY

    def test_status_to_enum_running_alias(self):
        """'running' is an alias for healthy."""
        assert _status_to_enum("running") == PROCESS_STATUS_HEALTHY

    def test_status_to_enum_ready_alias(self):
        """'ready' is an alias for healthy (InitController uses this)."""
        assert _status_to_enum("ready") == PROCESS_STATUS_HEALTHY

    def test_status_to_enum_stopped(self):
        """'stopped' maps to PROCESS_STATUS_STOPPED."""
        assert _status_to_enum("stopped") == PROCESS_STATUS_STOPPED

    def test_status_to_enum_starting(self):
        """'starting' maps to PROCESS_STATUS_STARTING."""
        assert _status_to_enum("starting") == PROCESS_STATUS_STARTING

    def test_status_to_enum_unhealthy(self):
        """'unhealthy' maps to PROCESS_STATUS_UNHEALTHY."""
        assert _status_to_enum("unhealthy") == PROCESS_STATUS_UNHEALTHY

    def test_status_to_enum_failed(self):
        """'failed' maps to PROCESS_STATUS_FAILED."""
        assert _status_to_enum("failed") == PROCESS_STATUS_FAILED

    def test_status_to_enum_error_alias(self):
        """'error' is an alias for failed."""
        assert _status_to_enum("error") == PROCESS_STATUS_FAILED

    def test_status_to_enum_pending(self):
        """'pending' maps to PROCESS_STATUS_PENDING."""
        assert _status_to_enum("pending") == PROCESS_STATUS_PENDING

    def test_status_to_enum_unknown(self):
        """Unknown status maps to UNSPECIFIED."""
        assert _status_to_enum("unknown") == PROCESS_STATUS_UNSPECIFIED
        assert _status_to_enum("garbage") == PROCESS_STATUS_UNSPECIFIED

    def test_status_to_enum_case_insensitive(self):
        """Status mapping is case-insensitive."""
        assert _status_to_enum("HEALTHY") == PROCESS_STATUS_HEALTHY
        assert _status_to_enum("Healthy") == PROCESS_STATUS_HEALTHY
        assert _status_to_enum("HeAlThY") == PROCESS_STATUS_HEALTHY


# ─────────────────────────────────────────────────────────────────────────────
# ServiceRegistry Mock
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MockEndpointStatus:
    """Mock endpoint status returned by orchestrator."""
    status: str = "healthy"
    port: Optional[int] = 8000
    gpu_ids: Optional[list] = None
    startup_message: Optional[str] = None


@dataclass
class MockCompletionResult:
    """Mock completion result from backend router."""
    content: str = "Hello from LLM"
    output_tokens: int = 50
    model: str = "test-model"


class MockServiceRegistry:
    """Mock ServiceRegistry for testing.

    Provides the same interface as ServiceRegistry but with MagicMock services.
    Use as_registry() to get a properly typed reference for the servicer.
    """

    def __init__(
        self,
        has_orchestrator: bool = True,
        has_router: bool = True,
        has_config: bool = True,
    ):
        self.orchestrator_service = MagicMock() if has_orchestrator else None
        self.backend_router = MagicMock() if has_router else None
        self.init_controller = None

        if has_config:
            self.config = MagicMock()
            self.config.gpus.total = 4
            self.config.gpus.reserved = []
        else:
            self.config = None

    def as_registry(self) -> "ServiceRegistry":
        """Return self cast to ServiceRegistry for type-safe servicer init."""
        # MockServiceRegistry implements the ServiceRegistry protocol;
        # cast is safe because we provide all required attributes
        return cast("ServiceRegistry", self)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestratorStatus:
    """Test OrchestratorStatus RPC."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_orchestrator_status_returns_gpu_count(self, servicer, services, context):
        """OrchestratorStatus returns GPU counts from config."""
        services.orchestrator_service.get_status.return_value = {"endpoints": {}}

        response = await servicer.OrchestratorStatus(empty_pb2.Empty(), context)

        assert response.total_gpus == 4
        assert response.available_gpus == 4

    @pytest.mark.asyncio
    async def test_orchestrator_status_includes_endpoints(self, servicer, services, context):
        """OrchestratorStatus includes endpoint info."""
        services.orchestrator_service.get_status.return_value = {
            "endpoints": {
                "reasoning": {
                    "model": "qwen-32b",
                    "status": "healthy",
                    "port": 8000,
                },
                "fast": {
                    "model": "llama-8b",
                    "status": "starting",
                    "port": 8001,
                },
            }
        }

        response = await servicer.OrchestratorStatus(empty_pb2.Empty(), context)

        assert len(response.endpoints) == 2

        # Find endpoints by name
        endpoints = {ep.name: ep for ep in response.endpoints}

        assert endpoints["reasoning"].status == PROCESS_STATUS_HEALTHY
        assert endpoints["reasoning"].port == 8000
        assert endpoints["fast"].status == PROCESS_STATUS_STARTING

    @pytest.mark.asyncio
    async def test_orchestrator_status_no_orchestrator(self, context):
        """OrchestratorStatus works without orchestrator service."""
        services = MockServiceRegistry(has_orchestrator=False)
        servicer = GaiusServicer(services.as_registry())

        response = await servicer.OrchestratorStatus(empty_pb2.Empty(), context)

        # Should still return GPU info from config
        assert response.total_gpus == 4


class TestStartEndpoint:
    """Test StartEndpoint RPC."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_start_endpoint_success(self, servicer, services, context):
        """StartEndpoint returns success when endpoint starts."""
        services.orchestrator_service.start_endpoint = AsyncMock(
            return_value=MockEndpointStatus(status="healthy", port=8000)
        )

        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, context)

        assert response.success is True
        assert "started" in response.message

    @pytest.mark.asyncio
    async def test_start_endpoint_no_orchestrator(self, context):
        """StartEndpoint fails without orchestrator service."""
        services = MockServiceRegistry(has_orchestrator=False)
        servicer = GaiusServicer(services.as_registry())

        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, context)

        assert response.success is False
        assert "not initialized" in response.message

    @pytest.mark.asyncio
    async def test_start_endpoint_handles_exception(self, servicer, services, context):
        """StartEndpoint handles orchestrator exceptions."""
        services.orchestrator_service.start_endpoint = AsyncMock(
            side_effect=RuntimeError("GPU out of memory")
        )

        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, context)

        assert response.success is False
        assert "GPU out of memory" in response.message


class TestStopEndpoint:
    """Test StopEndpoint RPC."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_stop_endpoint_success(self, servicer, services, context):
        """StopEndpoint returns success when endpoint stops."""
        services.orchestrator_service.stop_endpoint = AsyncMock(return_value=True)

        request = StopEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StopEndpoint(request, context)

        assert response.success is True
        assert "stopped" in response.message

    @pytest.mark.asyncio
    async def test_stop_endpoint_no_orchestrator(self, context):
        """StopEndpoint fails without orchestrator service."""
        services = MockServiceRegistry(has_orchestrator=False)
        servicer = GaiusServicer(services.as_registry())

        request = StopEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StopEndpoint(request, context)

        assert response.success is False
        assert "not initialized" in response.message


class TestRestartEndpoint:
    """Test RestartEndpoint RPC."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_restart_endpoint_success(self, servicer, services, context):
        """RestartEndpoint returns success when endpoint restarts."""
        services.orchestrator_service.restart_endpoint = AsyncMock(
            return_value=MockEndpointStatus(status="healthy", port=8000)
        )

        request = RestartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.RestartEndpoint(request, context)

        assert response.success is True
        assert "restarted" in response.message


class TestCleanStart:
    """Test CleanStart RPC."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_clean_start_success(self, servicer, services, context):
        """CleanStart kills stale processes and starts endpoints."""
        services.orchestrator_service.clean_start = AsyncMock(
            return_value={
                "cleanup": {"processes_killed": 3},
                "started": ["reasoning", "fast"],
            }
        )

        request = CleanStartRequest(endpoints=["reasoning", "fast"])
        response = await servicer.CleanStart(request, context)

        assert response.success is True
        assert response.processes_killed == 3
        assert response.endpoints_started == 2

    @pytest.mark.asyncio
    async def test_clean_start_no_orchestrator(self, context):
        """CleanStart fails without orchestrator service."""
        services = MockServiceRegistry(has_orchestrator=False)
        servicer = GaiusServicer(services.as_registry())

        request = CleanStartRequest()
        response = await servicer.CleanStart(request, context)

        assert response.success is False
        assert "not initialized" in response.message


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSchedulerStatus:
    """Test SchedulerStatus RPC."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_scheduler_status_returns_metrics(self, servicer, services, context):
        """SchedulerStatus returns queue metrics."""
        services.backend_router.get_status.return_value = {
            "queue_depth": 5,
            "active_jobs": 2,
            "avg_latency_ms": 150.5,
        }

        response = await servicer.SchedulerStatus(empty_pb2.Empty(), context)

        assert response.queue_depth == 5
        assert response.active_jobs == 2
        assert response.avg_latency_ms == pytest.approx(150.5)

    @pytest.mark.asyncio
    async def test_scheduler_status_no_router(self, context):
        """SchedulerStatus returns zeros without router."""
        services = MockServiceRegistry(has_router=False)
        servicer = GaiusServicer(services.as_registry())

        response = await servicer.SchedulerStatus(empty_pb2.Empty(), context)

        assert response.queue_depth == 0
        assert response.active_jobs == 0


class TestComplete:
    """Test Complete RPC - the primary inference endpoint."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        ctx = MagicMock()
        ctx.set_code = MagicMock()
        ctx.set_details = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_complete_success(self, servicer, services, context):
        """Complete returns LLM response."""
        services.backend_router.complete = AsyncMock(
            return_value=MockCompletionResult(
                content="The answer is 42.",
                output_tokens=10,
                model="qwen-32b",
            )
        )

        request = CompleteRequest(
            prompt="What is the answer?",
            agent_alias="reasoning",
            temperature=0.7,
            max_tokens=100,
        )
        response = await servicer.Complete(request, context)

        assert response.text == "The answer is 42."
        assert response.tokens_used == 10
        assert response.model == "qwen-32b"
        assert response.latency_ms > 0

    @pytest.mark.asyncio
    async def test_complete_uses_default_agent(self, servicer, services, context):
        """Complete uses 'fast' as default agent."""
        services.backend_router.complete = AsyncMock(
            return_value=MockCompletionResult()
        )

        request = CompleteRequest(prompt="Hello")
        await servicer.Complete(request, context)

        # Verify the backend was called with 'fast' as default
        call_kwargs = services.backend_router.complete.call_args.kwargs
        assert call_kwargs["agent_alias"] == "fast"

    @pytest.mark.asyncio
    async def test_complete_no_router(self, context):
        """Complete fails without backend router."""
        services = MockServiceRegistry(has_router=False)
        servicer = GaiusServicer(services.as_registry())

        request = CompleteRequest(prompt="Hello")
        response = await servicer.Complete(request, context)

        # Should set gRPC error status
        context.set_code.assert_called()
        context.set_details.assert_called_with("Backend router not initialized")

    @pytest.mark.asyncio
    async def test_complete_handles_exception(self, servicer, services, context):
        """Complete handles backend exceptions."""
        services.backend_router.complete = AsyncMock(
            side_effect=RuntimeError("Model unavailable")
        )

        request = CompleteRequest(prompt="Hello")
        await servicer.Complete(request, context)

        # Should set gRPC error status
        context.set_code.assert_called()
        context.set_details.assert_called_with("Model unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# Free GPU Selection Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGetFreeGPU:
    """Test GPU selection logic."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    def test_get_free_gpu_from_resource_manager(self, servicer, services):
        """Free GPU is selected from ResourceManager."""
        services.orchestrator_service.resource_manager = MagicMock()
        services.orchestrator_service.resource_manager.get_free_gpus.return_value = [2, 3]

        gpu = servicer._get_free_gpu()

        # Should select highest-numbered free GPU
        assert gpu == 3

    def test_get_free_gpu_fallback_to_config(self, servicer, services):
        """Falls back to config when no ResourceManager."""
        # Remove resource_manager attribute
        del services.orchestrator_service.resource_manager

        gpu = servicer._get_free_gpu()

        # Should return GPU 3 (total - 1 = 4 - 1 = 3)
        assert gpu == 3

    def test_get_free_gpu_no_config(self, servicer, services):
        """Falls back to GPU 0 with no config."""
        services.config = None
        del services.orchestrator_service.resource_manager

        gpu = servicer._get_free_gpu()

        assert gpu == 0


# ─────────────────────────────────────────────────────────────────────────────
# XAI Budget Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestXAIBudget:
    """Test XAI budget status endpoint."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_xai_budget_returns_limits(self, servicer, context):
        """XAIBudget returns configured limits."""
        response = await servicer.XAIBudget(empty_pb2.Empty(), context)

        # Check default limits are returned
        assert response.daily_limit == 50
        assert response.weekly_limit == 200
        assert response.daily_used == 0
        assert response.weekly_used == 0
        assert response.reset_at  # Should have a valid ISO timestamp


# ─────────────────────────────────────────────────────────────────────────────
# Submit/GetJob Tests (Placeholder functionality)
# ─────────────────────────────────────────────────────────────────────────────


class TestJobManagement:
    """Test async job submission and retrieval."""

    @pytest.fixture
    def services(self):
        """Create mock service registry."""
        return MockServiceRegistry()

    @pytest.fixture
    def servicer(self, services):
        """Create servicer with mock services."""
        return GaiusServicer(services.as_registry())

    @pytest.fixture
    def context(self):
        """Create mock gRPC context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_submit_job_returns_id(self, servicer, context):
        """SubmitJob returns a job ID."""
        from gaius.engine.generated import SubmitJobRequest

        request = SubmitJobRequest(prompt="Process this")
        response = await servicer.SubmitJob(request, context)

        assert response.job_id.startswith("job-")
        assert response.status == "queued"

    @pytest.mark.asyncio
    async def test_get_job_result(self, servicer, context):
        """GetJobResult returns job status."""
        from gaius.engine.generated import GetJobResultRequest

        request = GetJobResultRequest(job_id="job-abc123")
        response = await servicer.GetJobResult(request, context)

        assert response.job_id == "job-abc123"
        assert response.status == "pending"


# ─────────────────────────────────────────────────────────────────────────────
# Coverage Summary
# ─────────────────────────────────────────────────────────────────────────────
"""
Coverage Focus:

1. Status Mapping (lines 262-278):
   - All string-to-enum conversions
   - Case insensitivity
   - Unknown status handling

2. Orchestrator (lines 324-551):
   - OrchestratorStatus with/without services
   - StartEndpoint success/failure/exception
   - StopEndpoint success/failure
   - RestartEndpoint success
   - CleanStart success/failure

3. Scheduler (lines 557-671):
   - SchedulerStatus with/without router
   - Complete success/failure/exception
   - Default agent alias handling
   - SubmitJob/GetJobResult placeholders

4. GPU Selection (lines 292-318):
   - ResourceManager selection
   - Config fallback
   - Ultimate fallback to GPU 0

5. XAI Budget (lines 642-671):
   - Budget limits returned correctly
"""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
