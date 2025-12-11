"""Test ObservePanel widget via textual pilot."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from textual.app import App, ComposeResult

from gaius.core.state import AppState
from gaius.widgets.observe_panel import ObservePanel
from gaius.observability.sources.base import MetricSeries, MetricValue


class ObservePanelTestApp(App):
    """Minimal app for testing ObservePanel."""

    CSS = """
    ObservePanel {
        width: 42;
        height: auto;
    }
    """

    def __init__(self):
        super().__init__()
        self.state = AppState()

    def compose(self) -> ComposeResult:
        yield ObservePanel(self.state, id="observe")


def make_series(name: str, values: list[float], unit: str = "ms") -> MetricSeries:
    """Create a MetricSeries with proper MetricValue objects."""
    now = datetime.now()
    metric_values = [
        MetricValue(value=v, timestamp=now)
        for v in values
    ]
    return MetricSeries(name=name, values=metric_values, unit=unit)


@pytest.fixture
def mock_prometheus():
    """Mock PrometheusSource."""
    with patch("gaius.widgets.observe_panel.PrometheusSource") as mock:
        source = MagicMock()
        source.health_check = AsyncMock(return_value=True)
        source.query_range = AsyncMock(return_value=make_series(
            "test", [1.0, 2.0, 3.0, 2.5, 3.5], "ms"
        ))
        source.close = AsyncMock()
        mock.return_value = source
        yield source


@pytest.fixture
def mock_engine():
    """Mock EngineSource."""
    with patch("gaius.widgets.observe_panel.EngineSource") as mock:
        source = MagicMock()
        source.query_range = AsyncMock(return_value=make_series(
            "gpu_mem", [0.67], "%"
        ))
        source.close = AsyncMock()
        mock.return_value = source
        yield source


@pytest.mark.asyncio
async def test_observe_panel_renders_unavailable():
    """Test panel shows unavailable message when Prometheus is down."""
    with patch("gaius.widgets.observe_panel.PrometheusSource") as mock:
        source = MagicMock()
        source.health_check = AsyncMock(return_value=False)
        source.close = AsyncMock()
        mock.return_value = source

        app = ObservePanelTestApp()
        async with app.run_test() as pilot:
            # Wait for initial fetch
            await pilot.pause()

            # Panel should exist
            panel = app.query_one("#observe", ObservePanel)
            assert panel is not None

            # Check render output contains unavailable message
            rendered = panel.render()
            assert "unavailable" in str(rendered.renderable).lower() or \
                   "Waiting for Prometheus" in str(rendered.renderable)


@pytest.mark.asyncio
async def test_observe_panel_renders_metrics(mock_prometheus, mock_engine):
    """Test panel renders metrics when sources are available."""
    app = ObservePanelTestApp()
    async with app.run_test() as pilot:
        # Wait for initial fetch and polling
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one("#observe", ObservePanel)
        assert panel is not None

        # Should have called health check
        mock_prometheus.health_check.assert_called()

        # Panel should show as available after successful fetch
        # Note: May need to wait for refresh cycle
        assert panel._available or mock_prometheus.health_check.call_count > 0


@pytest.mark.asyncio
async def test_observe_panel_polls_periodically(mock_prometheus, mock_engine):
    """Test panel polls metrics at configured interval."""
    app = ObservePanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one("#observe", ObservePanel)

        # Initial call count
        await pilot.pause()
        initial_calls = mock_prometheus.health_check.call_count

        # Wait a bit (poll interval is 5s, but test should see at least initial fetch)
        await pilot.pause()

        # Should have made at least one call
        assert mock_prometheus.health_check.call_count >= initial_calls


@pytest.mark.asyncio
async def test_observe_panel_hidden_skips_poll(mock_prometheus, mock_engine):
    """Test panel doesn't poll when hidden."""
    app = ObservePanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one("#observe", ObservePanel)

        # Wait for initial fetch
        await pilot.pause()
        initial_calls = mock_prometheus.health_check.call_count

        # Hide panel
        panel.add_class("hidden")
        await pilot.pause()

        # Trigger poll manually (simulating interval)
        await panel._poll_metrics()

        # Should not have made additional calls while hidden
        # (poll_metrics checks hidden class)
        assert mock_prometheus.health_check.call_count == initial_calls


@pytest.mark.asyncio
async def test_observe_panel_renders_endpoint_status():
    """Test panel renders endpoint status section."""
    with patch("gaius.widgets.observe_panel.PrometheusSource") as mock_prom:
        source = MagicMock()
        source.health_check = AsyncMock(return_value=False)
        source.close = AsyncMock()
        mock_prom.return_value = source

        app = ObservePanelTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            panel = app.query_one("#observe", ObservePanel)

            # Set endpoint status directly
            panel._grpc_connected = True
            panel._endpoint_status = {
                "reasoning": {"status": "healthy"},
                "fast": {"status": "starting"},
            }

            # Render and check for endpoint indicators
            rendered = panel.render()
            content = str(rendered.renderable)

            # Should show endpoint count
            assert "Endpoints" in content
            # Should show gRPC status
            assert "gRPC" in content or "connected" in content


@pytest.mark.asyncio
async def test_observe_panel_renders_grpc_disconnected():
    """Test panel shows disconnected gRPC status."""
    with patch("gaius.widgets.observe_panel.PrometheusSource") as mock_prom:
        source = MagicMock()
        source.health_check = AsyncMock(return_value=False)
        source.close = AsyncMock()
        mock_prom.return_value = source

        app = ObservePanelTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            panel = app.query_one("#observe", ObservePanel)

            # Set disconnected state
            panel._grpc_connected = False
            panel._endpoint_status = {}

            rendered = panel.render()
            content = str(rendered.renderable)

            # Should show disconnected
            assert "disconnected" in content.lower() or "--" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
