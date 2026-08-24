"""YK Application stamps: resource class, no root.gaius, GPU token only."""

from __future__ import annotations

import pytest
import yaml

from gaius.engine.sentinel_claim import (
    COMPUTE,
    EXTRACT,
    GPU_ADMIT_TIMEOUT_S,
    HEAVY,
    LIGHT,
    GURU_GPUCOLLIDE,
    GURU_NOAPP,
    RATE_METERED,
    application_yaml,
    disk_paths_for,
    gpu_start_allowed,
    resource_class_for,
)


def test_gpu_extract_waits_for_yk_preemption() -> None:
    """60s STZ of a Blocked extract claim is how article_curate starved."""
    assert GPU_ADMIT_TIMEOUT_S >= 180.0
    assert EXTRACT.gpu_tokens == 1


def test_optillm_is_compute_not_a_gpu_claim() -> None:
    from gaius.engine.sentinel_claim import OPTILLM_WORKLOAD_ID, disk_paths_for

    assert resource_class_for("optillm") == COMPUTE
    assert resource_class_for("gaius-optillm") == COMPUTE
    assert OPTILLM_WORKLOAD_ID == "gaius-optillm"
    doc = yaml.safe_load(application_yaml("gaius-optillm", "optillm"))
    req = doc["spec"]["containers"][0]["resources"]["requests"]
    assert "federation.zndx.org/gpu" not in req
    assert doc["metadata"]["annotations"]["yunikorn.apache.org/queue"] == (
        "root.internal.compute"
    )
    assert disk_paths_for("optillm") == ()


def test_article_and_prospects_map_to_extract() -> None:
    assert resource_class_for("article-curate") == EXTRACT
    assert resource_class_for("prospects-update") == EXTRACT
    assert resource_class_for("prospects-compact") == HEAVY
    assert resource_class_for("prospects-summary") == HEAVY
    assert resource_class_for("ambient-summarize") == HEAVY
    assert EXTRACT.queue == "root.internal.inference.extract"
    assert EXTRACT.gpu_tokens == 1
    assert EXTRACT.max_applications == 2
    assert HEAVY.max_applications == 1
    assert HEAVY.gpu_tokens == 4
    assert COMPUTE.max_applications == 8
    assert LIGHT.max_applications == 2


def test_ambient_phases_split_cpu_from_gpu() -> None:
    from gaius.engine.sentinel_claim import (
        yk_phase_for,
        resource_class_for,
        COMPUTE,
        EXTRACT,
        HEAVY,
        extract_wait_available,
        LIGHT,
        MEDIUM,
    )

    assert yk_phase_for("ambient") == "buffer"
    assert resource_class_for("ambient") == COMPUTE
    assert yk_phase_for("ambient-summarize") == "summarize"
    assert resource_class_for("ambient-summarize") == HEAVY
    assert yk_phase_for("ambient-compact") == "compact"
    assert resource_class_for("ambient-compact") == COMPUTE
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
    sm = yaml.safe_load(application_yaml("gaius-thinking", "ambient-summarize"))
    assert sm["metadata"]["annotations"]["federation.zndx.org/phase"] == "summarize"
    assert sm["metadata"]["annotations"]["yunikorn.apache.org/queue"] == (
        "root.internal.inference.heavy"
    )
    assert sm["spec"]["containers"][0]["resources"]["requests"]["federation.zndx.org/gpu"] == "4"


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
        resource_class_for("not-a-flow")


def test_every_registered_flow_has_yk_class() -> None:
    from gaius.engine.sentinel_claim import (
        COMPUTE,
        EXTRACT,
        HEAVY,
        LIGHT,
        MEDIUM,
        RATE_METERED,
    )
    from gaius.flows import FLOW_REGISTRY, _register_builtin_flows

    _register_builtin_flows()
    for name, cls in FLOW_REGISTRY.items():
        kind = getattr(cls, "yk_kind", name.replace("_", "-"))
        rc = resource_class_for(kind)
        assert rc in (
            EXTRACT,
            COMPUTE,
            RATE_METERED,
            HEAVY,
            LIGHT,
            MEDIUM,
        ), (
            name,
            kind,
            rc,
        )


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


def test_bind_mints_extract_until_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        EXTRACT,
        AdmittedApplication,
        bind_workload_id,
        _ADMITTED,
        _MU,
    )

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._cluster_gaius_app_ids", lambda _q: []
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Running"
    )
    a = AdmittedApplication(
        workload_id="article-curate-1",
        resource_class=EXTRACT,
        namespace="federation-signals",
        admitted=True,
        required=True,
        kind="article-curate",
    )
    b = AdmittedApplication(
        workload_id="article-curate-2",
        resource_class=EXTRACT,
        namespace="federation-signals",
        admitted=True,
        required=True,
        kind="article-curate",
    )
    with _MU:
        _ADMITTED[a.workload_id] = a
    try:
        # One of two extract tokens in use — mint the second.
        assert bind_workload_id("article-curate", "article-curate-999") == (
            "article-curate-999"
        )
        with _MU:
            _ADMITTED[b.workload_id] = b
        from gaius.engine.sentinel_claim import GURU_ENVELOPE, YkAdmitError

        # At cap — backpressure, never steal article-curate for another process.
        with pytest.raises(YkAdmitError, match=GURU_ENVELOPE):
            bind_workload_id("prospects-update", "prospects-update-1")
        # Same process id already live is 1:1, not steal.
        assert bind_workload_id("article-curate", "article-curate-1") == (
            "article-curate-1"
        )
    finally:
        with _MU:
            _ADMITTED.pop(a.workload_id, None)
            _ADMITTED.pop(b.workload_id, None)


def test_bind_does_not_cross_queues(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        EXTRACT,
        AdmittedApplication,
        bind_workload_id,
        _ADMITTED,
        _MU,
    )

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._cluster_gaius_app_ids", lambda _q: []
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Running"
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
        # Summarize is heavy — must not reuse a Pending extract article-curate.
        assert bind_workload_id("ambient-summarize", "gaius-thinking") == (
            "gaius-thinking"
        )
    finally:
        with _MU:
            _ADMITTED.pop(row.workload_id, None)


def test_summarize_reuses_standing_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.engine.sentinel_claim import (
        HEAVY,
        AdmittedApplication,
        bind_workload_id,
        _ADMITTED,
        _MU,
    )

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._cluster_gaius_app_ids", lambda _q: []
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Running"
    )
    row = AdmittedApplication(
        workload_id="gaius-thinking",
        resource_class=HEAVY,
        namespace="federation-signals",
        admitted=True,
        required=True,
        kind="thinking",
    )
    with _MU:
        _ADMITTED[row.workload_id] = row
    try:
        from gaius.engine.sentinel_claim import GURU_ENVELOPE, YkAdmitError

        # Standing thinking is this process. A second heavy Application is
        # envelope backpressure, not reuse.
        assert bind_workload_id("ambient-summarize", "gaius-thinking") == (
            "gaius-thinking"
        )
        with pytest.raises(YkAdmitError, match=GURU_ENVELOPE):
            bind_workload_id("ambient-summarize", "gaius-thinking-extra")
    finally:
        with _MU:
            _ADMITTED.pop(row.workload_id, None)


def test_pending_extract_is_not_a_live_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.engine.sentinel_claim import bind_workload_id

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._cluster_gaius_app_ids",
        lambda _q: ["article-curate-1786767299"],
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Pending"
    )
    assert bind_workload_id("article-curate", "article-curate-new") == (
        "article-curate-new"
    )


def test_apply_and_admit_stz_unplaced_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.engine.sentinel_claim import (
        GURU_NOTADMITTED,
        YkAdmitError,
        apply_and_admit,
    )

    deleted: list[str] = []
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.assert_host_envelope", lambda **_k: None
    )
    monkeypatch.setattr("gaius.engine.sentinel_claim.sentinels_enabled", lambda: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim.federation_required", lambda: True)
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Pending"
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._wait_running", lambda *_a, **_k: False
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._delete_pod",
        lambda wid: deleted.append(wid),
    )

    class Ok:
        returncode = 0
        stdout = "created"
        stderr = ""

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.subprocess.run", lambda *_a, **_k: Ok()
    )
    with pytest.raises(YkAdmitError, match=GURU_NOTADMITTED):
        apply_and_admit("gaius-mf-docling-leak", "docling", timeout_s=0.1)
    assert deleted == ["gaius-mf-docling-leak"]


def test_extract_requests_preempt_yield_before_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.engine.sentinel_claim import YkAdmitError, apply_and_admit

    yielded: list[int] = []
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.assert_host_envelope", lambda **_k: None
    )
    monkeypatch.setattr("gaius.engine.sentinel_claim.sentinels_enabled", lambda: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim.federation_required", lambda: True)
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Pending"
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._wait_running", lambda *_a, **_k: False
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._delete_pod", lambda _wid: None
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._request_preempt_yield",
        lambda: yielded.append(1),
    )

    class Ok:
        returncode = 0
        stdout = "created"
        stderr = ""

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.subprocess.run", lambda *_a, **_k: Ok()
    )
    with pytest.raises(YkAdmitError):
        apply_and_admit("article-curate-yield", "article-curate", timeout_s=0.1)
    assert yielded == [1]


def test_docling_flow_is_compute_not_extract() -> None:
    from gaius.engine.sentinel_claim import COMPUTE, EXTRACT, resource_class_for

    assert resource_class_for("docling") == COMPUTE
    assert resource_class_for("article-curate") == EXTRACT


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
    assert disk_paths_for("thinking") == ()
    assert disk_paths_for("ask-agent") == ()
    assert disk_paths_for("article-curate") == ("/raid",)
    assert disk_paths_for("clt-skos-admit") == ("/raid",)
    assert disk_paths_for("knowledge-summary") == ("/raid",)
    assert resource_class_for("clt-skos-label") == COMPUTE
    assert resource_class_for("docling") == COMPUTE
    assert resource_class_for("thinking") == HEAVY
    assert resource_class_for("thinking").gpu_tokens == 4


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


def test_colbert_is_light_one_gpu() -> None:
    from gaius.engine.sentinel_claim import (
        DEPLOYMENT_PROFILES,
        EMBEDDING_WORKLOAD_ID,
        MEDIUM,
        YkAdmitError,
        class_for_gpu_tokens,
        yk_phase_for,
    )

    assert class_for_gpu_tokens(1) is LIGHT
    assert class_for_gpu_tokens(2) is MEDIUM
    assert class_for_gpu_tokens(4) is HEAVY
    with pytest.raises(YkAdmitError, match="not a profile"):
        class_for_gpu_tokens(3)
    assert resource_class_for("aperture") is LIGHT
    assert resource_class_for("colbert") is LIGHT
    assert resource_class_for("clt-skos-admit") is LIGHT
    assert DEPLOYMENT_PROFILES["embedding"].gpu_tokens == 1
    assert DEPLOYMENT_PROFILES["embedding"].resource_class() is LIGHT
    assert yk_phase_for("embedding") == "embed"
    doc = yaml.safe_load(application_yaml(EMBEDDING_WORKLOAD_ID, "embedding"))
    req = doc["spec"]["containers"][0]["resources"]["requests"]
    assert req["federation.zndx.org/gpu"] == "1"
    assert doc["metadata"]["annotations"]["yunikorn.apache.org/queue"] == (
        "root.internal.inference.light"
    )
    assert "nvidia.com/gpu" not in yaml.dump(doc)
    from gaius.flows.clt_skos.admit import CltSkosAdmitFlow

    assert CltSkosAdmitFlow.gpu_tokens == 1
    assert CltSkosAdmitFlow.model == "lightonai/ColBERT-Zero"


def test_embedding_cuda_skips_thinking_gpus(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import (
        YkAdmitError,
        embedding_cuda_device,
    )

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.federation_required", lambda: False
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.vllm_held_gpu_ids", lambda: {0, 1, 2, 3}
    )
    from gaius.engine.sentinel_claim import reset_light_device_pin

    reset_light_device_pin()
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.gpu_free_mib",
        lambda: {0: 137, 1: 200, 2: 180, 3: 150, 4: 22000, 5: 23000},
    )
    assert embedding_cuda_device() == "cuda:4"
    assert embedding_cuda_device() == "cuda:4"
    reset_light_device_pin()
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.gpu_free_mib",
        lambda: {0: 137, 1: 200, 2: 180, 3: 150, 4: 200, 5: 180},
    )
    with pytest.raises(YkAdmitError, match=GURU_GPUCOLLIDE):
        embedding_cuda_device()
