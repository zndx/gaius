"""YK Application claim for a spawned Gaius flow.

Queue path is the resource class. Project is identity only
(``federation.project=gaius``). There is no ``root.gaius``.

The Application is the Yield victim: YK preempt → C2 last-gasp :50561 →
``zndx.engine.v1.Engine/Yield`` on :50051. Host GPU occupancy is
``federation.zndx.org/gpu`` only — never ``nvidia.com/gpu`` on this
CPU-only sentinel (that would bind the card into an empty pod).

Signals / YK shows three Gaius lanes on existing leaves (no
``root.gaius``):

- ``external.rate-metered`` — FMP ingest. Comes and goes.
- ``internal.compute`` — Ambient RAM FIFO. Standing while the daemon
  runs. Never a disk write.
- ``internal.inference.extract`` — one GPU token. Article/prospects
  GPU children and agentic summarization bind this id.

Host disk and RAM are not YK resources — Gaius refuses new disk-writing
children when those floors are crossed so the box cannot fill past the
physical lid. Ambient (compute) skips the disk floor.

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

# Tinybox physical: federation.zndx.org/gpu=6, ~128Gi RAM. Gaius survey
# takes one token so Ægir/Atelier keep the other inference leaves.
# YK sees apps/gpu/cpu/mem on the pause claim. Disk and host RAM are
# Gaius floors — YK cannot cap host Metaflow / Postgres / KB writes.
ENVELOPE_MAX_APPS = 1
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


EXTRACT = ResourceClass(
    name="internal.inference.extract",
    queue="root.internal.inference.extract",
    gpu_tokens=ENVELOPE_GPU,
)

# One-GPU interactive Ask (each 1.7B replica). Not extract. Not SAE.
LIGHT = ResourceClass(
    name="internal.inference.light",
    queue="root.internal.inference.light",
    gpu_tokens=1,
)

# Two-GPU interactive Ask (9B SAE TP=2). Light must not land here.
MEDIUM = ResourceClass(
    name="internal.inference.medium",
    queue="root.internal.inference.medium",
    gpu_tokens=2,
)

# Standing thinking / large TP. Light/medium never preempt this leaf.
HEAVY = ResourceClass(
    name="internal.inference.heavy",
    queue="root.internal.inference.heavy",
    gpu_tokens=4,
)

# FMP / RPM APIs: no GPU. Application is deleted when the check ends.
RATE_METERED = ResourceClass(
    name="external.rate-metered",
    queue="root.external.rate-metered",
    gpu_tokens=0,
)

# Ambient RAM buffer: no GPU, no disk. Standing while the daemon runs.
COMPUTE = ResourceClass(
    name="internal.compute",
    queue="root.internal.compute",
    gpu_tokens=0,
)

AMBIENT_WORKLOAD_ID = "gaius-ambient"

# GPU summarization (docling / VLM / instruct) always binds EXTRACT.
# FMP ingest and Ambient buffer are other queues so YK can show them.
_KIND_CLASS: dict[str, ResourceClass] = {
    "article-curate": EXTRACT,
    "article_curate": EXTRACT,
    "prospects-update": EXTRACT,
    "prospects_update": EXTRACT,
    # Compact/summary ride the standing extract token (same envelope as
    # ambient-summarize). They must not mint a second GPU Application.
    "prospects-compact": EXTRACT,
    "prospects_compact": EXTRACT,
    "prospects-summary": EXTRACT,
    "prospects_summary": EXTRACT,
    "ambient-summarize": EXTRACT,
    "ambient_summarize": EXTRACT,
    # Planned RAM→sitrep compaction: same extract token as summarize
    # so Aegir fine-tune preempts one GPU claim, not two.
    "ambient-compact": EXTRACT,
    "ambient_compact": EXTRACT,
    "prospects-check": RATE_METERED,
    "prospects_check": RATE_METERED,
    "fmp": RATE_METERED,
    "ambient": COMPUTE,
    # Ask 1.7B: one whole GPU per replica (light).
    "ask-agent": LIGHT,
    "ask_agent": LIGHT,
    "ask-light": LIGHT,
    # Ask SAE 9B: two whole GPUs, medium leaf only.
    "ask-sae": MEDIUM,
    "ask_sae": MEDIUM,
    "ask-medium": MEDIUM,
    # Live YK has extract, not light yet (light is in Signals yaml, not
    # loaded). Probe is offline batch — extract is the existing 1-GPU leaf.
    "clt-probe": EXTRACT,
    "clt_probe": EXTRACT,
    "clt-skos-admit": EXTRACT,
    "clt_skos_admit": EXTRACT,
    # Label uses standing thinking Complete — no extra GPU token.
    "clt-skos-label": COMPUTE,
    "clt_skos_label": COMPUTE,
}


def resource_class_for(kind: str) -> ResourceClass:
    try:
        return _KIND_CLASS[kind]
    except KeyError as e:
        raise YkAdmitError(
            GURU_NOADMIT,
            f"no resource class for kind={kind!r}; "
            "light: ask-agent (1 GPU); medium: ask-sae (2 GPU); "
            "extract (offline): article_curate / prospects_update / …; "
            "rate-metered: prospects-check / fmp; compute: ambient",
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


# Phase is what YK/operators see: buffer is CPU+RAM only; summarize
# and compact borrow the one extract GPU token (Aegir fine-tune preempts
# that token — they must not mint a second).
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
    return n < ENVELOPE_MAX_APPS


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
    if rc.queue == COMPUTE.queue:
        return ()
    if rc.queue == RATE_METERED.queue:
        return ("/raid",)
    if kind.replace("_", "-").startswith("prospects-"):
        return ("/raid",)
    if kind.replace("_", "-") == "clt-probe":
        # Tape is Postgres. Root 99% must not block understanding.
        return ("/raid",)
    if kind.replace("_", "-") == "article-curate":
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
    timeout_s: float = 60.0,
) -> AdmittedApplication:
    """Apply the Application and wait until the pod is Running (YK admitted)."""
    rc = resource_class_for(kind)
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
        # Do not delete: YK may already have placed this app-id. Killing the
        # claim pod here is "delete at host-flow start" and 404s extract.
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
        _ADMITTED.pop(workload_id, None)
    _delete_pod(workload_id)


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
            "-o",
            "jsonpath={.items[*].metadata.name}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return [n for n in (r.stdout or "").split() if n]


def live_workload_id(kind: str) -> str | None:
    """Return the live Gaius Application on this kind's queue (envelope: one)."""
    rc = resource_class_for(kind)
    names: list[str] = []
    with _MU:
        for row in _ADMITTED.values():
            if row.admitted and row.resource_class.queue == rc.queue:
                names.append(row.workload_id)
    names.extend(_cluster_gaius_app_ids(rc.queue))
    uniq = list(dict.fromkeys(names))
    if len(uniq) > ENVELOPE_MAX_APPS:
        cap = (
            f"{ENVELOPE_MAX_APPS} app / {ENVELOPE_GPU} GPU"
            if rc.gpu_tokens
            else f"{ENVELOPE_MAX_APPS} app (no GPU)"
        )
        raise YkAdmitError(
            GURU_ENVELOPE,
            f"{len(uniq)} Gaius Applications on {rc.queue}: {uniq}; "
            f"envelope cap is {cap}",
        )
    return uniq[0] if uniq else None


def bind_workload_id(kind: str, proposed: str) -> str:
    """Reuse the live Application on this kind's queue (one app per leaf)."""
    live = live_workload_id(kind)
    if live:
        log.info("reusing live Application %s for kind=%s (not %s)", live, kind, proposed)
        return live
    return proposed


def release_kind(kind: str) -> None:
    """Complete the live Application on this kind's queue (FMP / Ambient stop)."""
    live = live_workload_id(kind)
    if live:
        delete_flow_sentinel(live)


def ephemeral_claim(kind: str, proposed: str) -> str:
    """Admit, return the id. Caller must ``release_kind`` in ``finally``.

    FMP uses this so the rate-metered row comes and goes.
    """
    wid = bind_workload_id(kind, proposed)
    apply_and_admit(wid, kind)
    return wid


def has_admitted_application() -> bool:
    """True if this engine holds any live admitted Application."""
    with _MU:
        return any(r.admitted for r in _ADMITTED.values())


def gpu_start_allowed(workload_id: str) -> bool:
    """Exclusive GPU start requires a live admitted Application when federated."""
    if is_admitted(workload_id):
        return True
    if has_admitted_application():
        # Nested BeginWorkload (render / extract) rides the parent Application.
        return True
    return not federation_required()


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
