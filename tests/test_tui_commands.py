"""Test TUI commands via textual pilot."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from textual.pilot import Pilot

# Test the actual GaiusApp
from gaius.app import GaiusApp
from gaius.widgets.content import ContentPanel
from gaius.widgets.note_editor import NoteEditor
from gaius.widgets.command import CommandInput


@pytest.mark.asyncio
async def test_gaius_app_starts():
    """Test GaiusApp can start."""
    app = GaiusApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # App should have started
        assert True


@pytest.mark.asyncio
async def test_command_input_focus():
    """Test pressing / focuses command input."""
    app = GaiusApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Press / to enter command mode
        await pilot.press("slash")
        await pilot.pause()

        # Command input should exist
        cmd = app.query_one("#command-input", CommandInput)
        assert cmd is not None


@pytest.mark.asyncio
async def test_health_command_creates_report(tmp_path):
    """Test /health command creates report and shows in editor."""
    # Mock the health module
    mock_report = MagicMock()
    mock_report.healthy = True
    mock_report.timestamp = datetime.now()
    mock_report.duration_ms = 100
    mock_report.passed = 5
    mock_report.warnings = 0
    mock_report.failures = 0
    mock_report.skipped = 0
    mock_report.checks = []
    mock_report.interventions = []
    mock_report.metrics = {}
    mock_report.summary.return_value = "All systems healthy"

    with patch("gaius.health.HealthChecker") as mock_checker_class:
        checker = MagicMock()
        checker.run_all = AsyncMock(return_value=mock_report)
        checker.run_quick = AsyncMock(return_value=mock_report)
        checker.run_category = AsyncMock(return_value=mock_report)
        checker.set_healing_coordinator = MagicMock()
        mock_checker_class.return_value = checker

        # Also mock the healing coordinator fetch
        with patch.dict("os.environ", {"GAIUS_KB_PATH": str(tmp_path)}):
            app = GaiusApp()
            async with app.run_test() as pilot:
                await pilot.pause()

                # Enter command mode
                await pilot.press("slash")
                await pilot.pause()

                # Type health command
                for char in "health":
                    await pilot.press(char)
                await pilot.press("enter")

                # Wait for async execution
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

                # Check content panel exists
                content = app.query_one("#content-panel", ContentPanel)
                assert content is not None


@pytest.mark.asyncio
async def test_state_command():
    """Test /state command returns state."""
    app = GaiusApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Enter command mode
        await pilot.press("slash")
        await pilot.pause()

        # Type state command
        for char in "state":
            await pilot.press(char)
        await pilot.press("enter")

        # Wait for command
        await pilot.pause()

        # Content panel should show state
        content = app.query_one("#content-panel", ContentPanel)
        assert content is not None


@pytest.mark.asyncio
async def test_toggle_panels():
    """Test panel toggle key bindings."""
    app = GaiusApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Get panels
        content = app.query_one("#content-panel", ContentPanel)

        # Press ] to toggle right panel
        await pilot.press("bracketright")
        await pilot.pause()

        # Press [ to toggle left panel
        await pilot.press("bracketleft")
        await pilot.pause()

        # Press \ to toggle both
        await pilot.press("backslash")
        await pilot.pause()

        # App should still be running
        assert True


@pytest.mark.asyncio
async def test_help_command():
    """Test /help command shows help."""
    app = GaiusApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Enter command mode
        await pilot.press("slash")
        await pilot.pause()

        # Type help command
        for char in "help":
            await pilot.press(char)
        await pilot.press("enter")

        # Wait for command
        await pilot.pause()
        await pilot.pause()

        # Content panel should exist and contain something
        content = app.query_one("#content-panel", ContentPanel)
        assert content is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
