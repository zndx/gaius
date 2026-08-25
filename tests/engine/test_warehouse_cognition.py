"""Everything the waterfall shows comes from Kudu ∪ Iceberg.

Before cognition was persisted, the warehouse path filled only gpu-N/util-N
while still advertising eight cognition channels it could never fill. They sat
at zero forever — the strip looked unwired because it was.
"""

from __future__ import annotations

import time

import pytest

from gaius.engine.services.cognition_waterfall import tick_from_gpu_rows
from gaius.engine.services.warehouse_ingest import (
    _DCGM_EXTRA,
    cognition_tuples,
    dcgm_tuples,
)
from gaius.engine.services.waterfall_drivers import (
    ONSET_NAMES,
    Sample,
    cognition_channel_names,
)


def _now() -> tuple[float, int, int]:
    now = time.time()
    return now, int(now * 1_000_000_000), int(now) // 3600


class TestDcgmTuples:
    def test_emits_one_row_per_field_present(self):
        now, _, hour = _now()
        gpus = [
            {
                "gpu_index": 0,
                "power_w": 100.0,
                "sm_clock_mhz": 2100.0,
                "energy_mj": 5.0,
                "mem_temp_c": 40.0,
                "xid_errors": 0.0,
            }
        ]
        rows = dcgm_tuples(now, gpus)
        assert {r[3] for r in rows} == set(_DCGM_EXTRA.values())
        assert all(r[0] == hour and r[2] == 0 for r in rows)

    def test_absent_field_is_an_absent_row_not_a_zero(self):
        """A narrow table represents 'not reported' by having no row."""
        now, _, _ = _now()
        rows = dcgm_tuples(now, [{"gpu_index": 3, "sm_clock_mhz": 1500.0}])
        assert [r[3] for r in rows] == ["sm_clock_mhz"]
        assert rows[0][4] == 1500.0

    def test_core_only_gpu_yields_no_dcgm_rows(self):
        now, _, _ = _now()
        assert dcgm_tuples(now, [{"gpu_index": 1, "power_w": 10.0}]) == []


class TestCognitionTuples:
    def test_present_flag_survives(self):
        now, _, hour = _now()
        rows = cognition_tuples(
            now, [Sample("ricci", 0.5, True), Sample("clt", 0.0, False)]
        )
        assert [(r[2], r[3], r[4]) for r in rows] == [
            ("ricci", 0.5, True),
            ("clt", 0.0, False),
        ]
        assert all(r[0] == hour for r in rows)

    def test_channel_set_matches_the_strip(self):
        """Whatever the drivers advertise is what the warehouse must carry."""
        names = cognition_channel_names()
        assert "ricci" in names and "clt" in names
        assert not any(n.startswith("gpu-") or n.startswith("util-") for n in names), (
            "hardware channels belong in gpu_metrics, not cognition_metrics"
        )


class TestWarehouseStrip:
    def _gpu_rows(self, ts_ns: int) -> list[dict]:
        return [
            {"ts_ns": ts_ns, "gpu_index": i, "power_w": 200.0, "util_pct": 90.0}
            for i in range(6)
        ]

    def test_cognition_rows_fill_their_channels(self):
        _, ts_ns, _ = _now()
        state = tick_from_gpu_rows(
            self._gpu_rows(ts_ns),
            60,
            [
                {"ts_ns": ts_ns, "channel": "ricci", "value": 0.25, "present": True},
                {"ts_ns": ts_ns, "channel": "clt", "value": 0.75, "present": True},
            ],
        )
        assert state.driver == "warehouse"
        idx = {n: i for i, n in enumerate(state.channel_names)}
        assert max(state.matrix[idx["ricci"]]) == pytest.approx(0.25)
        assert max(state.matrix[idx["clt"]]) == pytest.approx(0.75)

    def test_a_gap_is_not_painted_as_zero(self):
        """present=False must leave the cell untouched, not assert 0.0."""
        _, ts_ns, _ = _now()
        state = tick_from_gpu_rows(
            self._gpu_rows(ts_ns),
            60,
            [{"ts_ns": ts_ns, "channel": "ricci", "value": 9.9, "present": False}],
        )
        idx = {n: i for i, n in enumerate(state.channel_names)}
        assert max(state.matrix[idx["ricci"]]) == 0.0

    def test_tremor_comes_from_warehouse_onset_channels(self):
        _, ts_ns, _ = _now()
        onset = sorted(ONSET_NAMES)[0]
        state = tick_from_gpu_rows(
            self._gpu_rows(ts_ns),
            60,
            [{"ts_ns": ts_ns, "channel": onset, "value": -0.6, "present": True}],
        )
        assert state.salience == pytest.approx(0.6), "envelope is the absolute peak"

    def test_non_onset_channel_does_not_raise_tremor(self):
        _, ts_ns, _ = _now()
        non_onset = next(
            n for n in cognition_channel_names() if n not in ONSET_NAMES
        )
        state = tick_from_gpu_rows(
            self._gpu_rows(ts_ns),
            60,
            [{"ts_ns": ts_ns, "channel": non_onset, "value": 0.9, "present": True}],
        )
        assert state.salience == 0.0

    def test_unknown_channel_is_ignored(self):
        """Probe rows and retired channels must not break the strip."""
        _, ts_ns, _ = _now()
        state = tick_from_gpu_rows(
            self._gpu_rows(ts_ns),
            60,
            [{"ts_ns": ts_ns, "channel": "probe", "value": 0.42, "present": True}],
        )
        assert "probe" not in state.channel_names

    def test_gpu_strip_renders_without_any_cognition(self):
        """A quiet cognition surface must not blank the GPU strip."""
        _, ts_ns, _ = _now()
        state = tick_from_gpu_rows(self._gpu_rows(ts_ns), 60, [])
        idx = {n: i for i, n in enumerate(state.channel_names)}
        assert max(state.matrix[idx["gpu-0"]]) > 0.0
        assert state.salience == 0.0
