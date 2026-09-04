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
    """light=1 GPU, medium=2 consecutive, heavy=4 consecutive; extract if offline."""
    from gaius.engine.sentinel_claim import class_for_gpu_tokens

    return class_for_gpu_tokens(n, offline=offline)


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
    floor: int | None = None,
    priority: int | None = None,
    owner: str | None = None,
    owner_id: str = "",
) -> object:
    """Build a QueueShareRequest. Always mints a new UUIDv7.

    ``floor``/``priority`` given → that declared intent rides the request
    (phase emission). Otherwise the supervision instance is consulted for
    (owner, kind); ``owner`` defaults to GAIUS_YK_KIND or ``kind``.
    ``owner_id`` is the DECLARER stamped on the wire (WorkloadIntent.owner):
    the run's workload id for phase emission, empty for a workload's own
    admission claim — the arbiter's supersession identity is
    (peer, queue, wrk, owner), so two declarers' intents for one shared
    workload coexist.
    """
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    tokens = int(rc.gpu_tokens if gpu is None else gpu)
    max_gpu = int(rc.gpu_tokens) if int(rc.gpu_tokens) >= 2 else (2 if int(rc.gpu_tokens) else 0)
    apps = 0 if tokens == 0 else (1 if applications is None else int(applications))
    _rc_enum = (
        zpb.RESOURCE_CLASS_COMPUTE if tokens <= 0
        else zpb.RESOURCE_CLASS_LIGHT if tokens == 1
        else zpb.RESOURCE_CLASS_MEDIUM if tokens == 2
        else zpb.RESOURCE_CLASS_HEAVY
    )
    share = spb.QueueShare(
        queue=rc.queue,
        guaranteed=spb.ResourceMap(quantities={GPU_KEY: tokens}),
        max=spb.ResourceMap(quantities={GPU_KEY: max_gpu}),
        max_applications=int(rc.max_applications),
    )
    wrk = spb.WorkloadIntent(
        wrk=kind.replace("_", "-"),
        queue=rc.queue,
        owner=(owner_id or "").strip(),
        resource_class=_rc_enum,
        applications=apps,
        requirements=zpb.WorkloadRequirements(
            backend=(
                zpb.SERVING_BACKEND_VLLM_LOCAL if tokens > 0
                else zpb.SERVING_BACKEND_CPU_PROXY
            ),
            footprint=zpb.ResourceFootprint(gpu=tokens),
        ),
    )
    # Declared intent (zndx.supervision.v1 ResourceIntent, config/supervision):
    # the FLOOR the arbiter must protect is what the spec says for this owner and
    # workload — not the tokens resident. The owner is the flow/task kind that
    # runs this process (GAIUS_YK_KIND in flow children), else the kind itself.
    # A legacy request (no intent declared) leaves `floor` ABSENT, so the arbiter
    # keeps footprint-derived protection for it.
    reason = (
        f"{kind} ended on {rc.queue} (zero floor)"
        if tokens == 0
        else f"{kind} occupies {rc.queue} (guarantee gpu={tokens})"
    )
    if tokens > 0:
        it = None
        if floor is None:
            try:
                from gaius.engine.supervision_spec import intent_for

                own = (owner or os.environ.get("GAIUS_YK_KIND") or kind).replace("_", "-")
                it = intent_for(own, kind)
            except Exception as e:  # noqa: BLE001 — spec problems are logged by the loader
                log.debug("intent lookup skipped for %s: %s", kind, e)
            if it is not None:
                floor, priority = int(it.floor), int(it.priority)
                origin = f"{it.owner}{'/' + it.phase if it.phase else ''}"
            else:
                origin = ""
        else:
            origin = f"{owner or 'phase'}"
        if floor is not None:
            fl = max(0, min(int(floor), tokens))
            share.guaranteed.quantities[GPU_KEY] = fl
            wrk.floor = fl
            wrk.priority = int(priority or 0)
            reason = (
                f"{kind} occupies {rc.queue}: declared floor gpu={fl} of {tokens} "
                f"priority={int(priority or 0)} ({origin})"
            )
            log.info("queue share intent %s: %s", kind, reason)
    return spb.QueueShareRequest(
        peer=PEER,
        request_id=mint_uuid7(),
        valid_from_ns=time.time_ns(),
        valid_until_ns=int(valid_until_ns),
        reason=reason,
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
        # Generous: the record is fast (apply is off the hot path server-side), but
        # YuniKorn ops legitimately take 3-5s; 1.5s was the 2026-08-26 false timeout.
        resp = stub.RequestQueueShare(req, timeout=8)
    except grpc.RpcError as e:
        # Signals has not implemented persist yet, or Scheduler is down.
        # Do not take down Engine/UI. REJECTED is the only hard no-admit.
        transient = (
            grpc.StatusCode.UNIMPLEMENTED,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.UNAVAILABLE,
        )
        if e.code() in transient:
            log.info(
                "RequestQueueShare %s (Signals not ready) wrk=%s queue=%s",
                e.code().name,
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


# Last observed apply wait per kind, for the caller (ScheduledTaskProcessor)
# to record as a ledger forecast: {"elapsed_s", "final_state", "apply_ms",
# "transitions"}. Written by _wait_applied, read by the spawn path.
LAST_APPLY_WAIT: dict[str, dict] = {}


def _state_name(spb, value: int | None) -> str:
    if value is None:
        return "UNSEEN"
    try:
        return spb.QueueShareState.Name(value)
    except ValueError:
        return f"STATE_{value}"


def _wait_applied(
    request_id: str,
    *,
    queue: str = "",
    kind: str = "",
    net_s: float | None = None,
    stall_s: float | None = None,
    poll_s: float = 1.5,
) -> str:
    """Progress-based wait until the share reaches APPLIED.

    The Scheduler's applier moves a record RECORDED -> APPLYING (batch
    taken, kubectl apply in flight) -> APPLIED. The apply is variable-
    latency (~4 s when the worker is idle, minutes when it is busy or in
    backoff), so this wait keys on PROGRESS, not a deadline: every state
    transition resets patience; no transition for ``stall_s`` logs a
    warning; ``net_s`` is the outer net for a dead arbiter. A fixed 30 s
    deadline here mistook slow applies for stalls (11 of 14 GPU waits on
    2026-09-04). The outcome is handed back via LAST_APPLY_WAIT so the
    caller can score "APPLIED within QUEUE_SHARE_APPLY_EXPECTED_S" in the
    ledger — the arbiter is Brier-scored like every other observer.
    """
    from gaius.core.budgets import QUEUE_SHARE_APPLY_NET_S, QUEUE_SHARE_APPLY_STALL_S
    from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb

    net_s = QUEUE_SHARE_APPLY_NET_S if net_s is None else net_s
    stall_s = QUEUE_SHARE_APPLY_STALL_S if stall_s is None else stall_s
    applying = getattr(spb, "QUEUE_SHARE_APPLYING", 5)
    t0 = time.monotonic()
    last_state: int | None = None
    last_change = t0
    warned_stall = False
    transitions: list[str] = []
    final = "UNSEEN"
    apply_ms = 0
    # Bound the arbiter's work per poll: the record we wait for was just
    # recorded, so an hour-wide, capped listing is enough. An unbounded list
    # over thousands of SUPERSEDED records took >1.5 s server-side; each poll
    # timed out client-side while the server kept working on the abandoned
    # call, and the Scheduler's thread pool saturated (06:04–06:12).
    since = time.time_ns() - 3_600 * 1_000_000_000
    while time.monotonic() - t0 < net_s:
        rec = None
        for r in list_queue_share_requests(queue=queue, since_ns=since, limit=500):
            if r.request.request_id == request_id:
                rec = r
                break
        if rec is not None:
            st = int(rec.state)
            if st != last_state:
                transitions.append(_state_name(spb, st))
                last_state = st
                last_change = time.monotonic()
                warned_stall = False
                if st == applying:
                    log.info(
                        "queue share APPLYING id=%s queue=%s (apply in flight)",
                        request_id, queue,
                    )
            if st == spb.QUEUE_SHARE_APPLIED:
                apply_ms = int(getattr(rec, "apply_ms", 0) or 0)
                log.info(
                    "queue share APPLIED id=%s queue=%s after %.1fs (apply %d ms)",
                    request_id, queue, time.monotonic() - t0, apply_ms,
                )
                final = "APPLIED"
                break
            if st in (spb.QUEUE_SHARE_REJECTED, spb.QUEUE_SHARE_SUPERSEDED):
                final = _state_name(spb, st)
                log.warning("queue share %s id=%s queue=%s", final, request_id, queue)
                break
        if not warned_stall and time.monotonic() - last_change > stall_s:
            warned_stall = True
            log.warning(
                "queue share no progress for %.0fs (state %s) id=%s queue=%s — "
                "Signals applier busy or backing off; waiting under the %.0fs net",
                stall_s, _state_name(spb, last_state), request_id, queue, net_s,
            )
        time.sleep(poll_s)
    else:
        final = _state_name(spb, last_state)
        log.warning(
            "queue share not APPLIED within the %.0fs net (last state %s) id=%s queue=%s — "
            "Signals arbiter dark or apply stuck",
            net_s, final, request_id, queue,
        )
    LAST_APPLY_WAIT[(kind or queue).replace("_", "-")] = {
        "request_id": request_id,
        "queue": queue,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "final_state": final,
        "apply_ms": apply_ms,
        "transitions": transitions,
    }
    return final


def request_queue_share(kind: str, rc: ResourceClass) -> bool:
    """Tell Signals the occupancy intent, then positively wait for APPLIED.

    UNIMPLEMENTED: log, do not fail admit.
    REJECTED or persist error: fail-fast SHAREFAIL, do not admit.
    """
    req = share_for_class(kind, rc)
    resp = _send(req)
    if resp is None:
        return False
    _ADMIT_IDS[kind.replace("_", "-")] = req.request_id
    if resp.accepted and int(getattr(rc, "gpu_tokens", 0)):
        # GPU occupancy: gate on the queue actually being promoted before we let the
        # pod race YuniKorn admission. Zero-floor (ends) don't need to wait.
        # (2026-09-04) Never block the engine's event loop with this wait: a
        # caller on the loop gets its request recorded and moves on, loudly.
        try:
            import asyncio as _aio

            _aio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        if on_loop:
            import traceback as _tb

            # Name the caller: the guard fired 10× for `embedding` on 2026-09-04
            # (twice per SKOS admit tick) with no obvious on-loop call site.
            frames = [
                f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}"
                for f in _tb.extract_stack(limit=9)[:-1]
            ]
            log.warning(
                "#YK.00000011.ONLOOP request_queue_share(%s) called on the event loop — "
                "APPLIED wait skipped (would stall every async probe); run admission "
                "via asyncio.to_thread. Stack: %s",
                kind,
                " <- ".join(reversed(frames)),
            )
            LAST_APPLY_WAIT[kind.replace("_", "-")] = {
                "request_id": req.request_id,
                "queue": rc.queue,
                "elapsed_s": 0.0,
                "final_state": "UNWAITED_ONLOOP",
                "apply_ms": 0,
                "transitions": [],
            }
            return True
        _wait_applied(req.request_id, queue=rc.queue, kind=kind)
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
    timeout_s: float = 1.5,
) -> list:
    """Signals' queue-share records. A transient (UNAVAILABLE / DEADLINE /
    UNIMPLEMENTED) returns [] and logs — a caller that must tell "no records"
    from "no answer" treats an empty list as inconclusive and passes a
    deadline sized for its purpose (admission wants 1.5 s; a verifier listing
    a thousand records can afford 10 s — the 1.5 s default timed out in-engine
    during boot on 2026-09-04 and produced a vacuous objective pass)."""
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
            timeout=float(timeout_s),
        )
    except grpc.RpcError as e:
        transient = (
            grpc.StatusCode.UNIMPLEMENTED,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.UNAVAILABLE,
        )
        if e.code() in transient:
            log.info(
                "ListQueueShareRequests %s (Signals not ready) peer=%s",
                e.code().name,
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


# ── Phase emission (Nautilus's job; in-engine interim) ──────────────────────
# A run's declared intents change with its phase. On phase entry every intent of
# the phase is emitted with the phase horizon as its validity window (so a run
# that dies without its end request cannot hold a floor forever); intents the
# new phase no longer declares get a zero floor that supersedes them.

# (owner_wid, workload) -> (request_id, leaf) of the share currently held
_PHASE_SHARES: dict[tuple[str, str], tuple[str, str]] = {}


def _class_for_leaf(leaf: str):
    from gaius.engine import sentinel_claim as sc

    for rc in (sc.HEAVY, sc.MEDIUM, sc.LIGHT, sc.EXTRACT, sc.COMPUTE):
        if rc.queue == leaf:
            return rc
    return None


def emit_phase_intents(owner_wid: str, owner_kind: str, intents, horizon_s: int) -> int:
    """Emit the given intents for a phase; supersede intents no longer declared.

    Returns the number of requests sent. Never raises — emission is bookkeeping
    toward the arbiter; the claim itself is made (and gated) elsewhere.
    """
    sent = 0
    wanted = {(owner_wid, (i.workload or "").replace("_", "-")): i for i in intents}
    now = time.time_ns()
    until = now + int(max(horizon_s, 60)) * 1_000_000_000 if horizon_s else 0
    try:
        # Zero floors for intents this phase dropped (supersede by request id).
        for key, (rid, leaf) in list(_PHASE_SHARES.items()):
            if key[0] != owner_wid or key in wanted:
                continue
            rc = _class_for_leaf(leaf)
            if rc is not None:
                req = share_for_class(
                    key[1], rc, gpu=0, valid_until_ns=now, supersedes_request_id=rid,
                    applications=0, floor=0, priority=0, owner=owner_kind,
                    owner_id=owner_wid,
                )
                _send(req)
                sent += 1
            _PHASE_SHARES.pop(key, None)
        for key, it in wanted.items():
            rc = _class_for_leaf(it.leaf)
            if rc is None:
                log.warning("phase intent for unknown leaf %s (%s) skipped", it.leaf, it.workload)
                continue
            prior = _PHASE_SHARES.get(key, ("", ""))[0]
            req = share_for_class(
                key[1], rc, gpu=int(it.occupancy or rc.gpu_tokens),
                valid_until_ns=until, supersedes_request_id=prior,
                floor=int(it.floor), priority=int(it.priority), owner=owner_kind,
                owner_id=owner_wid,
            )
            resp = _send(req)
            if resp is not None and getattr(resp, "accepted", False):
                _PHASE_SHARES[key] = (req.request_id, it.leaf)
                sent += 1
    except Exception as e:  # noqa: BLE001 — never fail the run for its bookkeeping
        log.warning("phase intent emission skipped for %s: %s", owner_kind, e)
    return sent


def end_phase_intents(owner_wid: str, owner_kind: str) -> int:
    """Zero-floor every intent still held for this run (run ended or died)."""
    return emit_phase_intents(owner_wid, owner_kind, [], 0)


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
