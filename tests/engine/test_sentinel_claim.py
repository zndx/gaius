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


def test_cerebras_thinking_is_token_metered_not_subscription() -> None:
    from gaius.engine.sentinel_claim import TOKEN_METERED

    assert resource_class_for("cerebras-thinking") == TOKEN_METERED
    assert resource_class_for("gaius-cerebras-thinking") == TOKEN_METERED
    doc = yaml.safe_load(application_yaml("gaius-cerebras-thinking", "cerebras-thinking"))
    assert doc["metadata"]["annotations"]["yunikorn.apache.org/queue"] == (
        "root.external.token-metered"
    )
    req = doc["spec"]["containers"][0]["resources"]["requests"]
    assert "federation.zndx.org/gpu" not in req


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
    from gaius.engine.sentinel_claim import RATE_METERED, YkAdmitError

    assert resource_class_for("article-curate") == EXTRACT
    assert resource_class_for("prospects-update") == EXTRACT
    # (2026-09-04) Compaction / summarization are no longer kinds: the flows
    # reach thinking through Engine/Complete on its standing claim.
    assert resource_class_for("fmp-roll") == RATE_METERED
    assert resource_class_for("ambient-synthesis") == COMPUTE
    for retired in ("prospects-compact", "prospects-summary", "ambient-summarize"):
        with pytest.raises(YkAdmitError):
            resource_class_for(retired)
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
    # (2026-09-04) The scheduled flows that replaced the in-engine loops.
    assert yk_phase_for("ambient-synthesis") == "synthesize"
    assert resource_class_for("ambient-synthesis") == COMPUTE
    assert yk_phase_for("fmp-roll") == "ingest"
    assert resource_class_for("fmp-roll").gpu_tokens == 0
    assert yk_phase_for("prospects-update") == "extract"
    assert resource_class_for("thinking") == HEAVY
    assert resource_class_for("ask-agent") == LIGHT
    assert resource_class_for("ask-agent").gpu_tokens == 1
    assert resource_class_for("ask-sae") == MEDIUM
    assert resource_class_for("ask-sae").gpu_tokens == 2
    assert yk_phase_for("ask-agent") == "ask"
    assert extract_wait_available() is True
    buf = yaml.safe_load(application_yaml("gaius-ambient", "ambient"))
    assert buf["metadata"]["labels"]["federation.phase"] == "buffer"
    assert "federation.zndx.org/gpu" not in buf["spec"]["containers"][0]["resources"]["requests"]
    # The heavy claim is thinking's own; compaction/summarization Complete
    # against it and never mint a heavy manifest of their own.
    sm = yaml.safe_load(application_yaml("gaius-thinking", "thinking"))
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
        # Thinking is heavy — must not reuse a Pending extract article-curate.
        assert bind_workload_id("thinking", "gaius-thinking") == "gaius-thinking"
    finally:
        with _MU:
            _ADMITTED.pop(row.workload_id, None)


def test_second_heavy_is_envelope_backpressure(
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
        # envelope backpressure, not reuse. (Compaction/summarization no
        # longer bind a kind of their own — they Complete against this claim.)
        assert bind_workload_id("thinking", "gaius-thinking") == "gaius-thinking"
        with pytest.raises(YkAdmitError, match=GURU_ENVELOPE):
            bind_workload_id("thinking", "gaius-thinking-extra")
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
    # 2026-09-04: no hard-coded preempt nudge — YuniKorn preempts by the
    # declared floors/priorities; nothing else must be poked on NOTADMITTED.
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._priority_class_line", lambda _k: ""
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
    assert yielded == []


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


# ── (2026-09-04 15:41) a GPU-token holder backs its own ColBERT ─────────────
# 28 consecutive admit deferrals: the light flow held its token, then claimed
# the shared gaius-embedding too, then needed gaius-clt — three on a leaf of two.


def test_own_gpu_token_backs_colbert_without_shared_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.engine import sentinel_claim as sc

    monkeypatch.setenv("GAIUS_YK_APPLICATION_ID", "clt-skos-admit-1")
    monkeypatch.setenv("GAIUS_YK_KIND", "clt-skos-admit")
    monkeypatch.setattr(sc, "federation_required", lambda: True)
    monkeypatch.setattr(
        sc, "_pod_phase", lambda wid: "Running" if wid == "clt-skos-admit-1" else ""
    )
    calls: list[tuple] = []
    monkeypatch.setattr(sc, "apply_and_admit", lambda *a, **k: calls.append(a))
    sc._OWN_TOKEN_LOGGED.clear()

    assert sc.own_gpu_application() == ("clt-skos-admit-1", "clt-skos-admit")
    sc.ensure_embedding_claim()
    assert calls == []  # the flow's own token is the ColBERT token


def test_own_gpu_token_waits_for_binding_then_defers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The processor admits on node binding; the pause container starts
    seconds later. The own-token path waits on the same criterion (16:00:06
    admitted / 16:00:20 Started: a phase==Running check failed the run)."""
    from gaius.engine import sentinel_claim as sc

    monkeypatch.setenv("GAIUS_YK_APPLICATION_ID", "clt-skos-admit-2")
    monkeypatch.setenv("GAIUS_YK_KIND", "clt-skos-admit")
    monkeypatch.setattr(sc, "federation_required", lambda: True)
    monkeypatch.setattr(sc, "_pod_phase", lambda wid: "Pending")
    monkeypatch.setattr(
        sc, "apply_and_admit", lambda *a, **k: pytest.fail("shared claim made")
    )
    waited: list[tuple[str, float]] = []

    def _bound(wid: str, timeout_s: float) -> bool:
        waited.append((wid, timeout_s))
        return True

    monkeypatch.setattr(sc, "_wait_running", _bound)
    sc.ensure_embedding_claim()  # bound to the node ⇒ the token is ours
    assert waited == [("clt-skos-admit-2", sc.GPU_ADMIT_TIMEOUT_S)]

    monkeypatch.setattr(sc, "_wait_running", lambda wid, t: False)
    with pytest.raises(sc.YkAdmitError, match=sc.GURU_NOTADMITTED):
        sc.ensure_embedding_claim()  # expiry is the deferral class, not NOAPP


def test_compute_flow_and_engine_still_use_the_shared_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.engine import sentinel_claim as sc

    calls: list[tuple] = []
    monkeypatch.setattr(sc, "federation_required", lambda: True)
    monkeypatch.setattr(sc, "apply_and_admit", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        sc, "_pod_phase", lambda wid: "Running" if wid == sc.EMBEDDING_WORKLOAD_ID else ""
    )
    # the compute-class ambient flow holds no GPU token of its own
    monkeypatch.setenv("GAIUS_YK_APPLICATION_ID", "ambient-synthesis-7")
    monkeypatch.setenv("GAIUS_YK_KIND", "ambient-synthesis")
    assert sc.own_gpu_application() is None
    sc.ensure_embedding_claim()
    # the engine process carries no spawn env at all
    monkeypatch.delenv("GAIUS_YK_APPLICATION_ID")
    monkeypatch.delenv("GAIUS_YK_KIND")
    assert sc.own_gpu_application() is None
    sc.ensure_embedding_claim()
    assert calls == [
        (sc.EMBEDDING_WORKLOAD_ID, "embedding"),
        (sc.EMBEDDING_WORKLOAD_ID, "embedding"),
    ]


# ── (2026-09-04) shared Pending claim + intra-leaf arbitration ──────────────


def test_class_rank_orders_buckets() -> None:
    from gaius.engine.sentinel_claim import _class_rank

    assert _class_rank("zndx-gpu-standing") > _class_rank("zndx-gpu-high")
    assert _class_rank("zndx-gpu-high") > _class_rank("zndx-gpu-normal")
    assert _class_rank("zndx-gpu-normal") > _class_rank("zndx-gpu-low")
    assert _class_rank("zndx-gpu-low") > _class_rank("")
    assert _class_rank("") == _class_rank("bogus") == -1


def _admit_scaffold(monkeypatch: pytest.MonkeyPatch, *, pending_class: str, mine: str | None):
    calls: dict[str, list] = {"apply": [], "delete": [], "yield": []}
    monkeypatch.setattr("gaius.engine.sentinel_claim.sentinels_enabled", lambda: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim.federation_required", lambda: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim.assert_host_envelope", lambda **_k: None)
    monkeypatch.setattr("gaius.engine.queue_share.notify_admit", lambda *_a, **_k: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim._pod_phase", lambda _wid: "Pending")
    monkeypatch.setattr("gaius.engine.sentinel_claim._pod_priority_class", lambda _wid: pending_class)
    monkeypatch.setattr("gaius.engine.sentinel_claim.priority_class_for", lambda _k, owner=None: mine)
    monkeypatch.setattr("gaius.engine.sentinel_claim._priority_class_line", lambda _k: "")
    monkeypatch.setattr("gaius.engine.sentinel_claim._delete_pod", lambda wid: calls["delete"].append(wid))
    monkeypatch.setattr("gaius.engine.sentinel_claim._wait_gone", lambda _wid, timeout_s=30.0: True)
    monkeypatch.setattr("gaius.engine.sentinel_claim._wait_running", lambda *_a, **_k: True)

    class Ok:
        returncode = 0
        stdout = "created"
        stderr = ""

    def _run(argv, **_k):
        if argv[:2] == ["kubectl", "apply"]:
            calls["apply"].append(argv)
        return Ok()

    monkeypatch.setattr("gaius.engine.sentinel_claim.subprocess.run", _run)
    return calls


def test_pending_shared_claim_is_reused_when_class_not_higher(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import _ADMITTED, _MU, apply_and_admit

    calls = _admit_scaffold(monkeypatch, pending_class="zndx-gpu-low", mine="zndx-gpu-low")
    try:
        row = apply_and_admit("gaius-embedding", "embedding", timeout_s=1.0)
        assert row.admitted is True
        assert calls["apply"] == []      # priorityClassName is immutable: never re-apply in place
        assert calls["delete"] == []
    finally:
        with _MU:
            _ADMITTED.pop("gaius-embedding", None)


def test_pending_shared_claim_is_raised_when_class_higher(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import _ADMITTED, _MU, apply_and_admit

    calls = _admit_scaffold(monkeypatch, pending_class="zndx-gpu-low", mine="zndx-gpu-normal")
    try:
        row = apply_and_admit("gaius-embedding", "embedding", timeout_s=1.0)
        assert row.admitted is True
        assert calls["delete"] == ["gaius-embedding"]   # unplaced pod dropped …
        assert len(calls["apply"]) == 1                  # … and re-applied under the higher class
    finally:
        with _MU:
            _ADMITTED.pop("gaius-embedding", None)


def test_intra_leaf_yields_lowest_lower_priority_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import LIGHT, _yield_lower_priority_holder

    prios = {"embedding": 40, "clt-probe": 10, "clt-skos-admit": 20, "mystery": None}
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.declared_priority_for", lambda k, owner=None: prios.get(k)
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._leaf_holders",
        lambda _rc, _ex: [
            ("clt-skos-admit-1", "Running", "clt-skos-admit"),
            ("gaius-clt", "Running", "clt-probe"),
            ("gaius-mystery", "Running", "mystery"),
            ("gaius-other", "Pending", "clt-probe"),
        ],
    )
    yielded: list[str] = []
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._request_yield",
        lambda wid, reason="": (yielded.append(wid), True)[1],
    )
    assert _yield_lower_priority_holder(LIGHT, "gaius-embedding", "embedding") == "gaius-clt"
    assert yielded == ["gaius-clt"]              # lowest declared priority, Running, below mine


def test_intra_leaf_never_yields_equal_or_undeclared(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.engine.sentinel_claim import LIGHT, _yield_lower_priority_holder

    prios = {"embedding": 20, "clt-skos-admit": 20}
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.declared_priority_for", lambda k, owner=None: prios.get(k)
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._leaf_holders",
        lambda _rc, _ex: [("clt-skos-admit-1", "Running", "clt-skos-admit")],
    )
    monkeypatch.setattr(
        "gaius.engine.sentinel_claim._request_yield", lambda *_a, **_k: pytest.fail("must not yield")
    )
    assert _yield_lower_priority_holder(LIGHT, "gaius-embedding", "embedding") is None
    # An undeclared requester never arbitrates.
    assert _yield_lower_priority_holder(LIGHT, "x", "article-curate-legacy-kind") is None
