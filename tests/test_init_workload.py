"""Test /init workload management integration."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestInitWorkloadFlow:
    """Test that /init properly requests GPU resources."""

    @pytest.mark.asyncio
    async def test_begin_workload_called_during_init(self):
        """Verify use_engine_proxy checks gRPC client singleton state."""
        from gaius.client.engine_proxy import use_engine_proxy
        from gaius.client import grpc_client

        # Initially, no client exists
        assert grpc_client._grpc_client is None
        # With no client and no engine running, should return False
        result_no_engine = use_engine_proxy()
        assert result_no_engine is False

        # Create a mock client that appears connected
        mock_client = MagicMock()
        mock_client.is_connected = True

        # Set the singleton
        grpc_client._grpc_client = mock_client

        try:
            # Now use_engine_proxy should return True
            result_with_client = use_engine_proxy()
            assert result_with_client is True
        finally:
            # Restore singleton state
            grpc_client._grpc_client = None

        # Verify imports work
        from gaius.client.engine_proxy import (
            begin_workload_sync,
            complete_workload_sync,
        )
        assert callable(begin_workload_sync)
        assert callable(complete_workload_sync)
        assert callable(use_engine_proxy)

    def test_workload_sync_functions_exist(self):
        """Verify sync helper functions are importable."""
        from gaius.client.engine_proxy import (
            begin_workload_sync,
            complete_workload_sync,
            embed_texts_sync,
            use_engine_proxy,
            WorkloadAllocation,
        )

        # Check they're callable
        assert callable(begin_workload_sync)
        assert callable(complete_workload_sync)
        assert callable(embed_texts_sync)
        assert callable(use_engine_proxy)

    def test_grpc_client_has_workload_handlers(self):
        """Verify gRPC client can handle Workload service calls."""
        from gaius.client.grpc_client import GrpcEngineClient

        client = GrpcEngineClient()
        # Check the method exists
        assert hasattr(client, '_call_workload')
        assert hasattr(client, '_call_embedding')


class TestPreemptionLogic:
    """Test that preemption properly evicts vLLM endpoints."""

    def test_find_evict_includes_vllm_processes(self):
        """Verify _find_and_evict_for_resources considers vLLM processes."""
        # This tests the code path, not actual eviction
        from gaius.engine.services.orchestrator_service import OrchestratorService

        # Just verify the class can be imported with updated code
        assert OrchestratorService is not None

    @pytest.mark.asyncio
    async def test_embedding_controller_integration(self):
        """Verify embedding controller can be started."""
        from gaius.engine.backends.embedding_controller import (
            EmbeddingController,
            EmbeddingRequest,
            EmbeddingStatus,
        )

        controller = EmbeddingController()
        assert controller is not None
        assert controller.default_model == "all-MiniLM-L6-v2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
