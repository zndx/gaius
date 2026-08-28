"""Cognition channels ride signal_tier0 as DECIMAL series (cog.<channel>).

Before cognition was persisted the strip advertised eight channels it could
never fill. Now every advertised channel is sourced from the warehouse; a gap
is a missing row, never a zero.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from gaius.engine.services.cognition_waterfall import tick_from_gpu_rows
from gaius.engine.services.warehouse_ingest import (
    cognition_rows,
    cognition_series,
    series_id_of,
)
from gaius.engine.services.waterfall_drivers import (
    ONSET_NAMES,
    Sample,
    cognition_channel_names,
)


class TestCognitionRows:
    def test_present_row_is_decimal(self):
        now = 1_700_000_000.0
        rows = cognition_rows(now, [Sample("ricci", 0.25, True)])
        assert len(rows) == 1
        eh, ts_ns, sid, src, gpu, inst, val_i, val_d = rows[0]
        assert sid == series_id_of("cog.ricci")
        assert val_i is None and val_d == Decimal("0.250000")

    def test_a_gap_is_an_absent_row_not_a_zero(self):
        rows = cognition_rows(1_700_000_000.0, [Sample("ricci", 9.9, False)])
        assert rows == []

    def test_channel_set_matches_the_strip(self):
        names = cognition_channel_names()
        assert names, "no cognition channels registered"
        assert {s.name for s in cognition_series()} == {f"cog.{n}" for n in names}
        assert not any(n.startswith(("gpu-", "util-")) for n in names), (
            "hardware channels belong to DCGM series, not cognition"
        )


def _span(step_s: float = 0.25, n: int = 40) -> list[int]:
    """Timestamps covering ~n*step seconds up to now, oldest first.

    The settling anchor holds back the newest ~2 s as still-forming, so a single
    ts_ns==now row is always dropped. Real fetches return a dense sweep; feed one
    so a row lands on the settled anchor slot (the strip's rightmost column).
    """
    now = time.time()
    return [int((now - k * step_s) * 1e9) for k in range(n)][::-1]


def _gpu_rows_over(tss: list[int]) -> list[dict]:
    rows: list[dict] = []
    for ts in tss:
        rows += [
            {"ts_ns": ts, "gpu": i, "series_id": series_id_of("dcgm.power_mw"), "val_i": 200_000}
            for i in range(4)
        ] + [
            {"ts_ns": ts, "gpu": i, "series_id": series_id_of("dcgm.gpu_util_pct"), "val_i": 90}
            for i in range(4)
        ]
    return rows


class TestStripFromWarehouse:
    def test_cognition_rows_fill_their_channels(self):
        tss = _span()
        cog: list[dict] = []
        for ts in tss:
            cog += [
                {"ts_ns": ts, "channel": "ricci", "val_d": Decimal("0.25")},
                {"ts_ns": ts, "channel": "clt", "val_d": Decimal("0.75")},
            ]
        state = tick_from_gpu_rows(_gpu_rows_over(tss), 60, cog)
        idx = {n: i for i, n in enumerate(state.channel_names)}
        # Rightmost column is the settled anchor slot; the sweep covers it.
        assert state.matrix[idx["ricci"]][-1] == pytest.approx(0.25)
        assert state.matrix[idx["clt"]][-1] == pytest.approx(0.75)
        # util is packed into the bivariate gpu-N cell, not a separate channel.
        assert state.matrix[idx["gpu-0"]][-1] != 0.0

    def test_missing_cognition_row_leaves_zero(self):
        tss = _span()
        state = tick_from_gpu_rows(_gpu_rows_over(tss), 60, [])
        idx = {n: i for i, n in enumerate(state.channel_names)}
        assert state.matrix[idx["ricci"]][-1] == 0.0

    def test_tremor_comes_from_warehouse_onset_channels(self):
        tss = _span()
        onset = sorted(ONSET_NAMES & set(cognition_channel_names()))[0]
        cog = [{"ts_ns": ts, "channel": onset, "val_d": Decimal("-0.6")} for ts in tss]
        state = tick_from_gpu_rows(_gpu_rows_over(tss), 60, cog)
        assert state.salience == pytest.approx(0.6)

    def test_non_onset_channel_does_not_raise_tremor(self):
        tss = _span()
        quiet = [n for n in cognition_channel_names() if n not in ONSET_NAMES][0]
        cog = [{"ts_ns": ts, "channel": quiet, "val_d": Decimal("0.9")} for ts in tss]
        state = tick_from_gpu_rows(_gpu_rows_over(tss), 60, cog)
        assert state.salience == 0.0

    def test_hot_window_renders_sub_second(self):
        """The 60 s hot window renders at the ~4 Hz ingest cadence, not 1 Hz, so
        the sub-second GPU motion Kudu records survives to the strip. A 1 Hz strip
        collapsed ~4 samples into one column (60 flat plateaus); 4 Hz keeps them."""
        now = time.time()
        sid_p = series_id_of("dcgm.power_mw")
        sid_u = series_id_of("dcgm.gpu_util_pct")
        rows: list[dict] = []
        # 4 Hz sweep across the whole window, util stepping every 250 ms so
        # adjacent sub-second columns differ.
        for k in range(60 * 4 + 20):
            ts = int((now - k * 0.25) * 1e9)
            rows += [
                {"ts_ns": ts, "gpu": 0, "series_id": sid_p, "val_i": 120_000},
                {"ts_ns": ts, "gpu": 0, "series_id": sid_u, "val_i": 10 + (k % 80)},
            ]
        state = tick_from_gpu_rows(rows, 60, [])
        assert state.hz == 4
        assert len(state.matrix[0]) == 240  # 60 s * 4 Hz, not 60
        gi = state.channel_names.index("gpu-0")
        distinct = {round(v, 4) for v in state.matrix[gi] if v != 0.0}
        # >60 distinct values is impossible from a 1 Hz (60-column) bucket.
        assert len(distinct) > 60
