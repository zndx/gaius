"""Test Observe Panel functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

pytest_plugins = ("pytest_asyncio",)


@pytest.mark.asyncio
async def test_prometheus_health_check():
    """Test that PrometheusSource health check works."""
    from gaius.observability.sources.prometheus import PrometheusSource

    source = PrometheusSource(base_url="http://localhost:9090")

    # Test health check
    is_healthy = await source.health_check()
    print(f"Prometheus health check: {is_healthy}")

    await source.close()

    # This test passes if Prometheus is running, logs otherwise
    if not is_healthy:
        print("WARNING: Prometheus not running at localhost:9090")


@pytest.mark.asyncio
async def test_prometheus_query():
    """Test Prometheus query_range for metrics."""
    from gaius.observability.sources.prometheus import PrometheusSource

    source = PrometheusSource(base_url="http://localhost:9090")

    # Test a simple query
    series = await source.query_range(
        "up",  # Simple metric that should exist
        duration_seconds=60,
        step_seconds=15,
    )

    print(f"Query 'up' returned: {len(series.values)} values")
    print(f"  current={series.current}, sparkline_data={series.sparkline_data}")

    await source.close()


@pytest.mark.asyncio
async def test_observe_panel_renders():
    """Test that ObservePanel renders without crashing."""
    from gaius.core.state import AppState
    from gaius.widgets.observe_panel import ObservePanel

    state = AppState()
    panel = ObservePanel(state, id="test-observe")

    # Test render method
    try:
        rendered = panel.render()
        print(f"Panel rendered successfully: {type(rendered)}")
        print(f"Panel content: {rendered}")
    except Exception as e:
        pytest.fail(f"Panel render failed: {e}")


@pytest.mark.asyncio
async def test_observe_panel_metrics_fetch():
    """Test ObservePanel metric fetching."""
    from gaius.core.state import AppState
    from gaius.widgets.observe_panel import ObservePanel

    state = AppState()
    panel = ObservePanel(state, id="test-observe")

    # Call internal refresh
    await panel._refresh_metrics()

    print(f"Panel available: {panel._available}")
    print(f"Metric data keys: {list(panel._metric_data.keys())}")
    print(f"Endpoint status: {panel._endpoint_status}")
    print(f"gRPC connected: {panel._grpc_connected}")

    # Render after fetch
    rendered = panel.render()
    print(f"Panel after fetch: {rendered}")


@pytest.mark.asyncio
async def test_engine_source():
    """Test EngineSource metric fetching."""
    from gaius.observability.sources.engine import EngineSource

    source = EngineSource()

    # Test health check
    healthy = await source.health_check()
    print(f"Engine source healthy: {healthy}")

    if healthy:
        # Try getting GPU memory
        value = await source.query_instant("gpu_memory:0")
        print(f"GPU 0 memory: {value}")

        # Try getting endpoint count
        value = await source.query_instant("endpoint_count")
        print(f"Endpoint count: {value}")

    await source.close()


@pytest.mark.asyncio
async def test_metrics_definitions():
    """Test that OBSERVE_METRICS are properly defined."""
    from gaius.observability.metrics import OBSERVE_METRICS

    print(f"Defined metrics: {len(OBSERVE_METRICS)}")
    for m in OBSERVE_METRICS:
        print(f"  - {m.id}: {m.name} ({m.source}) query='{m.query}'")


@pytest.mark.skip(reason="TUI pilot test times out with full app startup; use test_observe_panel_metrics_fetch instead")
@pytest.mark.asyncio
async def test_tui_observe_panel_via_pilot():
    """Test ObservePanel via TUI using textual pilot.

    Cycles through panel modes using 'g' key until reaching OBSERVE,
    then verifies the panel content.

    NOTE: This test times out due to the full app startup. Use
    test_observe_panel_metrics_fetch for faster verification.
    """
    from gaius.app import GaiusApp
    from gaius.core.state import CenterPanelMode
    from gaius.widgets.observe_panel import ObservePanel

    app = GaiusApp()
    async with app.run_test() as pilot:
        # Wait for app to initialize
        await pilot.pause()
        await pilot.pause()

        # Initial mode should be INIT
        initial_mode = app.state.center_panel_mode
        print(f"Initial center panel mode: {initial_mode}")

        # Press 'g' repeatedly to cycle through modes until we hit OBSERVE
        # Order: INIT → GRAPH → THINK → EVOLUTION → OBSERVE → NONE → INIT
        max_presses = 10
        found_observe = False

        for i in range(max_presses):
            mode_before = app.state.center_panel_mode
            await pilot.press("g")
            await pilot.pause()
            mode_after = app.state.center_panel_mode

            print(f"Press {i+1}: {mode_before} → {mode_after}")

            if mode_after == CenterPanelMode.OBSERVE:
                found_observe = True
                print("Found OBSERVE mode!")
                break

        assert found_observe, f"Never reached OBSERVE mode after {max_presses} presses"

        # Wait for panel to render
        await pilot.pause()
        await pilot.pause()

        # Try to find the ObservePanel widget
        try:
            observe_panel = app.query_one("#observe-panel", ObservePanel)
            print(f"Found ObservePanel widget: {observe_panel}")

            # Check initial panel state (before refresh)
            print(f"  [Before refresh]")
            print(f"    Panel available: {observe_panel._available}")
            print(f"    Metric data keys: {list(observe_panel._metric_data.keys())}")
            print(f"    Endpoint status: {observe_panel._endpoint_status}")
            print(f"    gRPC connected: {observe_panel._grpc_connected}")

            # Manually trigger a metrics refresh
            print(f"  [Triggering _refresh_metrics()]")
            await observe_panel._refresh_metrics()

            # Check panel state after refresh
            print(f"  [After refresh]")
            print(f"    Panel available: {observe_panel._available}")
            print(f"    Metric data keys: {list(observe_panel._metric_data.keys())}")
            print(f"    Endpoint status: {observe_panel._endpoint_status}")
            print(f"    gRPC connected: {observe_panel._grpc_connected}")

            # Show any metric values we got
            if observe_panel._metric_data:
                print(f"  [Metric values]")
                for key, data in observe_panel._metric_data.items():
                    print(f"    {key}: current={data.current}, sparkline={data.sparkline_data[:3]}...")

            # Render and check output
            rendered = observe_panel.render()
            print(f"  Rendered type: {type(rendered)}")

        except Exception as e:
            print(f"Could not find ObservePanel: {e}")
            import traceback
            traceback.print_exc()
            # List all widgets
            for widget in app.query("*"):
                print(f"  Widget: {widget.__class__.__name__} id={getattr(widget, 'id', None)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
