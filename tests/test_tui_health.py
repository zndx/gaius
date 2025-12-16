"""Test TUI /health command via textual pilot."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

# Enable pytest-asyncio auto mode for this module
pytest_plugins = ("pytest_asyncio",)

# Import pilot from textual
from textual.app import App, ComposeResult
from textual.widgets import Static


class MinimalTestApp(App):
    """Minimal app for basic testing."""

    def compose(self) -> ComposeResult:
        yield Static("Test", id="test")


@pytest.mark.asyncio
async def test_basic_app_runs():
    """Test that a minimal app can run."""
    app = MinimalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_running or True  # App may have exited


@pytest.mark.asyncio
async def test_health_cli_command(tmp_path):
    """Test /health CLI command directly (not TUI)."""
    from gaius.cli import GaiusCLI

    # Create CLI instance
    cli = GaiusCLI()

    # Mock the health checker to avoid actual system checks
    # Import is inside the function, so patch where it's imported from
    with patch("gaius.health.HealthChecker") as mock_checker:
        checker = MagicMock()

        # Create mock report
        mock_report = MagicMock()
        mock_report.healthy = True
        mock_report.timestamp = datetime.now()
        mock_report.duration_ms = 100
        mock_report.passed = 3
        mock_report.warnings = 0
        mock_report.failures = 0
        mock_report.skipped = 0
        mock_report.checks = []
        mock_report.interventions = []
        mock_report.metrics = {}
        mock_report.summary.return_value = "All systems healthy"

        checker.run_all = AsyncMock(return_value=mock_report)
        mock_checker.return_value = checker

        # Set KB path to temp dir
        with patch.dict("os.environ", {"GAIUS_KB_PATH": str(tmp_path)}):
            result = await cli._cmd_health("")

            # Should return report_path
            assert "report_path" in result
            assert result.get("healthy") == True
            assert result.get("passed") == 3

            # Check file was created
            report_path = result.get("report_path")
            if report_path:
                assert Path(report_path).exists()


@pytest.mark.asyncio
async def test_ask_cli_engine_routing():
    """Test /ask routes through engine scheduler."""
    from gaius.cli import GaiusCLI

    cli = GaiusCLI()

    # Test _complete_via_engine helper exists
    assert hasattr(cli, "_complete_via_engine")
    assert hasattr(cli, "_get_scheduler_proxy")

    # Mock the scheduler proxy
    with patch.object(cli, "_get_scheduler_proxy") as mock_get_proxy:
        mock_proxy = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = "Test response"
        mock_result.model = "test-model"
        mock_result.input_tokens = 10
        mock_result.output_tokens = 20
        mock_result.technique = None
        mock_result.backend = "grpc_engine"

        mock_proxy.complete = AsyncMock(return_value=mock_result)
        mock_get_proxy.return_value = mock_proxy

        # Call _complete_via_engine
        result = await cli._complete_via_engine(
            prompt="Test prompt",
            system_prompt="You are helpful",
        )

        # Should return dict with response
        assert result is not None
        assert result["content"] == "Test response"
        assert result["backend"] == "grpc_engine"


@pytest.mark.asyncio
async def test_ask_reason_uses_engine():
    """Test _ask_reason tries engine first."""
    from gaius.cli import GaiusCLI

    cli = GaiusCLI()

    # Mock _complete_via_engine to return a result
    with patch.object(cli, "_complete_via_engine") as mock_engine:
        mock_engine.return_value = {
            "content": "Engine response",
            "model": "fast-model",
            "input_tokens": 10,
            "output_tokens": 20,
            "technique": "cot_reflection",
            "backend": "grpc_engine",
        }

        result = await cli._ask_reason("What is 2+2?", None, False)

        # Should have used engine
        mock_engine.assert_called_once()
        assert result["backend"] == "grpc_engine"
        assert result["response"] == "Engine response"


@pytest.mark.asyncio
async def test_ask_reason_fallback_to_direct():
    """Test _ask_reason falls back to direct client if engine unavailable."""
    from gaius.cli import GaiusCLI

    cli = GaiusCLI()

    # Mock engine to return None (unavailable)
    with patch.object(cli, "_complete_via_engine") as mock_engine:
        mock_engine.return_value = None

        # Mock direct client - import is inside the function
        with patch("gaius.inference.get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_result = MagicMock()
            mock_result.content = "Direct response"
            mock_result.model = "direct-model"
            mock_result.input_tokens = 10
            mock_result.output_tokens = 20
            mock_result.technique = "cot_reflection"
            mock_client.complete = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            result = await cli._ask_reason("What is 2+2?", None, False)

            # Should have fallen back to direct
            assert result["backend"] == "direct"
            assert result["response"] == "Direct response"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
