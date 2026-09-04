"""WRK occupancy intent for Scheduler/RequestQueueShare."""

from __future__ import annotations

import uuid
from concurrent import futures
from pathlib import Path

import grpc
import pytest

from gaius.engine.queue_share import (
    GURU_SHAREFAIL,
    GPU_KEY,
    PEER,
    leaf_for_gpu_tokens,
    list_queue_share_requests,
    mint_uuid7,
    notify_admit,
    notify_release,
    request_queue_share,
    request_queue_share_end,
    require_uuid7,
    share_for_class,
)
from gaius.engine.s2s import declared_queues, declared_workloads, local_response
from gaius.engine.sentinel_claim import COMPUTE, EXTRACT, HEAVY, LIGHT, MEDIUM
from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spbg


def test_uuidv7_required_never_v4() -> None:
    s = mint_uuid7()
    u = uuid.UUID(s)
    assert u.version == 7
    assert require_uuid7(s) == s
    with pytest.raises(RuntimeError, match=r"UUIDv7"):
        require_uuid7("")
    with pytest.raises(RuntimeError, match=r"not v4"):
        require_uuid7(str(uuid.uuid4()))


def test_share_mints_uuidv7_every_request() -> None:
    a = share_for_class("article-curate", EXTRACT)
    b = share_for_class("article-curate", EXTRACT)
    assert uuid.UUID(a.request_id).version == 7
    assert uuid.UUID(b.request_id).version == 7
    assert a.request_id != b.request_id


def test_leaf_from_gpu_tokens_not_queue_name() -> None:
    assert leaf_for_gpu_tokens(4) is HEAVY
    assert leaf_for_gpu_tokens(2) is MEDIUM
    assert leaf_for_gpu_tokens(1) is LIGHT
    assert leaf_for_gpu_tokens(0) is COMPUTE
    assert leaf_for_gpu_tokens(1, offline=True) is EXTRACT
    req = share_for_class("thinking", leaf_for_gpu_tokens(4))
    assert req.shares[0].queue == HEAVY.queue
    assert "qwen" not in req.shares[0].queue.lower()
    assert "tp" not in req.shares[0].queue


def test_extract_share_requests_gpu_floor_1() -> None:
    req = share_for_class("article-curate", EXTRACT)
    assert req.peer == PEER
    assert req.workloads[0].wrk == "article-curate"
    assert req.workloads[0].queue == EXTRACT.queue
    assert req.shares[0].guaranteed.quantities[GPU_KEY] == 1
    assert req.shares[0].max.quantities[GPU_KEY] == 2


def test_zero_floor_valid_until_on_end() -> None:
    req = share_for_class(
        "thinking", HEAVY, gpu=0, valid_until_ns=123, supersedes_request_id="x", applications=0
    )
    assert req.shares[0].guaranteed.quantities[GPU_KEY] == 0
    assert req.valid_until_ns == 123
    assert req.workloads[0].applications == 0
    assert req.supersedes_request_id == "x"
    assert uuid.UUID(req.request_id).version == 7


def test_workloads_not_in_queue_name() -> None:
    # declared_workloads() returns zndx.engine.v1.WorkloadOffer since the
    # 2026-08-31 redesign (model + capabilities + typed requirements); the
    # old hint fields (wrk / gpu_tokens / tensor_parallel) are gone.
    offers = declared_workloads()
    assert offers
    thinking = next(
        o for o in offers if o.requirements.parallelism.tensor_parallel == 4
    )
    assert thinking.requirements.footprint.gpu == 4
    proxy = next(o for o in offers if o.model == "proxy")
    assert proxy.requirements.footprint.gpu == 0
    for o in offers:
        assert "root.internal" not in o.model
        assert not o.queue or o.queue.startswith("root.")
    q = local_response(zpb.SERVER_QUERY_KIND_WORKLOADS, object())
    assert [(w.model, w.queue) for w in q.workloads] == [(o.model, o.queue) for o in offers]


def test_queue_hint_is_declared_shape() -> None:
    paths = {h.path for h in declared_queues()}
    assert HEAVY.queue in paths
    assert EXTRACT.queue in paths
    for h in declared_queues():
        assert "Qwen" not in h.path
        assert "tp" not in h.path


def test_module_never_writes_queues_yaml() -> None:
    src = Path("src/gaius/engine/queue_share.py").read_text()
    assert "do not write queues.yaml" in src
    assert "open(" not in src
    assert "write_text" not in src


def _serve(servicer) -> tuple[grpc.Server, str]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    spbg.add_SchedulerServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, f"127.0.0.1:{port}"


def test_unimplemented_is_signals_not_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    server, addr = _serve(spbg.SchedulerServicer())
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", addr)
    try:
        assert request_queue_share("article-curate", EXTRACT) is False
        assert list_queue_share_requests() == []
    finally:
        server.stop(grace=0)


class _Reject(spbg.SchedulerServicer):
    def RequestQueueShare(self, request, context):
        return spb.QueueShareResponse(
            accepted=False,
            request_id=request.request_id,
            state=spb.QUEUE_SHARE_REJECTED,
            error="over parent max",
        )


def test_rejected_does_not_admit(monkeypatch: pytest.MonkeyPatch) -> None:
    server, addr = _serve(_Reject())
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", addr)
    try:
        with pytest.raises(RuntimeError, match=r"#YK\.00000007\.SHAREFAIL"):
            request_queue_share("thinking", HEAVY)
        with pytest.raises(RuntimeError, match="SHAREFAIL"):
            notify_admit("thinking", HEAVY)
    finally:
        server.stop(grace=0)


class _RejectSilent(spbg.SchedulerServicer):
    def RequestQueueShare(self, request, context):
        return spb.QueueShareResponse(
            accepted=False,
            request_id=request.request_id,
            state=spb.QUEUE_SHARE_REJECTED,
        )


def test_rejected_without_error_still_blocks_admit(monkeypatch: pytest.MonkeyPatch) -> None:
    server, addr = _serve(_RejectSilent())
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", addr)
    try:
        with pytest.raises(RuntimeError, match=r"REJECTED"):
            notify_admit("thinking", HEAVY)
    finally:
        server.stop(grace=0)


class _Unavailable(spbg.SchedulerServicer):
    def RequestQueueShare(self, request, context):
        context.abort(grpc.StatusCode.UNAVAILABLE, "engine down")

    def ListQueueShareRequests(self, request, context):
        context.abort(grpc.StatusCode.UNAVAILABLE, "engine down")


def test_unavailable_does_not_kill_admit(monkeypatch: pytest.MonkeyPatch) -> None:
    server, addr = _serve(_Unavailable())
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", addr)
    try:
        assert request_queue_share("thinking", HEAVY) is False
        assert list_queue_share_requests() == []
        assert notify_admit("optillm", COMPUTE) is False
    finally:
        server.stop(grace=0)


class _Internal(spbg.SchedulerServicer):
    def RequestQueueShare(self, request, context):
        context.abort(grpc.StatusCode.INTERNAL, "persist boom")


def test_internal_grpc_error_is_sharefail(monkeypatch: pytest.MonkeyPatch) -> None:
    server, addr = _serve(_Internal())
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", addr)
    try:
        with pytest.raises(RuntimeError, match=r"#YK\.00000007\.SHAREFAIL"):
            request_queue_share("thinking", HEAVY)
    finally:
        server.stop(grace=0)


class _Record(spbg.SchedulerServicer):
    def __init__(self) -> None:
        self.seen = []

    def RequestQueueShare(self, request, context):
        self.seen.append(request)
        return spb.QueueShareResponse(
            accepted=True,
            request_id=request.request_id,
            state=spb.QUEUE_SHARE_RECORDED,
        )

    def ListQueueShareRequests(self, request, context):
        # The real applier moves RECORDED -> APPLYING -> APPLIED; the client's
        # wait is progress-based (no deadline short of the 600 s net), so the
        # stub must report the terminal state or the test outlives its budget.
        recs = [
            spb.QueueShareRecord(
                request=r,
                recorded_at_ns=1,
                state=spb.QUEUE_SHARE_APPLIED,
                applied_at_ns=2,
                apply_ms=1,
            )
            for r in self.seen
        ]
        return spb.ListQueueShareRequestsResponse(records=recs)


def test_admit_then_zero_floor_end(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _Record()
    server, addr = _serve(svc)
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", addr)
    try:
        assert notify_admit("article-curate", EXTRACT) is True
        assert notify_release("article-curate", EXTRACT) is True
        assert len(svc.seen) == 2
        admit, end = svc.seen
        assert uuid.UUID(admit.request_id).version == 7
        assert uuid.UUID(end.request_id).version == 7
        assert admit.request_id != end.request_id
        assert end.supersedes_request_id == admit.request_id
        assert end.shares[0].guaranteed.quantities[GPU_KEY] == 0
        assert end.valid_until_ns > 0
        assert end.workloads[0].applications == 0
        recs = list_queue_share_requests()
        assert len(recs) == 2
    finally:
        server.stop(grace=0)
