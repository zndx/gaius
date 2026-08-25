"""Warehouse ingest: DCGM → signal_tier0 rows under the typing rule.

INT in → INT out at native precision; float in → DECIMAL; never float(val)
widening. Power is NVML milliwatts, stored INT32.
"""

from decimal import Decimal

import pytest

from gaius.engine.services import warehouse_ingest as wi


def test_series_ids_are_stable_and_distinct() -> None:
    ids = {s.series_id for s in wi.all_series()}
    assert len(ids) == len(wi.all_series())
    assert wi.series_id_of("dcgm.power_mw") == wi.series_id_of("dcgm.power_mw")
    assert all(0 < i < 2**63 for i in ids)


def test_dcgm_families_are_integers_except_power_which_is_mw() -> None:
    by = {s.name: s for s in wi.DCGM_SERIES}
    assert len(by) == 17
    assert all(s.vtype == wi.VT_INT for s in wi.DCGM_SERIES)
    assert by["dcgm.power_mw"].unit == "mW"
    assert by["dcgm.energy_mj"].unit == "mJ"


def test_integer_parser_refuses_to_round() -> None:
    assert wi._as_int("37", "x") == 37
    assert wi._as_int("37.0", "x") == 37  # Prometheus text renders ints as floats
    assert wi._as_int("12345678901234", "x") == 12345678901234
    with pytest.raises(RuntimeError, match="declared INT"):
        wi._as_int("37.5", "x")


def test_decimal_parser_is_exact_and_finite() -> None:
    assert wi._as_dec("109.123", "x") == Decimal("109.123000")
    assert wi._as_dec("0.1", "x") + wi._as_dec("0.2", "x") == Decimal("0.3")
    with pytest.raises(RuntimeError, match="no DECIMAL representation"):
        wi._as_dec("NaN", "x")


def test_dcgm_rows_are_narrow_and_typed() -> None:
    now = 1_700_000_000.0
    gpus = {0: {"dcgm.power_mw": 109_123, "dcgm.gpu_util_pct": 37, "dcgm.fb_used_mib": 21334,
                "dcgm.gpu_temp_c": 51}}
    rows = wi.dcgm_rows(now, gpus)
    assert len(rows) == 4
    eh, ts_ns, sid, src, gpu, inst, val_i, val_d = rows[0]
    assert eh == int(now) // 3600 and ts_ns == int(now * 1e9)
    assert src == wi.SRC_DCGM and gpu == 0 and inst is None
    assert isinstance(val_i, int) and val_d is None
    assert {r[2] for r in rows} == {wi.series_id_of(n) for n in gpus[0]}


def test_sample_gpus_live() -> None:
    """Live DCGM :9400; every GPU carries the four core series as ints."""
    try:
        gpus = wi.sample_gpus()
    except RuntimeError as e:
        pytest.skip(f"DCGM not reachable in this environment: {e}")
    assert gpus
    for gi, rec in gpus.items():
        for k in wi._DCGM_CORE:
            assert isinstance(rec[k], int), (gi, k, rec[k])
        assert rec["dcgm.power_mw"] >= 0
