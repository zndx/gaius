"""Signals DCGM OTLP parse — skip PROF/DCP, fold per GPU."""

from __future__ import annotations

from gaius.engine.services.signals_telemetry import parse_otlp_snapshot


def _pt(idx: str, value: float) -> dict:
    return {
        "asDouble": value,
        "attributes": [
            {"key": "gpu.index", "value": {"stringValue": idx}},
            {"key": "gpu.uuid", "value": {"stringValue": f"GPU-{idx}"}},
            {"key": "gpu.modelname", "value": {"stringValue": "NVIDIA GeForce RTX 4090"}},
        ],
    }


def _metric(name: str, points: list[dict], kind: str = "gauge") -> dict:
    return {"name": name, "unit": "W", kind: {"dataPoints": points}}


def test_parse_folds_power_and_skips_prof() -> None:
    payload = {
        "resourceMetrics": [
            {
                "scopeMetrics": [
                    {
                        "metrics": [
                            _metric(
                                "gpu.power.draw",
                                [_pt("0", 109.0), _pt("4", 23.0)],
                            ),
                            _metric(
                                "gpu.memory.used",
                                [_pt("0", 21163.0), _pt("4", 3.0)],
                                kind="gauge",
                            ),
                            _metric(
                                "DCGM_FI_PROF_GR_ENGINE_ACTIVE",
                                [_pt("0", 99.0)],
                            ),
                            _metric(
                                "gpu.utilization",
                                [_pt("0", 100.0), _pt("4", 0.0)],
                            ),
                        ]
                    }
                ]
            }
        ]
    }
    snap = parse_otlp_snapshot(payload)
    assert snap["total_w"] == 132.0
    assert snap["parked_w"] == 23.0
    assert snap["inferring_w"] == 109.0
    assert len(snap["gpus"]) == 2
    assert snap["gpus"][0]["power_w"] == 109.0
    assert "prof" not in str(snap).lower()


def test_empty_payload_is_honest() -> None:
    snap = parse_otlp_snapshot({})
    assert snap["gpus"] == []
    assert snap["total_w"] == 0.0
