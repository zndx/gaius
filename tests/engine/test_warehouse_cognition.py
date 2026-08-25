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


def _gpu_rows(ts_ns: int) -> list[dict]:
    return [
        {"ts_ns": ts_ns, "gpu": i, "series_id": series_id_of("dcgm.power_mw"), "val_i": 200_000}
        for i in range(4)
    ] + [
        {"ts_ns": ts_ns, "gpu": i, "series_id": series_id_of("dcgm.gpu_util_pct"), "val_i": 90}
        for i in range(4)
    ]


class TestStripFromWarehouse:
    def test_cognition_rows_fill_their_channels(self):
        ts_ns = int(time.time() * 1e9)
        state = tick_from_gpu_rows(
            _gpu_rows(ts_ns), 60,
            [
                {"ts_ns": ts_ns, "channel": "ricci", "val_d": Decimal("0.25")},
                {"ts_ns": ts_ns, "channel": "clt", "val_d": Decimal("0.75")},
            ],
        )
        idx = {n: i for i, n in enumerate(state.channel_names)}
        assert state.matrix[idx["ricci"]][-1] == pytest.approx(0.25)
        assert state.matrix[idx["clt"]][-1] == pytest.approx(0.75)
        assert state.matrix[idx["gpu-0"]][-1] != 0.0
        assert state.matrix[idx["util-3"]][-1] == pytest.approx(0.9)

    def test_missing_cognition_row_leaves_zero(self):
        ts_ns = int(time.time() * 1e9)
        state = tick_from_gpu_rows(_gpu_rows(ts_ns), 60, [])
        idx = {n: i for i, n in enumerate(state.channel_names)}
        assert state.matrix[idx["ricci"]][-1] == 0.0

    def test_tremor_comes_from_warehouse_onset_channels(self):
        ts_ns = int(time.time() * 1e9)
        onset = sorted(ONSET_NAMES & set(cognition_channel_names()))[0]
        state = tick_from_gpu_rows(
            _gpu_rows(ts_ns), 60, [{"ts_ns": ts_ns, "channel": onset, "val_d": Decimal("-0.6")}]
        )
        assert state.salience == pytest.approx(0.6)

    def test_non_onset_channel_does_not_raise_tremor(self):
        ts_ns = int(time.time() * 1e9)
        quiet = [n for n in cognition_channel_names() if n not in ONSET_NAMES][0]
        state = tick_from_gpu_rows(
            _gpu_rows(ts_ns), 60, [{"ts_ns": ts_ns, "channel": quiet, "val_d": Decimal("0.9")}]
        )
        assert state.salience == 0.0
