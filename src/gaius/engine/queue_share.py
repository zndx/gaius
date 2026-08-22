"""Request YK queue guarantee floors over zndx.scheduler.v1.

WRK (optillm, Metaflow extract, thinking, CLT/SAE) occupies a resource-class
leaf. Guarantees must move over time so YK preemption can fire. Signals
records RequestQueueShare; applying queues.yaml is Signals later.
UNIMPLEMENTED means Signals is behind the proto — admit still proceeds.
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


def _request_id() -> str:
    gen = getattr(uuid, "uuid7", None)
    return str(gen() if callable(gen) else uuid.uuid4())


def _addr() -> str:
    return (
        os.environ.get("SIGNALS_ENGINE_GRPC")
        or os.environ.get("SIGNALS_ENGINE_TARGET")
        or "127.0.0.1:50551"
    )


def share_for_class(kind: str, rc: ResourceClass) -> object:
    """Build a QueueShareRequest for one WRK occupying ``rc``."""
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb

    gpu = int(rc.gpu_tokens)
    max_gpu = gpu if gpu >= 2 else (2 if gpu else 0)
    share = spb.QueueShare(
        queue=rc.queue,
        guaranteed=spb.ResourceMap(quantities={GPU_KEY: gpu}),
        max=spb.ResourceMap(quantities={GPU_KEY: max_gpu}),
        max_applications=int(rc.max_applications),
    )
    wrk = spb.WorkloadIntent(
        wrk=kind.replace("_", "-"),
        queue=rc.queue,
        resource_class=rc.name,
        applications=1,
    )
    return spb.QueueShareRequest(
        peer=PEER,
        request_id=_request_id(),
        valid_from_ns=time.time_ns(),
        reason=f"{kind} occupies {rc.queue} (guarantee gpu={gpu})",
        workloads=[wrk],
        shares=[share],
    )


def request_queue_share(kind: str, rc: ResourceClass) -> bool:
    """Tell Signals the occupancy intent. True if recorded.

    ``UNIMPLEMENTED``: proto is ahead of Signals — log, do not fail admit.
    Any other gRPC error: fail-fast SHAREFAIL.
    """
    import grpc

    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

    req = share_for_class(kind, rc)
    channel = grpc.insecure_channel(_addr())
    try:
        stub = spb_grpc.SchedulerStub(channel)
        resp = stub.RequestQueueShare(req, timeout=5.0)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            log.info(
                "RequestQueueShare UNIMPLEMENTED (Signals behind proto) wrk=%s queue=%s",
                kind,
                rc.queue,
            )
            return False
        raise RuntimeError(
            f"{GURU_SHAREFAIL} RequestQueueShare failed: {e.code()} {e.details()}\n"
            "  Signals Scheduler on SIGNALS_ENGINE_TARGET; do not write queues.yaml"
        ) from e
    finally:
        channel.close()
    if not resp.accepted and (resp.error or "").strip():
        raise RuntimeError(
            f"{GURU_SHAREFAIL} {resp.error}\n"
            "  Signals Scheduler on SIGNALS_ENGINE_TARGET; do not write queues.yaml"
        )
    log.info(
        "RequestQueueShare accepted=%s state=%s wrk=%s queue=%s id=%s",
        resp.accepted,
        resp.state,
        kind,
        rc.queue,
        resp.request_id or req.request_id,
    )
    return bool(resp.accepted)
