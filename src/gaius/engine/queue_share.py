"""Request YK queue guarantee floors over zndx.scheduler.v1.

WRK occupies a resource-class leaf. Guarantees move over time so YK
preemption can fire. Signals records RequestQueueShare; applying
queues.yaml is Signals later. UNIMPLEMENTED: proto ahead of Signals —
admit proceeds. REJECTED: do not admit.

Every QueueShareRequest mints RFC 9562 UUIDv7 (required; never omit,
never v4). Admit sends occupancy; WRK end sends zero-floor with
valid_until_ns and supersedes_request_id. Pick heavy/medium/light from
gpu_tokens; never put model/tp/pp in the queue name.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.engine.sentinel_claim import ResourceClass

log = logging.getLogger("gaius.engine.queue_share")

GURU_SHAREFAIL = "#YK.00000007.SHAREFAIL"
GPU_KEY = "federation.zndx.org/gpu"
PEER = "gaius"

_ADMIT_IDS: dict[str, str] = {}


def mint_uuid7() -> str:
    """RFC 9562 UUIDv7. Required on every RequestQueueShare — never omit, never v4."""
    gen = getattr(uuid, "uuid7", None)
    if callable(gen):
        u = gen()
    else:
        ts_ms = time.time_ns() // 1_000_000
        ts_ms &= (1 << 48) - 1
        rnd = int.from_bytes(os.urandom(10), "big")
        rand_a = (rnd >> 62) & 0xFFF
        rand_b = rnd & ((1 << 62) - 1)
        u = uuid.UUID(int=(ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b)
    if u.version != 7:
        raise RuntimeError(
            f"{GURU_SHAREFAIL} request_id must be RFC 9562 UUIDv7, got v{u.version}"
        )
    return str(u)


def require_uuid7(value: str) -> str:
    s = (value or "").strip()
    if not s:
        raise RuntimeError(
            f"{GURU_SHAREFAIL} request_id omitted; RFC 9562 UUIDv7 required"
        )
    try:
        u = uuid.UUID(s)
    except ValueError as e:
        raise RuntimeError(
            f"{GURU_SHAREFAIL} request_id is not a UUID: {s!r}"
        ) from e
    if u.version != 7:
        raise RuntimeError(
            f"{GURU_SHAREFAIL} request_id must be RFC 9562 UUIDv7, not v{u.version}"
        )
    return s


def leaf_for_gpu_tokens(n: int, *, offline: bool = False) -> ResourceClass:
    """heavy/medium/light from GPU requirement; extract if offline; compute if 0."""
    from gaius.engine.sentinel_claim import COMPUTE, EXTRACT, HEAVY, LIGHT, MEDIUM

    tokens = int(n)
    if tokens <= 0:
        return COMPUTE
    if offline:
        return EXTRACT
    if tokens >= 4:
        return HEAVY
    if tokens >= 2:
        return MEDIUM
    return LIGHT


def _addr() -> str:
    return (
        os.environ.get("SIGNALS_ENGINE_GRPC")
        or os.environ.get("SIGNALS_ENGINE_TARGET")
        or "127.0.0.1:50551"
    )


def share_for_class(
    kind: str,
    rc: ResourceClass,
    *,
    gpu: int | None = None,
    valid_until_ns: int = 0,
    supersedes_request_id: str = "",
    applications: int | None = None,
) -> object:
    """Build a QueueShareRequest. Always mints a new UUIDv7."""
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb

    tokens = int(rc.gpu_tokens if gpu is None else gpu)
    max_gpu = int(rc.gpu_tokens) if int(rc.gpu_tokens) >= 2 else (2 if int(rc.gpu_tokens) else 0)
    apps = 0 if tokens == 0 else (1 if applications is None else int(applications))
    share = spb.QueueShare(
        queue=rc.queue,
        guaranteed=spb.ResourceMap(quantities={GPU_KEY: tokens}),
        max=spb.ResourceMap(quantities={GPU_KEY: max_gpu}),
        max_applications=int(rc.max_applications),
    )
    wrk = spb.WorkloadIntent(
        wrk=kind.replace("_", "-"),
        queue=rc.queue,
        resource_class=rc.name,
        applications=apps,
    )
    return spb.QueueShareRequest(
        peer=PEER,
        request_id=mint_uuid7(),
        valid_from_ns=time.time_ns(),
        valid_until_ns=int(valid_until_ns),
        reason=(
            f"{kind} ended on {rc.queue} (zero floor)"
            if tokens == 0
            else f"{kind} occupies {rc.queue} (guarantee gpu={tokens})"
        ),
        supersedes_request_id=supersedes_request_id,
        workloads=[wrk],
        shares=[share],
    )


def _send(req) -> object:
    import grpc

    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

    require_uuid7(req.request_id)
    channel = grpc.insecure_channel(_addr())
    try:
        stub = spb_grpc.SchedulerStub(channel)
        resp = stub.RequestQueueShare(req, timeout=5.0)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            log.info(
                "RequestQueueShare UNIMPLEMENTED (Signals behind proto) wrk=%s queue=%s",
                req.workloads[0].wrk if req.workloads else "",
                req.shares[0].queue if req.shares else "",
            )
            return None
        raise RuntimeError(
            f"{GURU_SHAREFAIL} RequestQueueShare failed: {e.code()} {e.details()}\n"
            "  Signals Scheduler on SIGNALS_ENGINE_TARGET; do not write queues.yaml"
        ) from e
    finally:
        channel.close()
    if resp.state == spb.QUEUE_SHARE_REJECTED:
        raise RuntimeError(
            f"{GURU_SHAREFAIL} {resp.error or 'REJECTED'}\n"
            "  Signals Scheduler on SIGNALS_ENGINE_TARGET; do not write queues.yaml"
        )
    if not resp.accepted and (resp.error or "").strip():
        raise RuntimeError(
            f"{GURU_SHAREFAIL} {resp.error}\n"
            "  Signals Scheduler on SIGNALS_ENGINE_TARGET; do not write queues.yaml"
        )
    log.info(
        "RequestQueueShare accepted=%s state=%s wrk=%s queue=%s id=%s",
        resp.accepted,
        resp.state,
        req.workloads[0].wrk if req.workloads else "",
        req.shares[0].queue if req.shares else "",
        resp.request_id or req.request_id,
    )
    return resp


def request_queue_share(kind: str, rc: ResourceClass) -> bool:
    """Tell Signals the occupancy intent. True if recorded.

    UNIMPLEMENTED: log, do not fail admit.
    REJECTED or persist error: fail-fast SHAREFAIL, do not admit.
    """
    req = share_for_class(kind, rc)
    resp = _send(req)
    if resp is None:
        return False
    _ADMIT_IDS[kind.replace("_", "-")] = req.request_id
    return bool(resp.accepted)


def request_queue_share_end(kind: str, rc: ResourceClass) -> bool:
    """Zero-floor occupancy and close the window when the WRK ends."""
    key = kind.replace("_", "-")
    prior = _ADMIT_IDS.pop(key, "")
    now = time.time_ns()
    req = share_for_class(
        kind,
        rc,
        gpu=0,
        valid_until_ns=now,
        supersedes_request_id=prior,
        applications=0,
    )
    resp = _send(req)
    return bool(resp and resp.accepted)


def list_queue_share_requests(
    *,
    peer: str = PEER,
    queue: str = "",
    since_ns: int = 0,
    limit: int = 0,
) -> list:
    import grpc

    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

    channel = grpc.insecure_channel(_addr())
    try:
        stub = spb_grpc.SchedulerStub(channel)
        resp = stub.ListQueueShareRequests(
            spb.ListQueueShareRequestsRequest(
                peer=peer, queue=queue, since_ns=since_ns, limit=limit
            ),
            timeout=5.0,
        )
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            log.info(
                "ListQueueShareRequests UNIMPLEMENTED (Signals behind proto) peer=%s",
                peer,
            )
            return []
        raise RuntimeError(
            f"{GURU_SHAREFAIL} ListQueueShareRequests failed: {e.code()} {e.details()}\n"
            "  Signals Scheduler on SIGNALS_ENGINE_TARGET; do not write queues.yaml"
        ) from e
    finally:
        channel.close()
    return list(resp.records)


def notify_admit(kind: str, rc: ResourceClass | None = None) -> bool:
    """Call RequestQueueShare when a WRK admits. REJECTED/SHAREFAIL fails fast."""
    from gaius.engine.sentinel_claim import EXTRACT, resource_class_for

    cls = rc if rc is not None else resource_class_for(kind)
    if cls.gpu_tokens and cls is not EXTRACT:
        cls = leaf_for_gpu_tokens(cls.gpu_tokens)
    try:
        return request_queue_share(kind, cls)
    except RuntimeError as e:
        if "SHAREFAIL" in str(e):
            raise
        log.warning("RequestQueueShare skipped: %s", e)
        return False
    except Exception as e:
        log.warning("RequestQueueShare skipped: %s", e)
        return False


def notify_release(kind: str, rc: ResourceClass | None = None) -> bool:
    """Zero-floor + valid_until when the WRK ends. Does not block local stop."""
    from gaius.engine.sentinel_claim import EXTRACT, resource_class_for

    cls = rc if rc is not None else resource_class_for(kind)
    if cls.gpu_tokens and cls is not EXTRACT:
        cls = leaf_for_gpu_tokens(cls.gpu_tokens)
    try:
        return request_queue_share_end(kind, cls)
    except RuntimeError as e:
        log.warning("RequestQueueShare end skipped: %s", e)
        return False
    except Exception as e:
        log.warning("RequestQueueShare end skipped: %s", e)
        return False
