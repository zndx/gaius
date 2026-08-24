"""10 Hz strip from real drivers; newest on the right."""

from gaius.engine.services.cognition_waterfall import (
    CHANNEL_NAMES,
    N_CHANNELS,
    holoviews_image,
    reset_for_tests,
    tick,
)
import pytest


def test_channel_names_are_measures() -> None:
    assert "gpu-0" in CHANNEL_NAMES
    assert "gpu-5" in CHANNEL_NAMES
    assert "pwr-0" not in CHANNEL_NAMES
    assert "ricci-d" in CHANNEL_NAMES
    assert "z0" not in CHANNEL_NAMES
    assert "delta" not in CHANNEL_NAMES
    assert len(CHANNEL_NAMES) == N_CHANNELS == 20


def test_tick_seeds_and_scrolls() -> None:
    reset_for_tests()
    a = tick(8, hz=1, ctx={"tape_n": 0})
    assert len(a.matrix) == N_CHANNELS
    assert len(a.matrix[0]) == 8
    assert a.driver == "measures"
    import time

    time.sleep(0.002)
    b = tick(8, hz=1, ctx={"tape_n": 0})
    assert len(b.matrix[0]) == 8


def test_ingest_skipped_in_tests() -> None:
    reset_for_tests()
    from gaius.engine.services.cognition_waterfall import ingest_fast_column, tick

    tick(8, hz=1, ctx={"tape_n": 0})
    ingest_fast_column()  # must not resize/clear the test ring
    b = tick(8, hz=1, ctx={"tape_n": 0})
    assert len(b.matrix[0]) == 8


def test_tick_high_res_columns() -> None:
    reset_for_tests()
    a = tick(6, hz=10)
    assert len(a.matrix[0]) == 60
    assert a.hz == 10


def test_bad_window_fail_fast() -> None:
    with pytest.raises(ValueError, match="COG.00000030"):
        tick(0)


def test_long_window_requires_warehouse() -> None:
    reset_for_tests()
    with pytest.raises(ValueError, match="COG.00000031"):
        tick(120)


def test_warehouse_null_ts_fail_fast() -> None:
    reset_for_tests()
    rows = [{"ts_ns": None, "gpu_index": 0, "power_w": 80.0, "util_pct": 10.0}]
    with pytest.raises(ValueError, match="COG.00000031"):
        tick(120, warehouse_rows=rows)


def test_warehouse_rows_fill_gpu_channels() -> None:
    reset_for_tests()
    import time

    now_ns = int(time.time() * 1_000_000_000)
    rows = [
        {
            "ts_ns": now_ns,
            "gpu_index": 0,
            "power_w": 80.0,
            "util_pct": 10.0,
        }
    ]
    state = tick(120, warehouse_rows=rows)
    assert state.driver == "warehouse"
    assert state.hz == 1
    assert len(state.matrix[0]) == 120
    assert "gpu-0" in state.channel_names
    gi = state.channel_names.index("gpu-0")
    assert any(v != 0.0 for v in state.matrix[gi])


def test_holoviews_image_optional() -> None:
    reset_for_tests()
    state = tick(8, hz=1)
    try:
        img = holoviews_image(state)
    except ImportError:
        pytest.skip("holoviews not installed")
    assert img.kdims[0].name == "epoch_s"
    assert [d.name for d in img.vdims] == ["R", "G", "B"]
