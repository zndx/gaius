"""YK Application stamps: resource class, no root.gaius, GPU token only."""

from __future__ import annotations

import pytest
import yaml

from gaius.engine.sentinel_claim import (
    COMPUTE,
    EXTRACT,
    GURU_NOAPP,
    RATE_METERED,
    application_yaml,
    gpu_start_allowed,
    resource_class_for,
)


def test_article_and_prospects_map_to_extract() -> None:
    assert resource_class_for("article-curate") == EXTRACT
    assert resource_class_for("prospects-update") == EXTRACT
    assert resource_class_for("prospects-compact") == EXTRACT
    assert resource_class_for("prospects-summary") == EXTRACT
    assert resource_class_for("ambient-summarize") == EXTRACT
    assert EXTRACT.queue == "root.internal.inference.extract"
    assert EXTRACT.gpu_tokens == 1


def test_ambient_phases_split_cpu_from_gpu() -> None:
    from gaius.engine.sentinel_claim import (
        yk_phase_for,
        resource_class_for,
        COMPUTE,
        EXTRACT,
        extract_wait_available,
        LIGHT,
        MEDIUM,
    )

    assert yk_phase_for("ambient") == "buffer"
    assert resource_class_for("ambient") == COMPUTE
    assert yk_phase_for("ambient-summarize") == "summarize"
    assert resource_class_for("ambient-summarize") == EXTRACT
    assert yk_phase_for("ambient-compact") == "compact"
    assert resource_class_for("ambient-compact") == EXTRACT
    assert yk_phase_for("prospects-update") == "extract"
    assert yk_phase_for("prospects-compact") == "compact"
    assert yk_phase_for("prospects-summary") == "summarize"
    assert resource_class_for("ask-agent") == LIGHT
    assert resource_class_for("ask-agent").gpu_tokens == 1
    assert resource_class_for("ask-sae") == MEDIUM
    assert resource_class_for("ask-sae").gpu_tokens == 2
    assert yk_phase_for("ask-agent") == "ask"
    assert extract_wait_available() is True
    buf = yaml.safe_load(application_yaml("gaius-ambient", "ambient"))
    assert buf["metadata"]["labels"]["federation.phase"] == "buffer"
    assert "federation.zndx.org/gpu" not in buf["spec"]["containers"][0]["resources"]["requests"]
    sm = yaml.safe_load(application_yaml("gaius-sum", "ambient-summarize"))
    assert sm["metadata"]["annotations"]["federation.zndx.org/phase"] == "summarize"
    assert sm["spec"]["containers"][0]["resources"]["requests"]["federation.zndx.org/gpu"] == "1"


def test_fmp_and_ambient_are_not_extract() -> None:
    assert resource_class_for("prospects-check") == RATE_METERED
    assert resource_class_for("fmp") == RATE_METERED
    assert resource_class_for("ambient") == COMPUTE
    assert RATE_METERED.gpu_tokens == 0
    assert COMPUTE.gpu_tokens == 0
    fmp = yaml.safe_load(application_yaml("gaius-fmp-1", "prospects-check"))
    amb = yaml.safe_load(application_yaml("gaius-ambient", "ambient"))
    assert "federation.zndx.org/gpu" not in fmp["spec"]["containers"][0]["resources"]["requests"]
    assert "federation.zndx.org/gpu" not in amb["spec"]["containers"][0]["resources"]["requests"]
    assert fmp["metadata"]["annotations"]["yunikorn.apache.org/queue"] == (
        "root.external.rate-metered"
    )
    assert amb["metadata"]["annotations"]["yunikorn.apache.org/queue"] == (
        "root.internal.compute"
    )
    assert fmp["metadata"]["annotations"]["federation.zndx.org/envelope"] == (
        "apps=1,gpu=0,mem=16Mi,cpu=10m"
    )


def test_unknown_kind_fail_fast() -> None:
    from gaius.engine.sentinel_claim import YkAdmitError

    with pytest.raises(YkAdmitError, match="no resource class"):
        resource_class_for("docling")


def test_yaml_stamps_and_gpu_token() -> None:
    raw = application_yaml("article-curate-99", "article-curate")
    doc = yaml.safe_load(raw)
    labels = doc["metadata"]["labels"]
    ann = doc["metadata"]["annotations"]
    assert labels["federation.project"] == "gaius"
    assert labels["federation.workload_id"] == "article-curate-99"
    assert labels["federation.resource_class"] == "internal.inference.extract"
    assert labels["applicationId"] == "article-curate-99"
    assert labels["queue"] == "root.internal.inference.extract"
    assert labels["zarf.dev/agent"] == "ignore"
    assert ann["zarf.dev/agent"] == "ignore"
    assert "root.gaius" not in raw
    assert ann["yunikorn.apache.org/app-id"] == "article-curate-99"
    assert ann["yunikorn.apache.org/queue"] == "root.internal.inference.extract"
    req = doc["spec"]["containers"][0]["resources"]["requests"]
    lim = doc["spec"]["containers"][0]["resources"]["limits"]
    assert req["federation.zndx.org/gpu"] == "1"
    assert lim["federation.zndx.org/gpu"] == "1"
    assert req["cpu"] == lim["cpu"] == "10m"
    assert req["memory"] == lim["memory"] == "16Mi"
    assert "nvidia.com/gpu" not in raw
    assert (
        ann["federation.zndx.org/envelope"]
        == "apps=1,gpu=1,mem=16Mi,cpu=10m"
    )


def test_gpu_start_denied_when_federated_without_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GAIUS_REQUIRE_YK_ADMIT", "1")
    assert gpu_start_allowed("nobody") is False
    assert GURU_NOAPP.startswith("#YK.")


def test_bind_reuses_live_application() -> None:
    from gaius.engine.sentinel_claim import (
        EXTRACT,
        AdmittedApplication,
        bind_workload_id,
        _ADMITTED,
        _MU,
    )

    row = AdmittedApplication(
        workload_id="article-curate-1786767299",
        resource_class=EXTRACT,
        namespace="federation-signals",
        admitted=True,
        required=True,
        kind="article-curate",
    )
    with _MU:
        _ADMITTED[row.workload_id] = row
    try:
        assert (
            bind_workload_id("article-curate", "article-curate-999")
            == "article-curate-1786767299"
        )
        # Same extract envelope — prospects must not mint a second GPU token.
        assert (
            bind_workload_id("prospects-update", "prospects-update-1")
            == "article-curate-1786767299"
        )
    finally:
        with _MU:
            _ADMITTED.pop(row.workload_id, None)


def test_bind_does_not_cross_queues() -> None:
    from gaius.engine.sentinel_claim import (
        EXTRACT,
        AdmittedApplication,
        bind_workload_id,
        _ADMITTED,
        _MU,
    )

    row = AdmittedApplication(
        workload_id="article-curate-1786767299",
        resource_class=EXTRACT,
        namespace="federation-signals",
        admitted=True,
        required=True,
        kind="article-curate",
    )
    with _MU:
        _ADMITTED[row.workload_id] = row
    try:
        assert bind_workload_id("prospects-check", "gaius-fmp-1") == "gaius-fmp-1"
        assert bind_workload_id("ambient", "gaius-ambient") == "gaius-ambient"
        assert (
            bind_workload_id("ambient-summarize", "article-curate-ambient")
            == "article-curate-1786767299"
        )
    finally:
        with _MU:
            _ADMITTED.pop(row.workload_id, None)


def test_host_envelope_disk_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        GURU_DISK,
        YkAdmitError,
        assert_host_envelope,
    )

    ten_gib = 10 * 1024**3
    hundred_gib = 100 * 1024**3
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._disk_usage",
        lambda _path: (hundred_gib, hundred_gib - ten_gib, ten_gib),
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._mem_available_gib",
        lambda: 64.0,
    )
    with pytest.raises(YkAdmitError, match=GURU_DISK):
        assert_host_envelope()


def test_host_envelope_mem_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        GURU_MEM,
        YkAdmitError,
        assert_host_envelope,
    )

    two_hundred_gib = 200 * 1024**3
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._disk_usage",
        lambda _path: (two_hundred_gib, 10 * 1024**3, 190 * 1024**3),
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._mem_available_gib",
        lambda: 2.0,
    )
    with pytest.raises(YkAdmitError, match=GURU_MEM):
        assert_host_envelope()


def test_host_envelope_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import assert_host_envelope

    two_hundred_gib = 200 * 1024**3
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._disk_usage",
        lambda _path: (two_hundred_gib, 10 * 1024**3, 190 * 1024**3),
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._mem_available_gib",
        lambda: 64.0,
    )
    assert_host_envelope()


def test_apply_skips_kubectl_when_pod_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        EXTRACT,
        apply_and_admit,
        _ADMITTED,
        _MU,
    )

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.assert_host_envelope", lambda **_k: None
    )
    monkeypatch.setattr("gaius.engine.sentinel_claim.sentinels_enabled", lambda: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim.federation_required", lambda: True)
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Running"
    )

    called = {"apply": False}

    def no_apply(*_a, **_k):
        called["apply"] = True
        raise AssertionError("kubectl apply must not run for a live pod")

    monkeypatch.setattr("gaius.engine.sentinel_claim.subprocess.run", no_apply)
    try:
        row = apply_and_admit("article-curate-1786767299", "prospects-update")
        assert row.admitted is True
        assert row.resource_class == EXTRACT
        assert called["apply"] is False
    finally:
        with _MU:
            _ADMITTED.pop("article-curate-1786767299", None)


def test_prospects_disk_floor_is_raid_only() -> None:
    from gaius.engine.sentinel_claim import disk_paths_for

    assert disk_paths_for("prospects-check") == ("/raid",)
    assert disk_paths_for("prospects-update") == ("/raid",)
    assert disk_paths_for("fmp") == ("/raid",)
    assert disk_paths_for("ambient") == ()
    assert disk_paths_for("article-curate") == ("/raid",)


def test_prospects_check_ignores_full_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        assert_host_envelope,
        disk_paths_for,
    )

    def usage(path: str) -> tuple[int, int, int]:
        if path == "/":
            total = 100 * 1024**3
            free = 10 * 1024**3
            return (total, total - free, free)
        total = 200 * 1024**3
        free = 120 * 1024**3
        return (total, total - free, free)

    monkeypatch.setattr("gaius.engine.sentinel_claim._disk_usage", usage)
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._mem_available_gib",
        lambda: 64.0,
    )
    assert_host_envelope(disk_paths=disk_paths_for("prospects-check"))


def test_ambient_skips_disk_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import GURU_DISK, YkAdmitError, assert_host_envelope

    ten_gib = 10 * 1024**3
    hundred_gib = 100 * 1024**3
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._disk_usage",
        lambda _path: (hundred_gib, hundred_gib - ten_gib, ten_gib),
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._mem_available_gib",
        lambda: 64.0,
    )
    assert_host_envelope(check_disk=False)
    with pytest.raises(YkAdmitError, match=GURU_DISK):
        assert_host_envelope(check_disk=True)
