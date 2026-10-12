"""Who holds each GPU, and which holders an admitted mix must replace.

Signals admits one GPU deployment for a workload. The cards that
deployment uses are all-in: the model already on the card comes down,
and the admitted mix is what loads. Two models do not share a GPU.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Pinned by config/supervision/gaius.textproto. A d3_server on one of
# these cards is that replica; any other card is a stray d3 process.
_D3_GPU_TO_REPLICA = {5: "d3-flash-0", 4: "d3-flash-1"}
_SHARE_FLOOR_MIB = 100


class GpuStillShared(RuntimeError):
    """The card still has another model's memory, so the new mix must not load."""


@dataclass(frozen=True)
class GpuOccupant:
    gpu: int
    pid: int
    memory_mib: int
    command: str
    workload: str


def classify_workload(command: str, *, gpu: int, pid: int) -> str:
    """Name the model a compute process is serving.

    ``resident-<pid>`` is a process that is not part of a known mix.
    It still occupies the card.
    """
    text = command.replace("\x00", " ").lower()
    if "clt_worker" in text:
        return "clt"
    if "d3_server.py" in text:
        return _D3_GPU_TO_REPLICA.get(int(gpu), "d3")
    if "vllm" in text:
        return "thinking"
    return f"resident-{pid}"


def read_cmdline(pid: int) -> str:
    try:
        raw = open(f"/proc/{pid}/cmdline", "rb").read()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace")


def _is_engine(command: str) -> bool:
    """The engine process itself. Never a yield target."""
    text = command.replace("\x00", " ")
    if "clt_worker" in text or "d3_server.py" in text:
        return False
    return "-m gaius.engine" in text


def list_occupants(query=None, command_of=None) -> list[GpuOccupant]:
    """Compute processes currently holding GPU memory."""
    if query is None:
        from gaius.engine.resources.reconciliation import _query_nvidia_smi_processes

        query = _query_nvidia_smi_processes
    if command_of is None:
        command_of = read_cmdline
    found: list[GpuOccupant] = []
    info = query() or {}
    for gpu, row in sorted(info.items(), key=lambda item: int(item[0])):
        for proc in row.get("processes") or []:
            try:
                pid = int(proc["pid"])
                memory = int(proc.get("memory_mb") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            name = str(proc.get("name") or "")
            command = f"{command_of(pid)} {name}".strip()
            found.append(
                GpuOccupant(
                    gpu=int(gpu),
                    pid=pid,
                    memory_mib=memory,
                    command=command,
                    workload=classify_workload(command, gpu=int(gpu), pid=pid),
                )
            )
    return found


def occupants_to_yield(
    occupants: list[GpuOccupant],
    *,
    keep: set[str],
) -> list[GpuOccupant]:
    """Holders that are not part of the mix about to own the card."""
    return [
        occ
        for occ in occupants
        if occ.workload not in keep and occ.memory_mib > _SHARE_FLOOR_MIB
    ]


def scheduling_tasks_for(occupants: list[GpuOccupant], *, already: set[str]):
    """Current-mix tasks the scheduler can stop.

    One task per workload. Resident pids stay out of this list: restoring
    them after the workload would try to start a dead process. The exclusive
    prepare step still takes them off the card.
    """
    from gaius.engine.scheduling import SchedulingTask

    grouped: dict[str, list[GpuOccupant]] = {}
    for occ in occupants_to_yield(occupants, keep=set()):
        if occ.workload in already or occ.workload.startswith("resident-"):
            continue
        grouped.setdefault(occ.workload, []).append(occ)
    tasks = []
    for name, rows in grouped.items():
        gpus = sorted({row.gpu for row in rows})
        tasks.append(
            SchedulingTask(
                task_id=name,
                endpoint_name=name,
                model_id=(rows[0].command[:160] or name),
                required_gpus=len(gpus),
                capability=name,
                prefer_contiguous=len(gpus) > 1,
                fixed_gpu_ids=gpus,
                is_current=True,
                memory_mb=sum(row.memory_mib for row in rows),
            )
        )
    return tasks


def terminate_occupant(pid: int, *, timeout_s: float = 8.0) -> None:
    """Stop one model process. Never the engine, never its process group."""
    if pid <= 1 or pid == os.getpid():
        raise RuntimeError(f"refusing to signal pid {pid}")
    command = read_cmdline(pid)
    if _is_engine(command):
        raise RuntimeError(f"refusing to signal the engine pid {pid}")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def prepare_exclusive_gpu(
    gpu: int,
    *,
    owner: str,
    list_fn=None,
    stop_clt=None,
    release_inprocess=None,
    terminate=None,
    sleep=None,
    timeout_s: float = 45.0,
) -> list[GpuOccupant]:
    """Take every other model off ``gpu`` before ``owner`` loads.

    Thinking is part of the decisions mix and stays on its own cards.
    Finding it on this card refuses the load. CLT and any other resident
    model are stopped, and the call waits until their memory is gone.
    """
    if list_fn is None:
        list_fn = list_occupants
    if terminate is None:
        terminate = terminate_occupant
    if sleep is None:
        sleep = time.sleep

    def blockers() -> list[GpuOccupant]:
        return [
            occ
            for occ in list_fn()
            if occ.gpu == int(gpu)
            and occ.workload != owner
            and occ.memory_mib > _SHARE_FLOOR_MIB
        ]

    victims = blockers()
    if not victims:
        return []
    if any(occ.workload == "thinking" for occ in victims):
        raise GpuStillShared(
            f"GPU {gpu} is held by thinking. {owner} does not share a card."
        )
    logger.info(
        "%s takes GPU %s whole; yielding %s",
        owner,
        gpu,
        [(occ.workload, occ.pid, occ.memory_mib) for occ in victims],
    )
    if any(occ.workload == "clt" for occ in victims):
        if stop_clt is None:
            from gaius.engine.services.clt_service import stop_resident_clt_workers

            stop_clt = stop_resident_clt_workers
        stop_clt()
    engine_pids = {os.getpid()}
    for occ in victims:
        if occ.workload == "clt":
            continue
        if occ.pid in engine_pids or _is_engine(occ.command):
            if release_inprocess is None:
                release_inprocess = _release_inprocess_models
            release_inprocess()
            continue
        terminate(occ.pid)

    deadline = time.monotonic() + timeout_s
    left = blockers()
    while left and time.monotonic() < deadline:
        sleep(0.5)
        left = blockers()
    if left:
        detail = ", ".join(
            f"{occ.workload} pid={occ.pid} {occ.memory_mib}MiB" for occ in left
        )
        raise GpuStillShared(
            f"GPU {gpu} still held after yield ({detail}). "
            f"{owner} will not load beside another model."
        )
    return victims


def _release_inprocess_models() -> None:
    try:
        from gaius.engine.embeddings.colbert import release_colbert_embedder

        release_colbert_embedder()
    except Exception as exc:  # noqa: BLE001 — the retry below is the check
        logger.warning("in-process model release failed: %s", exc)
