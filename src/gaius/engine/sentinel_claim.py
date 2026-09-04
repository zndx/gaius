"""YK Application claim for a spawned Gaius flow.

Queue path is the resource class. Project is identity only
(``federation.project=gaius``). There is no ``root.gaius``.

The Application is the Yield victim: YK preempt → C2 last-gasp :50561 →
``zndx.engine.v1.Engine/Yield`` on :50051. Host GPU occupancy is
``federation.zndx.org/gpu`` only — never ``nvidia.com/gpu`` on this
CPU-only sentinel (that would bind the card into an empty pod).

Signals / YK shows Gaius lanes on existing leaves (no ``root.gaius``):

- ``external.rate-metered`` — FMP ingest. Comes and goes.
- ``internal.compute`` — Ambient RAM FIFO and CPU Metaflow ticks.
  Standing while the daemon runs. Never a disk write.
- ``internal.inference.extract`` — Docling / article GPU children only.
- ``internal.inference.light`` — models that fit on 1 GPU (Ask 1.7B,
  ColBERT-Zero / Aperture MaxSim).
- ``internal.inference.medium`` — models that need 2 consecutive GPUs
  (Ask SAE 9B).
- ``internal.inference.heavy`` — models that need 4 consecutive GPUs
  (Qwen3.8 thinking). Ambient summarize rides this Application.
- ``internal.compute`` — ``gaius-optillm`` gunicorn (CPU proxy). GPU
  occupancy stays on the vLLM Application it binds; optillm does not
  mint a second GPU claim when a vLLM is already provided.

A workload declares a model deployment profile (``gpu_tokens`` 1 / 2 / 4).
YK picks light / medium / heavy from that. Homemade leaves (e.g. a
private embedding queue) are not a profile. Non-trivial GPU work belongs
in Metaflow; in-process CUDA in the engine is debt and collides.

Host disk and RAM are not YK resources — Gaius refuses new disk-writing
children when those floors are crossed so the box cannot fill past the
physical lid. Ambient (compute) skips the disk floor.

Each **non-K8s host process** is 1:1 with a sentinel Application.
Metaflow ``@kubernetes`` steps already surface in YK as compute — they
do not borrow extract. When the host process ends, the sentinel is
retired (STZ / ``delete_flow_sentinel``) so the next process can admit.
Never reuse another process's Application at queue cap: that is YK
backpressure, not a hint to steal.

Admit (pod Running) is required before exclusive GPU start when Signals
is on the lattice. Standalone devenv skips the claim.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

log = logging.getLogger("gaius.engine.sentinel_claim")

_NS = os.environ.get("SIGNALS_SENTINEL_NAMESPACE", "federation-signals")
_C2 = os.environ.get("SIGNALS_C2_URL", "http://127.0.0.1:50561")
_GPU_KEY = "federation.zndx.org/gpu"

GURU_NOADMIT = "#YK.00000001.NOADMIT"
GURU_NOTADMITTED = "#YK.00000002.NOTADMITTED"
GURU_NOAPP = "#YK.00000003.NOAPP"
GURU_ENVELOPE = "#YK.00000004.ENVELOPE"
GURU_DISK = "#YK.00000005.DISK"
GURU_MEM = "#YK.00000006.MEM"
GURU_GPUCOLLIDE = "#YK.00000008.GPUCOLLIDE"

# CPU sentinels place immediately. GPU extract waits for YK to preempt
# medium (ask-sae) after extract's guaranteed floor is promoted.
#
# GPU admit wait: with thinking holding heavy's 4-GPU floor, ONE spare token is
# shared by extract + light. A light claimant (clt-skos-admit, every 15 min) holds
# it ~195s, so a 180s wait was a guaranteed #YK.00000002.NOTADMITTED for any
# extract flow landing on a :00/:15/:30/:45 boundary (the daily 09:00
# article-curate collided every night). YK Blocked IS the queue — a reasoning
# flow can afford to wait behind a light hold; 600s spans two of them.
CPU_ADMIT_TIMEOUT_S = 60.0
GPU_ADMIT_TIMEOUT_S = float(os.environ.get("GAIUS_YK_GPU_ADMIT_TIMEOUT_S", "600"))

# Tinybox: 6× RTX 4090 24Gi, ~128Gi RAM. Queues are light (1 GPU), medium
# (2 consecutive), heavy (4 consecutive). Compute has no GPU — many CPU
# Metaflow ticks must not serialize on a 1-app envelope.
# Pause-pod CPU/mem are sentinel-sized; host CUDA is not in the pod.
ENVELOPE_GPU = 1
ENVELOPE_CPU = "10m"
ENVELOPE_MEMORY = "16Mi"
ENVELOPE_DISK_MIN_FREE_GIB = {
    "/": 32,
    "/raid": 64,
}
ENVELOPE_DISK_MAX_USED_PCT = 98.0
ENVELOPE_MEM_MIN_FREE_GIB = 8.0


class YkAdmitError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(
            f"{code} {detail}\n"
            "  Stamp yunikorn.apache.org/queue (provided) on a leaf.\n"
            "  Try: kubectl -n federation-signals get pod <workload_id>\n"
            "  Or:  grpcurl -plaintext 127.0.0.1:50551 "
            "zndx.scheduler.v1.Scheduler/ListQueueApplications"
        )


@dataclass(frozen=True)
class ResourceClass:
    """Leaf resource class. ``name`` is the stamp; ``queue`` is the YK path."""

    name: str
    queue: str
    gpu_tokens: int
    max_applications: int = 1


EXTRACT = ResourceClass(
    name="internal.inference.extract",
    queue="root.internal.inference.extract",
    gpu_tokens=ENVELOPE_GPU,
    # Envelope on this leaf (YK maxapplications), not a private GPU stash.
    max_applications=2,
)

# Models that fit on 1 GPU (Ask 1.7B, ColBERT-Zero). Not extract. Not SAE.
LIGHT = ResourceClass(
    name="internal.inference.light",
    queue="root.internal.inference.light",
    gpu_tokens=1,
    max_applications=2,
)

# Models that need 2 consecutive GPUs (Ask SAE 9B). Light must not land here.
MEDIUM = ResourceClass(
    name="internal.inference.medium",
    queue="root.internal.inference.medium",
    gpu_tokens=2,
    max_applications=1,
)

# Models that need 4 consecutive GPUs (Qwen3.8-27B TP=4).
HEAVY = ResourceClass(
    name="internal.inference.heavy",
    queue="root.internal.inference.heavy",
    gpu_tokens=4,
    max_applications=1,
)

# FMP / RPM APIs: no GPU. Application is deleted when the check ends.
RATE_METERED = ResourceClass(
    name="external.rate-metered",
    queue="root.external.rate-metered",
    gpu_tokens=0,
    max_applications=4,
)

# Ambient + host Metaflow ticks (label, …). No GPU.
COMPUTE = ResourceClass(
    name="internal.compute",
    queue="root.internal.compute",
    gpu_tokens=0,
    max_applications=8,
)

AMBIENT_WORKLOAD_ID = "gaius-ambient"
OPTILLM_WORKLOAD_ID = "gaius-optillm"
EMBEDDING_WORKLOAD_ID = "gaius-embedding"
LIGHT_MIN_FREE_MIB = 4096


def class_for_gpu_tokens(n: int, *, offline: bool = False) -> ResourceClass:
    """YK leaf from the model deployment profile.

    1 GPU → light, 2 consecutive → medium, 4 consecutive → heavy.
    0 → compute. Offline extract is Docling, not a size class.
    """
    tokens = int(n)
    if tokens < 0:
        raise YkAdmitError(
            GURU_NOADMIT, f"gpu_tokens={tokens} is not a deployment profile"
        )
    if tokens == 0:
        return COMPUTE
    if offline:
        return EXTRACT
    if tokens == 1:
        return LIGHT
    if tokens == 2:
        return MEDIUM
    if tokens == 4:
        return HEAVY
    raise YkAdmitError(
        GURU_NOADMIT,
        f"gpu_tokens={tokens} is not a profile; use 1 (light), "
        "2 consecutive (medium), or 4 consecutive (heavy)",
    )


@dataclass(frozen=True)
class ModelDeploymentProfile:
    """What YK needs to schedule a WRK. Queue names stay light/medium/heavy."""

    wrk: str
    model: str
    gpu_tokens: int
    tensor_parallel: int
    pipeline_parallel: int = 1
    capabilities: tuple[str, ...] = ()
    offline: bool = False

    def resource_class(self) -> ResourceClass:
        return class_for_gpu_tokens(self.gpu_tokens, offline=self.offline)


DEPLOYMENT_PROFILES: dict[str, ModelDeploymentProfile] = {
    "thinking": ModelDeploymentProfile(
        wrk="thinking",
        model="Qwen/Qwen3.8-27B",
        gpu_tokens=4,
        tensor_parallel=4,
        capabilities=("thinking", "complete"),
    ),
    "ask-sae": ModelDeploymentProfile(
        wrk="ask-sae",
        model="Qwen/Qwen3-8B",
        gpu_tokens=2,
        tensor_parallel=2,
        capabilities=("complete",),
    ),
    "ask-agent": ModelDeploymentProfile(
        wrk="ask-agent",
        model="Qwen/Qwen3-1.7B",
        gpu_tokens=1,
        tensor_parallel=1,
        capabilities=("complete",),
    ),
    "embedding": ModelDeploymentProfile(
        wrk="embedding",
        model="lightonai/ColBERT-Zero",
        gpu_tokens=1,
        tensor_parallel=1,
        capabilities=("open-embedding",),
    ),
    "optillm": ModelDeploymentProfile(
        wrk="optillm",
        model="proxy",
        gpu_tokens=0,
        tensor_parallel=0,
        capabilities=("complete",),
    ),
    "article-curate": ModelDeploymentProfile(
        wrk="article-curate",
        model="",
        gpu_tokens=1,
        tensor_parallel=0,
        capabilities=("extract",),
        offline=True,
    ),
}

# EXTRACT is Docling / article GPU only. Thinking Complete (Qwen3.8)
# rides HEAVY so summarize does not steal extract slots from Docling.
_KIND_CLASS: dict[str, ResourceClass] = {
    "article-curate": EXTRACT,
    "article_curate": EXTRACT,
    "article-curation": EXTRACT,
    "article_curation": EXTRACT,
    # Prospects runs NEED a GPU token (user, 2026-09-04): the engine-side
    # ProspectsService admits `prospects-update` itself (prospects_service.py
    # apply_and_admit) and Signals' publish contract stamps every prospects run
    # on the extract leaf (flows/prospects/publish.py yk_queue=EXTRACT.queue).
    # Briefly mapped to COMPUTE on 2026-09-04 — a regression, reverted. The
    # 02:48 starvation is solved without touching this: the skos admit flow
    # (pure Yield bookkeeping) no longer takes a light token, and
    # gaius-embedding is a standing claim from boot, so budget during a
    # prospects run is thinking 4 + embedding 1 + extract 1 = 6, no deadlock.
    "prospects-update": EXTRACT,
    "prospects_update": EXTRACT,
    # Metaflow / host Python ticks are compute. EXTRACT is the Docling GPU
    # process only (article-curate), not the wrapping flow.
    "docling": COMPUTE,
    "card-upkeep": COMPUTE,
    "card_upkeep": COMPUTE,
    "prospects-check": RATE_METERED,
    "prospects_check": RATE_METERED,
    "fmp": RATE_METERED,
    "ambient": COMPUTE,
    "ambient-compact": COMPUTE,
    "ambient_compact": COMPUTE,
    # The CLT worker (gaius-clt) is a GPU model — 6.6 GB resident on GPU 4 —
    # and feature_probe gates its admission on a free LIGHT slot. Mapped to
    # COMPUTE (0 tokens) since 2026-08-20 it ran a GPU with no token, so
    # YuniKorn's accounting understated physical use by one GPU. Honest
    # budget: thinking 4 + clt 1 + embedding 1 = 6; extract queues behind
    # embedding's release. (Corrected 2026-09-04 at the user's insistence.)
    "clt-probe": LIGHT,
    "clt_probe": LIGHT,
    "clt-skos-eval": COMPUTE,
    "clt_skos_eval": COMPUTE,
    "clt-skos-label": COMPUTE,
    "clt_skos_label": COMPUTE,
    "knowledge-summary": COMPUTE,
    "knowledge_summary": COMPUTE,
    "research": COMPUTE,
    "search": COMPUTE,
    "metaflow": COMPUTE,
    # Ask 1.7B: one whole GPU per replica (light).
    "ask-agent": LIGHT,
    "ask_agent": LIGHT,
    "ask-light": LIGHT,
    # Ask SAE 9B: two whole GPUs, medium leaf only.
    "ask-sae": MEDIUM,
    "ask_sae": MEDIUM,
    "ask-medium": MEDIUM,
    # Qwen3.8 thinking. Ambient summarize / prospects compact Complete
    # reuse gaius-thinking (heavy cap 1) — thinking channel is CLT/SAE input.
    "thinking": HEAVY,
    "gaius-thinking": HEAVY,
    "ambient-summarize": HEAVY,
    "ambient_summarize": HEAVY,
    "prospects-compact": HEAVY,
    "prospects_compact": HEAVY,
    "prospects-summary": HEAVY,
    "prospects_summary": HEAVY,
    # gunicorn proxy. 0 extra GPU — bind a provided vLLM; demand one
    # via zndx.engine.v1 only when none is healthy.
    "optillm": COMPUTE,
    "gaius-optillm": COMPUTE,
    # Product-generic tier settle (Kudu -> Iceberg/HDF5). Per-product spawn kinds
    # tier-settle-<product>; the bare kinds cover a defaulted product.
    "tier-settle": COMPUTE,
    "tier_settle": COMPUTE,
    "tier-settle-signal": COMPUTE,
    # ColBERT-Zero MaxSim: 1 GPU model → light (same leaf as Ask 1.7B).
    # In-engine Aperture CUDA is undeclared Metaflow debt; admit light first.
    "embedding": LIGHT,
    "gaius-embedding": LIGHT,
    "colbert": LIGHT,
    "aperture": LIGHT,
    "maxsim": LIGHT,
    # The admit flow declares itself a one-token GPU claim (admit.py
    # `gpu_tokens = 1`: it runs ColBERT CUDA on its gpu-index in-process),
    # and sentinel_claim's consistency guard refuses a flow whose declared
    # class differs from this map (#YK.00000001.NOADMIT). Mapped to COMPUTE
    # for ~1 h on 2026-09-04 — every admit failed at start; reverted.
    "clt-skos-admit": LIGHT,
    "clt_skos_admit": LIGHT,
}


def resource_class_for(kind: str) -> ResourceClass:
    try:
        return _KIND_CLASS[kind]
    except KeyError as e:
        raise YkAdmitError(
            GURU_NOADMIT,
            f"no resource class for kind={kind!r}; "
            "gpu_tokens 1=light, 2 consecutive=medium, 4 consecutive=heavy; "
            "extract if offline Docling; compute if 0. "
            "Declare a model deployment profile — do not invent a queue.",
        ) from e


@dataclass
class AdmittedApplication:
    workload_id: str
    resource_class: ResourceClass
    namespace: str
    admitted: bool
    required: bool
    error: str = ""
    kind: str = ""


_MU = Lock()
_ADMITTED: dict[str, AdmittedApplication] = {}


def sentinels_enabled() -> bool:
    raw = os.environ.get("GAIUS_FLOW_SENTINEL", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return shutil.which("kubectl") is not None


def federation_required() -> bool:
    """True when Signals is on the lattice — admit is mandatory."""
    raw = (os.environ.get("GAIUS_REQUIRE_YK_ADMIT") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return _signals_scheduler_present()


def _signals_scheduler_present() -> bool:
    addr = os.environ.get("SIGNALS_ENGINE_GRPC", "127.0.0.1:50551")
    try:
        import grpc

        from gaius.engine.generated.zndx.engine.v1 import engine_pb2
        from gaius.engine.generated.zndx.engine.v1 import engine_pb2_grpc
    except ImportError:
        return False
    channel = grpc.insecure_channel(addr)
    try:
        stub = engine_pb2_grpc.EngineStub(channel)
        resp = stub.Status(engine_pb2.StatusRequest(), timeout=2.0)
        if (resp.project or "").lower() != "signals":
            return False
        return any(
            (ep.capability or "").lower() == "scheduler" and ep.healthy
            for ep in resp.endpoints
        )
    except Exception:
        return False
    finally:
        channel.close()


# Phase is what YK/operators see. Summarize is heavy thinking, not extract.
_KIND_PHASE: dict[str, str] = {
    "ambient": "buffer",
    "ambient-summarize": "summarize",
    "ambient_summarize": "summarize",
    "ambient-compact": "compact",
    "ambient_compact": "compact",
    "article-curate": "extract",
    "article_curate": "extract",
    "prospects-update": "extract",
    "prospects_update": "extract",
    "prospects-compact": "compact",
    "prospects_compact": "compact",
    "prospects-summary": "summarize",
    "prospects_summary": "summarize",
    "prospects-check": "ingest",
    "prospects_check": "ingest",
    "fmp": "ingest",
    "ask-agent": "ask",
    "ask_agent": "ask",
    "ask-light": "ask",
    "ask-sae": "ask",
    "ask_sae": "ask",
    "ask-medium": "ask",
    "clt-probe": "probe",
    "clt_probe": "probe",
    "clt-skos-admit": "admit",
    "clt_skos_admit": "admit",
    "clt-skos-eval": "eval",
    "clt_skos_eval": "eval",
    "clt-skos-label": "label",
    "clt_skos_label": "label",
    "knowledge-summary": "summary",
    "knowledge_summary": "summary",
    "article-curation": "extract",
    "article_curation": "extract",
    "card-upkeep": "extract",
    "card_upkeep": "extract",
    "docling": "flow",
    "research": "extract",
    "search": "extract",
    "metaflow": "work",
    "thinking": "think",
    "gaius-thinking": "think",
    "optillm": "proxy",
    "gaius-optillm": "proxy",
    "tier-settle": "settle",
    "tier_settle": "settle",
    "tier-settle-signal": "settle",
    "embedding": "embed",
    "gaius-embedding": "embed",
    "colbert": "embed",
    "aperture": "embed",
    "maxsim": "embed",
}


def light_wait_available() -> bool:
    """True if YK may still place an Ask (light) Sentinel.

    Never start light/medium vLLM without this. Going around YK OOMs the box.
    Standalone (no Signals scheduler): True so local Settings can start Ask.
    """
    if not sentinels_enabled() or not federation_required():
        return True
    with _MU:
        n = sum(
            1
            for row in _ADMITTED.values()
            if row.admitted and row.resource_class.queue == LIGHT.queue
        )
    return n < LIGHT.max_applications


def extract_wait_available() -> bool:
    """Backward name: light leaf, not extract."""
    return light_wait_available()


def yk_phase_for(kind: str) -> str:
    return _KIND_PHASE.get(kind, "work")


def disk_paths_for(kind: str) -> tuple[str, ...]:
    """Mounts this kind may fill. Empty = no disk floor.

    Prospects / FMP product bytes land on RustFS (``/raid``). A full
    root must not refuse that lane. Article curate writes KB under
    ``/raid/signals/var/kb/dev`` (``./build/dev`` is a symlink).
    """
    rc = resource_class_for(kind)
    k = kind.replace("_", "-")
    if k in {
        "knowledge-summary",
        "clt-skos-admit",
        "clt-skos-eval",
        "article-curation",
        "card-upkeep",
        "docling",
        "article-curate",
        "clt-probe",
    } or k.startswith("prospects-"):
        return ("/raid",)
    if rc.queue in (HEAVY.queue, LIGHT.queue, MEDIUM.queue):
        # vLLM occupancy — not KB writers. A full root must not refuse Complete.
        return ()
    if k in {
        "ambient",
        "ambient-compact",
        "clt-skos-label",
        "optillm",
        "gaius-optillm",
        "embedding",
        "gaius-embedding",
        "colbert",
        "aperture",
        "maxsim",
    }:
        return ()
    if rc.queue == RATE_METERED.queue:
        return ("/raid",)
    return ("/", "/raid")


def application_yaml(workload_id: str, kind: str) -> str:
    """Pod manifest. Annotation queue is what YK ``provided`` placement reads."""
    rc = resource_class_for(kind)
    phase = yk_phase_for(kind)
    gpu_req = ""
    gpu_lim = ""
    if rc.gpu_tokens > 0:
        gpu_req = f"\n          {_GPU_KEY}: \"{rc.gpu_tokens}\""
        gpu_lim = f"\n          {_GPU_KEY}: \"{rc.gpu_tokens}\""
    return f"""apiVersion: v1
kind: Pod
metadata:
  name: {workload_id}
  namespace: {_NS}
  labels:
    app.kubernetes.io/component: minifi-sentinel
    federation.project: gaius
    federation.workload_id: {workload_id}
    federation.resource_class: {rc.name}
    federation.kind: {kind}
    federation.phase: {phase}
    applicationId: {workload_id}
    queue: {rc.queue}
    zarf.dev/agent: ignore
  annotations:
    zarf.dev/agent: ignore
    yunikorn.apache.org/app-id: {workload_id}
    yunikorn.apache.org/queue: {rc.queue}
    federation.zndx.org/envelope: "apps=1,gpu={rc.gpu_tokens},mem={ENVELOPE_MEMORY},cpu={ENVELOPE_CPU}"
    federation.zndx.org/phase: "{phase}"
spec:
  restartPolicy: Never
  hostNetwork: true
  containers:
    - name: sentinel
      # Already on tinybox (rke2). zarf.dev/agent: ignore skips registry rewrite.
      image: rancher/mirrored-pause:3.6
      imagePullPolicy: IfNotPresent
      env:
        - name: FEDERATION_PROJECT
          value: gaius
        - name: FEDERATION_RESOURCE_CLASS
          value: {rc.name}
      lifecycle:
        preStop:
          exec:
            command:
              - sh
              - -c
              - |
                wget -q -O- --post-data='{{"workload_id":"{workload_id}","project":"gaius","phase":"preempted","sentinel_id":"{workload_id}"}}' \\
                  --header='Content-Type: application/json' \\
                  "{_C2}/c2-protocol/last-gasp" || true
      resources:
        requests:
          cpu: {ENVELOPE_CPU}
          memory: {ENVELOPE_MEMORY}{gpu_req}
        limits:
          cpu: {ENVELOPE_CPU}
          memory: {ENVELOPE_MEMORY}{gpu_lim}
"""


def _disk_usage(path: str) -> tuple[int, int, int]:
    usage = shutil.disk_usage(path)
    return (int(usage.total), int(usage.used), int(usage.free))


def _mem_available_gib() -> float:
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError as e:
        raise YkAdmitError(
            GURU_MEM,
            f"cannot read /proc/meminfo: {e}",
        ) from e
    raise YkAdmitError(GURU_MEM, "MemAvailable missing from /proc/meminfo")


def assert_host_envelope(
    *,
    check_disk: bool = True,
    disk_paths: tuple[str, ...] | None = None,
) -> None:
    """Refuse new children when *this kind's* disk or host RAM is past the floor.

    Check only the mounts the child writes. RustFS product lanes use
    ``/raid``; a full root does not refuse them.
    """
    paths: tuple[str, ...]
    if disk_paths is not None:
        paths = disk_paths
    elif check_disk:
        paths = tuple(ENVELOPE_DISK_MIN_FREE_GIB)
    else:
        paths = ()
    for path in paths:
        min_free = ENVELOPE_DISK_MIN_FREE_GIB.get(path)
        if min_free is None or not os.path.isdir(path):
            continue
        total, used, free = _disk_usage(path)
        free_gib = free / (1024**3)
        used_pct = (used / total) * 100 if total else 0.0
        if free_gib < min_free or used_pct > ENVELOPE_DISK_MAX_USED_PCT:
            raise YkAdmitError(
                GURU_DISK,
                f"{path} free {free_gib:.1f}Gi ({used_pct:.0f}% used); "
                f"envelope floor is {min_free}Gi free and "
                f"<{ENVELOPE_DISK_MAX_USED_PCT:.0f}% used. "
                "YK does not cap host disk — Gaius refuses the child. "
                f"Free space (dust -d 1 {path}) or condense; then retry.",
            )
    avail = _mem_available_gib()
    if avail < ENVELOPE_MEM_MIN_FREE_GIB:
        raise YkAdmitError(
            GURU_MEM,
            f"MemAvailable {avail:.1f}Gi; envelope floor is "
            f"{ENVELOPE_MEM_MIN_FREE_GIB:.0f}Gi. "
            "Do not start another host child on this box.",
        )


def apply_and_admit(
    workload_id: str,
    kind: str,
    *,
    timeout_s: float | None = None,
) -> AdmittedApplication:
    """Apply the Application and wait until the pod is Running (YK admitted).

    Do not treat a short Pending as failure: YK Blocked is the queue.
    GPU extract waits for preemption of medium (ask-sae) rather than
    STZ-ing the claim at 60s and leaving the work unscheduled.
    """
    rc = resource_class_for(kind)
    if timeout_s is None:
        timeout_s = GPU_ADMIT_TIMEOUT_S if rc.gpu_tokens else CPU_ADMIT_TIMEOUT_S
    assert_host_envelope(disk_paths=disk_paths_for(kind))
    required = federation_required()
    if not sentinels_enabled():
        row = AdmittedApplication(
            workload_id=workload_id,
            resource_class=rc,
            namespace=_NS,
            admitted=False,
            required=required,
            error="sentinels disabled or kubectl missing",
            kind=kind,
        )
        if required:
            raise YkAdmitError(
                GURU_NOADMIT,
                f"{row.error}; Signals scheduler is up so admit is mandatory",
            )
        return row

    try:
        from gaius.engine.queue_share import notify_admit

        notify_admit(kind, rc)
    except RuntimeError as e:
        if "SHAREFAIL" in str(e):
            raise
        log.warning("RequestQueueShare skipped: %s", e)
    except Exception as e:
        log.warning("RequestQueueShare skipped: %s", e)

    if _pod_phase(workload_id) == "Running":
        row = AdmittedApplication(
            workload_id=workload_id,
            resource_class=rc,
            namespace=_NS,
            admitted=True,
            required=required,
            kind=kind,
        )
        with _MU:
            _ADMITTED[workload_id] = row
        log.info(
            "reusing Running Application %s kind=%s (skip kubectl apply)",
            workload_id,
            kind,
        )
        return row

    yaml_body = application_yaml(workload_id, kind)
    if rc == EXTRACT:
        # Standing ask-sae (medium) may still occupy tokens extract needs.
        # YK custom-resource preemption may not victim it; C2 last-gasp
        # Yields the host vLLM so extract can place. Same process must not
        # gRPC-Yield itself (deadlock).
        _request_preempt_yield()
    r = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=yaml_body,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "")[:400]
        row = AdmittedApplication(
            workload_id=workload_id,
            resource_class=rc,
            namespace=_NS,
            admitted=False,
            required=required,
            error=detail,
            kind=kind,
        )
        if required:
            raise YkAdmitError(GURU_NOADMIT, f"kubectl apply {workload_id}: {detail}")
        log.warning("sentinel apply %s: %s", workload_id, detail)
        return row

    if not _wait_running(workload_id, timeout_s):
        # Unplaced claim occupies the YK Application id. STZ it so the
        # next process can admit — do not leak Pending pause pods.
        log.error(
            "sentinel not Running in %.0fs; STZ %s on %s",
            timeout_s,
            workload_id,
            rc.queue,
        )
        _delete_pod(workload_id)
        row = AdmittedApplication(
            workload_id=workload_id,
            resource_class=rc,
            namespace=_NS,
            admitted=False,
            required=required,
            error=f"pod {workload_id} not Running on {rc.queue} within {timeout_s:.0f}s",
            kind=kind,
        )
        if required:
            raise YkAdmitError(GURU_NOTADMITTED, row.error)
        log.warning("sentinel not admitted %s", row.error)
        return row

    row = AdmittedApplication(
        workload_id=workload_id,
        resource_class=rc,
        namespace=_NS,
        admitted=True,
        required=required,
        kind=kind,
    )
    with _MU:
        _ADMITTED[workload_id] = row
    log.info(
        "admitted Application %s class=%s queue=%s gpu=%s",
        workload_id,
        rc.name,
        rc.queue,
        rc.gpu_tokens,
    )
    return row


def apply_flow_sentinel(workload_id: str, kind: str) -> bool:
    """Back-compat wrapper: admit when required, else best-effort."""
    try:
        return apply_and_admit(workload_id, kind).admitted
    except YkAdmitError:
        raise


def delete_flow_sentinel(workload_id: str) -> None:
    with _MU:
        row = _ADMITTED.pop(workload_id, None)
    if row is not None and (row.kind or "").strip():
        try:
            from gaius.engine.queue_share import notify_release

            notify_release(row.kind, row.resource_class)
        except Exception as e:
            log.warning("RequestQueueShare end skipped: %s", e)
    _delete_pod(workload_id)


def _request_preempt_yield() -> None:
    """Ask C2 to Yield standing medium (ask-sae) so extract can admit."""
    import urllib.request

    for wid in ("gaius-ask-sae",):
        if _pod_phase(wid) != "Running":
            continue
        body = (
            '{"workload_id":"%s","project":"gaius","phase":"preempted",'
            '"sentinel_id":"%s"}' % (wid, wid)
        ).encode()
        req = urllib.request.Request(
            f"{_C2}/c2-protocol/last-gasp",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            log.info("requested preempt Yield of %s for extract", wid)
        except Exception as e:
            log.warning("preempt Yield of %s failed: %s", wid, e)


def _delete_pod(workload_id: str) -> None:
    if not shutil.which("kubectl"):
        return
    subprocess.run(
        [
            "kubectl",
            "-n",
            _NS,
            "delete",
            "pod",
            workload_id,
            "--ignore-not-found=true",
            "--wait=false",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )


def is_admitted(workload_id: str) -> bool:
    with _MU:
        row = _ADMITTED.get(workload_id)
    return bool(row and row.admitted)


def _cluster_gaius_app_ids(queue: str) -> list[str]:
    if not shutil.which("kubectl"):
        return []
    r = subprocess.run(
        [
            "kubectl",
            "-n",
            _NS,
            "get",
            "pods",
            "-l",
            f"federation.project=gaius,queue={queue}",
            "--field-selector",
            "status.phase=Running",
            "-o",
            "jsonpath={.items[*].metadata.name}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return [n for n in (r.stdout or "").split() if n]


def live_apps_on_queue(kind: str) -> list[str]:
    """Gaius Application ids currently Running on this kind's YK leaf.

    Pending is not a live envelope — reusing it is a 60s NOTADMITTED loop.
    """
    rc = resource_class_for(kind)
    names: list[str] = []
    with _MU:
        for row in _ADMITTED.values():
            if row.admitted and row.resource_class.queue == rc.queue:
                names.append(row.workload_id)
    names.extend(_cluster_gaius_app_ids(rc.queue))
    uniq = list(dict.fromkeys(names))
    live: list[str] = []
    for wid in uniq:
        phase = _pod_phase(wid)
        if phase in ("", "Running"):
            live.append(wid)
    return live


def live_workload_id(kind: str) -> str | None:
    """A live Application on this kind's queue, or None."""
    rc = resource_class_for(kind)
    uniq = live_apps_on_queue(kind)
    if rc.gpu_tokens and len(uniq) > rc.max_applications:
        raise YkAdmitError(
            GURU_ENVELOPE,
            f"{len(uniq)} Gaius Applications on {rc.queue}: {uniq}; "
            f"envelope cap is {rc.max_applications} app / "
            f"{rc.gpu_tokens} GPU each",
        )
    return uniq[0] if uniq else None


def bind_workload_id(kind: str, proposed: str) -> str:
    """Return ``proposed``. Never steal another process's sentinel.

    If ``proposed`` is already Running, that is this process's own claim.
    If the leaf is at cap with other ids, raise ``GURU_ENVELOPE`` — YK
    backpressure. Retire a finished sentinel (STZ) before minting another.
    """
    rc = resource_class_for(kind)
    live = live_apps_on_queue(kind)
    if proposed in live:
        return proposed
    if len(live) >= rc.max_applications:
        raise YkAdmitError(
            GURU_ENVELOPE,
            f"{rc.queue} at cap {rc.max_applications}: {live}; "
            f"proposed {proposed}. Each host process has one sentinel; "
            "retire the finished Application before the next admit.",
        )
    return proposed


def release_kind(kind: str) -> None:
    """Retire this kind's standing sentinel only (ambient / thinking)."""
    k = kind.replace("_", "-")
    if k == "ambient":
        delete_flow_sentinel(AMBIENT_WORKLOAD_ID)
        return
    if k in ("thinking", "gaius-thinking"):
        delete_flow_sentinel(capability_workload_id("thinking"))
        return
    if k in ("optillm", "gaius-optillm"):
        delete_flow_sentinel(OPTILLM_WORKLOAD_ID)
        return
    if k in ("embedding", "gaius-embedding", "aperture", "colbert"):
        delete_flow_sentinel(EMBEDDING_WORKLOAD_ID)
        return
    log.warning(
        "release_kind(%s) is not a standing claim; "
        "delete_flow_sentinel(workload_id) for 1:1 STZ",
        kind,
    )


def ephemeral_claim(kind: str, proposed: str) -> str:
    """Admit ``proposed``. Caller must ``delete_flow_sentinel(id)`` when the
    host process ends (STZ). Do not ``release_kind`` — that is standing only.
    """
    wid = bind_workload_id(kind, proposed)
    apply_and_admit(wid, kind)
    return wid


def has_admitted_application() -> bool:
    """True if this engine holds any live admitted Application."""
    with _MU:
        return any(r.admitted for r in _ADMITTED.values())


def capability_workload_id(alias: str) -> str:
    """Stable Application id for a standing capability (C2/Yield key)."""
    return "gaius-" + str(alias or "").strip().replace("_", "-")


def gpu_start_allowed(workload_id: str) -> bool:
    """GPU start is 1:1 with this process's sentinel when federated."""
    if is_admitted(workload_id):
        return True
    if _pod_phase(workload_id) == "Running":
        return True
    return not federation_required()


def vllm_held_gpu_ids() -> set[int]:
    """Physical GPU indices in CUDA_VISIBLE_DEVICES of live ``vllm serve``."""
    held: set[int] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return held
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode()
        except OSError:
            continue
        if "vllm" not in cmdline or "serve" not in cmdline:
            continue
        try:
            env = (entry / "environ").read_bytes().split(b"\x00")
        except OSError:
            continue
        for item in env:
            if not item.startswith(b"CUDA_VISIBLE_DEVICES="):
                continue
            raw = item.split(b"=", 1)[1].decode(errors="replace")
            for part in raw.split(","):
                part = part.strip()
                if part.isdigit():
                    held.add(int(part))
    return held


def gpu_free_mib() -> dict[int, int]:
    """index → free MiB from nvidia-smi. Empty if the binary is missing."""
    if not shutil.which("nvidia-smi"):
        return {}
    r = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if r.returncode != 0:
        return {}
    out: dict[int, int] = {}
    for line in (r.stdout or "").splitlines():
        if "," not in line:
            continue
        idx_s, mib_s = line.split(",", 1)
        try:
            out[int(idx_s.strip())] = int(float(mib_s.strip()))
        except ValueError:
            continue
    return out


async def apply_and_admit_async(workload_id: str, kind: str, **kw) -> AdmittedApplication:
    """``apply_and_admit`` off the event loop.

    The admit path is synchronous by design (kubectl + RequestQueueShare +
    ``time.sleep`` polls) and can legitimately wait GPU_ADMIT_TIMEOUT_S (600s)
    for a token. Called directly from an async handler it BLOCKS the engine's
    event loop for that long — Status hits DEADLINE, WatchWorkload drops, the
    httpx client stops reading and back-pressures optillm and vLLM's single
    uvicorn worker until thinking's /health "hangs" (observed 2026-08-30 16:15,
    a 10-minute engine freeze). Every async caller must use this wrapper.
    """
    import asyncio

    return await asyncio.to_thread(apply_and_admit, workload_id, kind, **kw)


async def delete_flow_sentinel_async(workload_id: str) -> None:
    """``delete_flow_sentinel`` (kubectl delete) off the event loop."""
    import asyncio

    await asyncio.to_thread(delete_flow_sentinel, workload_id)


def ensure_embedding_claim() -> None:
    """Admit ``gaius-embedding`` before any ColBERT CUDA load."""
    if federation_required():
        apply_and_admit(EMBEDDING_WORKLOAD_ID, "embedding")
    if not gpu_start_allowed(EMBEDDING_WORKLOAD_ID):
        raise YkAdmitError(
            GURU_NOAPP,
            f"ColBERT/Aperture CUDA requires admitted Application "
            f"{EMBEDDING_WORKLOAD_ID} on {LIGHT.queue} "
            "(ColBERT-Zero is a 1-GPU / light model). "
            "In-process CUDA without that profile is Metaflow debt.",
        )


_pinned_light_device: str | None = None


def reset_light_device_pin() -> None:
    """Tests only — next placement may pick again."""
    global _pinned_light_device
    _pinned_light_device = None


def embedding_cuda_device() -> str:
    """Map the light ColBERT claim onto one GPU and keep it."""
    global _pinned_light_device
    if _pinned_light_device:
        return _pinned_light_device
    ensure_embedding_claim()
    held = vllm_held_gpu_ids()
    free = gpu_free_mib()
    if free:
        for idx, mib in sorted(free.items()):
            if idx in held:
                continue
            if mib < LIGHT_MIN_FREE_MIB:
                continue
            _pinned_light_device = f"cuda:{idx}"
            return _pinned_light_device
        raise YkAdmitError(
            GURU_GPUCOLLIDE,
            "Aperture/ColBERT would land on a GPU another admitted WRK occupies. "
            f"vLLM holds {sorted(held) or 'none'}; free MiB={free}. "
            "ColBERT-Zero is light (1 GPU). Admit that profile or Yield "
            "the occupant. Do not steal another WRK's cards.",
        )
    try:
        import torch

        n = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
    except Exception:
        n = 0
    if n == 0:
        if federation_required():
            raise YkAdmitError(
                GURU_GPUCOLLIDE,
                "embedding Application admitted but CUDA is unavailable",
            )
        _pinned_light_device = "cpu"
        return _pinned_light_device
    for i in range(n):
        if i not in held:
            _pinned_light_device = f"cuda:{i}"
            return _pinned_light_device
    raise YkAdmitError(
        GURU_GPUCOLLIDE,
        f"Aperture/ColBERT collided with vLLM GPUs {sorted(held)}. "
        "Embedding's claim is not mapped to a free card; refuse stealing.",
    )


def _pod_phase(workload_id: str) -> str:
    if not shutil.which("kubectl"):
        return ""
    r = subprocess.run(
        [
            "kubectl",
            "-n",
            _NS,
            "get",
            "pod",
            workload_id,
            "-o",
            "jsonpath={.status.phase}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return (r.stdout or "").strip()


def _wait_running(workload_id: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = subprocess.run(
            [
                "kubectl",
                "-n",
                _NS,
                "get",
                "pod",
                workload_id,
                "-o",
                "jsonpath={.status.phase}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        phase = (r.stdout or "").strip()
        if phase == "Running":
            return True
        node = subprocess.run(
            [
                "kubectl",
                "-n",
                _NS,
                "get",
                "pod",
                workload_id,
                "-o",
                "jsonpath={.spec.nodeName}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # YK bind is admission. Image pull is not a queue reject.
        if (node.stdout or "").strip() and phase in {"Pending", "Running"}:
            return True
        if phase in {"Failed", "Succeeded", "Unknown"} and r.returncode == 0:
            return False
        time.sleep(1.5)
    return False
