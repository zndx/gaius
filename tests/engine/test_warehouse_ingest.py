"""Live nvidia-smi parse for engine warehouse ingest (no static GPUs)."""

from gaius.engine.services.warehouse_ingest import sample_gpus, _tuples


def test_sample_gpus_live() -> None:
    rows = sample_gpus()
    assert rows, "nvidia-smi returned no GPUs"
    for r in rows:
        assert "gpu_index" in r
        assert r["power_w"] >= 0
        assert 0 <= r["util_pct"] <= 100


def test_insert_tuples_shape() -> None:
    rows = sample_gpus()
    tups = _tuples(1_700_000_000.0, rows)
    assert len(tups) == len(rows)
    eh, ts_ns, idx, pw, ut, mem, temp = tups[0]
    assert eh == 1_700_000_000 // 3600
    assert ts_ns == 1_700_000_000 * 1_000_000_000
    assert idx == rows[0]["gpu_index"]
    assert pw == rows[0]["power_w"]
    assert ut == rows[0]["util_pct"]
    assert mem == rows[0]["mem_used_mb"]
    assert temp == rows[0]["temp_c"]
