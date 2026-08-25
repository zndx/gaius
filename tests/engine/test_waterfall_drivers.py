from gaius.engine.services.waterfall_drivers import (
    HardwareDriver,
    RicciDriver,
    Sample,
    VllmDriver,
    all_channel_names,
    kumo_minutes,
    onset_envelope,
    parse_prom_text,
    register,
    reset_for_tests,
    sample_column,
    _as_transient,
)

import pytest


DCGM = """
# HELP DCGM_FI_DEV_POWER_USAGE Power
DCGM_FI_DEV_POWER_USAGE{gpu="0",modelName="NVIDIA GeForce RTX 4090"} 120.0
DCGM_FI_DEV_POWER_USAGE{gpu="1",modelName="NVIDIA GeForce RTX 4090"} 110.0
DCGM_FI_DEV_POWER_USAGE{gpu="2",modelName="NVIDIA GeForce RTX 4090"} 115.0
DCGM_FI_DEV_POWER_USAGE{gpu="3",modelName="NVIDIA GeForce RTX 4090"} 118.0
DCGM_FI_DEV_POWER_USAGE{gpu="4",modelName="NVIDIA GeForce RTX 4090"} 20.8
DCGM_FI_DEV_POWER_USAGE{gpu="5",modelName="NVIDIA GeForce RTX 4090"} 14.4
DCGM_FI_DEV_GPU_UTIL{gpu="0"} 100
DCGM_FI_DEV_GPU_UTIL{gpu="1"} 80
DCGM_FI_DEV_GPU_UTIL{gpu="2"} 90
DCGM_FI_DEV_GPU_UTIL{gpu="3"} 70
DCGM_FI_DEV_GPU_UTIL{gpu="4"} 0
DCGM_FI_DEV_GPU_UTIL{gpu="5"} 0
"""

VLLM = """
vllm:kv_cache_usage_perc{engine="0",model_name="Qwen/Qwen3.8-27B"} 0.42
vllm:num_requests_running{engine="0",model_name="Qwen/Qwen3.8-27B"} 1.0
vllm:generation_tokens_total{engine="0",model_name="Qwen/Qwen3.8-27B"} 1000.0
vllm:prompt_tokens_total{engine="0",model_name="Qwen/Qwen3.8-27B"} 500.0
"""


@pytest.fixture(autouse=True)
def _iso_drivers() -> None:
    reset_for_tests()
    yield
    reset_for_tests()


def test_parse_prom_text() -> None:
    rows = parse_prom_text(DCGM)
    assert any(n == "DCGM_FI_DEV_POWER_USAGE" and lab["gpu"] == "0" for n, lab, _ in rows)


def test_parse_unlabeled() -> None:
    rows = parse_prom_text("vllm:num_requests_running 2.0\n")
    assert rows[0][0] == "vllm:num_requests_running"
    assert rows[0][2] == 2.0


def test_hardware_tinybox_gpus(monkeypatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.services.waterfall_drivers._http_get", lambda url, timeout=0.15: DCGM
    )
    samples = HardwareDriver().sample({})
    by = {s.name: s for s in samples}
    from gaius.engine.services.waterfall_color import unpack_gpu

    assert by["gpu-0"].present and by["gpu-0"].value > 1.5
    p0, u0, on0 = unpack_gpu(by["gpu-0"].value)
    assert on0 and u0 == 1.0 and p0 > 0.2
    assert by["util-0"].value == 1.0
    assert by["util-3"].value == 0.7
    _p4, u4, on4 = unpack_gpu(by["gpu-4"].value)
    assert on4 and abs(u4) < 0.01
    assert by["util-5"].value == 0.0
    assert by["gpu-5"].present


def test_hardware_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.services.waterfall_drivers._http_get", lambda url, timeout=0.15: None
    )
    samples = HardwareDriver().sample({})
    assert all(not s.present and s.value == 0.0 for s in samples)


def test_vllm_running(monkeypatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.services.waterfall_drivers._http_get", lambda url, timeout=0.15: VLLM
    )
    d = VllmDriver()
    first = {s.name: s for s in d.sample({})}
    assert first["run"].value == 1.0
    assert first["kv"].value == 0.42


def test_clt_absent_sae_always_absent() -> None:
    col = sample_column({"tape_n": 0, "tape_peak": 0.0, "clt_loaded": False})
    by = {s.name: s for s in col}
    assert by["clt"].present is False
    assert by["sae"].present is False
    assert by["sae"].value == 0.0


def test_clt_heartbeat_when_loaded() -> None:
    col = sample_column({"tape_n": 0, "tape_peak": 0.0, "clt_loaded": True})
    by = {s.name: s for s in col}
    assert by["clt"].present is True
    assert 0.0 < by["clt"].value < 0.2


def test_channel_names_stable() -> None:
    names = all_channel_names()
    assert names[:6] == ("gpu-0", "gpu-1", "gpu-2", "gpu-3", "gpu-4", "gpu-5")
    assert names[6:12] == ("util-0", "util-1", "util-2", "util-3", "util-4", "util-5")
    assert "clt" in names and "ricci" in names and "sae" in names
    assert "z0" not in names
    assert len(names) == 20


def test_ricci_onset_from_embedding_delta(monkeypatch) -> None:
    means = iter([0.10, 0.25])
    monkeypatch.setattr(
        "gaius.engine.services.waterfall_drivers.ollivier_mean",
        lambda vecs: next(means),
    )
    d = RicciDriver()
    vec_a = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 1.0, 0.0]]
    first = {s.name: s for s in d.sample({"embeddings": vec_a})}
    assert first["ricci"].present
    assert first["ricci-d"].value == 0.0
    d._at = 0.0
    vec_b = [[0.9, 0.1, 0.0], [0.1, 0.9, 0.0], [0.0, 0.1, 0.9], [0.8, 0.8, 0.1]]
    second = {s.name: s for s in d.sample({"embeddings": vec_b})}
    assert second["ricci-d"].value > 0.5


def test_onset_envelope_ignores_gpu_util() -> None:
    env = onset_envelope(
        [
            Sample("util-0", 1.0, True),
            Sample("pwr-0", 0.9, True),
            Sample("ricci-d", 0.4, True),
            Sample("clt", 0.0, False),
        ]
    )
    assert env == pytest.approx(0.4)


def test_ac_step_flashes_then_dim_occupancy() -> None:
    first = _as_transient("util-0", 0.0, True)
    assert abs(first) < 0.05
    onset = _as_transient("util-0", 1.0, True)
    assert onset > 0.8
    held = onset
    for _ in range(80):
        held = _as_transient("util-0", 1.0, True)
    assert 0.05 < held < 0.35
    assert _as_transient("util-0", 0.0, False) == 0.0


def test_hardware_records_kumo_minutes(monkeypatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.services.waterfall_drivers._http_get",
        lambda url, timeout=0.15: DCGM,
    )
    HardwareDriver().sample({})
    live = kumo_minutes()
    assert live
    watts, util, _sal = next(iter(live.values()))
    assert watts > 400
    assert util > 50


def test_register_appends_channels() -> None:
    class Extra:
        name = "lmas"
        cadence_s = 0.1

        def channel_names(self) -> tuple[str, ...]:
            return ("lmas",)

        def sample(self, ctx):
            return [Sample("lmas", 0.0, present=False)]

    from gaius.engine.services import waterfall_drivers as wd

    before = list(wd.DRIVERS)
    try:
        register(Extra())
        names = all_channel_names()
        assert names[-1] == "lmas"
        col = sample_column({})
        assert any(s.name == "lmas" and not s.present for s in col)
    finally:
        wd.DRIVERS = before
