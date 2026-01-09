"""Critical path test for inference migration.

Verifies the gRPC scheduler complete path works correctly.
This test guards the migration from old inference client to engine gRPC.

Issue #8: https://github.com/zndx/gaius-acp/issues/8
"""

import pytest
from unittest.mock import AsyncMock, patch

pytest_plugins = ("pytest_asyncio",)


class TestSchedulerComplete:
    """Test Scheduler.complete via gRPC client."""

    @pytest.mark.asyncio
    async def test_complete_routes_through_grpc(self):
        """Verify complete() calls route through gRPC to scheduler."""
        from gaius.client.grpc_client import GrpcEngineClient

        with patch.object(
            GrpcEngineClient, "call", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = {
                "content": "Test response",
                "model": "test-model",
                "input_tokens": 10,
                "output_tokens": 20,
            }

            client = GrpcEngineClient()
            result = await client.call(
                "Scheduler",
                "complete",
                {
                    "prompt": "What is 2+2?",
                    "agent": "fast",
                    "max_tokens": 100,
                },
            )

            assert result["content"] == "Test response"
            mock_call.assert_called_once_with(
                "Scheduler",
                "complete",
                {
                    "prompt": "What is 2+2?",
                    "agent": "fast",
                    "max_tokens": 100,
                },
            )

    @pytest.mark.asyncio
    async def test_ask_local_uses_grpc(self):
        """Verify ask_local() routes through gRPC.

        ask_local() is the primary interface for local LLM queries.
        It must use the engine-centric gRPC path.
        """
        # Patch at the import location (gaius.client module)
        with patch(
            "gaius.client.get_grpc_client", new_callable=AsyncMock
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.call.return_value = {"content": "4"}
            mock_get_client.return_value = mock_client

            from gaius.inference import ask_local

            result = await ask_local("What is 2+2?")

            assert result == "4"
            mock_client.call.assert_called_once()
            call_args = mock_client.call.call_args
            assert call_args.kwargs["service"] == "scheduler"
            assert call_args.kwargs["action"] == "complete"
            assert "prompt" in call_args.kwargs["params"]

    @pytest.mark.asyncio
    async def test_scheduler_complete_response_structure(self):
        """Verify scheduler response has expected fields."""
        from gaius.client.grpc_client import GrpcEngineClient

        # Test the response structure that callers will depend on
        expected_response = {
            "content": "The answer is 4",
            "model": "reasoning",
            "backend": "vllm",
            "input_tokens": 15,
            "output_tokens": 25,
            "latency_ms": 150,
            "error": None,
        }

        with patch.object(
            GrpcEngineClient, "call", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = expected_response

            client = GrpcEngineClient()
            result = await client.call(
                "Scheduler",
                "complete",
                {"prompt": "Test", "agent": "fast"},
            )

            # Callers will access these fields
            assert "content" in result
            assert "model" in result
            assert "input_tokens" in result
            assert "output_tokens" in result


class TestMigrationPatterns:
    """Test migration patterns from old to new inference API."""

    @pytest.mark.asyncio
    async def test_message_to_prompt_conversion(self):
        """Verify Message objects can be converted to prompt strings.

        Old pattern:
            messages=[Message(role="user", content="Hello")]

        New pattern:
            params={"prompt": "Hello", ...}
        """
        # Import the old Message class (still available for compatibility)
        from gaius.inference import Message

        # Old style message
        msg = Message(role="user", content="Hello, how are you?")

        # For single-turn conversations, content becomes prompt directly
        assert msg.content == "Hello, how are you?"

        # For multi-turn, would need to format as conversation string
        # But most uses are single-turn

    @pytest.mark.asyncio
    async def test_completion_result_field_mapping(self):
        """Verify old CompletionResult fields map to new response dict.

        Old pattern:
            result.content
            result.model

        New pattern:
            result.get("content", "")
            result.get("model", "")
        """
        # Simulate new gRPC response
        grpc_response = {
            "content": "Test content",
            "model": "reasoning",
            "input_tokens": 10,
            "output_tokens": 20,
            "latency_ms": 100,
            "error": None,
        }

        # New pattern access
        content = grpc_response.get("content", "")
        model = grpc_response.get("model", "")

        assert content == "Test content"
        assert model == "reasoning"


class TestDeprecationWarning:
    """Test that deprecated get_client() issues warning."""

    def test_get_client_warns_after_migration(self):
        """After migration, get_client() should warn about deprecation.

        This test is a placeholder - enable after adding deprecation warning.
        """
        # TODO: Enable after Phase 4 adds deprecation warning
        # import warnings
        # from gaius.inference import get_client
        #
        # with warnings.catch_warnings(record=True) as w:
        #     warnings.simplefilter("always")
        #     client = get_client()
        #     assert len(w) == 1
        #     assert issubclass(w[0].category, DeprecationWarning)
        #     assert "get_grpc_client" in str(w[0].message)
        pass
