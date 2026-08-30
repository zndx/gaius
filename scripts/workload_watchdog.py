#!/usr/bin/env python3
"""Out-of-band workload watchdog — verifies the engine's INTENDED serving set.

Replaces the boot-only thinking-ready oneshot and its GPU-idle heuristic (which
guessed at intent and produced false positives/negatives — thinking is legitimately
down during a viz eviction, or "idle" mid-load). Instead it consumes the engine's
own held-open `Engine/WatchWorkload` stream (signals-protocol v1): the engine
declares what it INTENDS to serve, each intent's ACTUAL status, and a SETTLED vs
TRANSITIONING phase that brackets every changeover.

Rule: recycle the unit (which the engine cannot do to itself) ONLY when, in a
SETTLED profile and past an intent's warmup_seconds, a desired intent is not
SERVING — sustained for MISS_CONFIRM. During TRANSITIONING it holds; an evicted
capability simply drops out of the intents list (never a miss). Budget-bounded so a
recycle-can't-fix cause (e.g. a venv clobber) stops thrashing and hands off.

Engine death / :50051 dark is NOT this watchdog's job — that's gaius-engine-ready.
Here a dropped stream just means "reconnect and wait". Guru: #EP.00000018.THINKNOLOAD
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# engine_pb2 imports cheaply now that gaius.engine.__init__ is lazy (~0.2s).
for _p in (str(REPO / "src" / "gaius" / "engine" / "generated"), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import grpc  # noqa: E402
from zndx.engine.v1 import engine_pb2 as pb  # noqa: E402

# ── config ─────────────────────────────────────────────────────────────────────
PORT = os.environ.get("GAIUS_ENGINE_GRPC_PORT", "50051")
STATE_DIR = os.environ.get("GAIUS_CRASH_STATE_DIR", "/var/lib/gaius")
DEFER_MARKER = os.environ.get("GAIUS_DEFER_MARKER", f"{STATE_DIR}/defer-gpu")
LEDGER = os.environ.get("GAIUS_WORKLOAD_RECYCLE_LEDGER", f"{STATE_DIR}/workload-recycles")
# Caps each intent's warmup grace (0 = no cap). An operator/test knob — the grace
# is otherwise the engine-declared per-intent warmup_seconds.
WARMUP_MAX = int(os.environ.get("GAIUS_WORKLOAD_WARMUP_MAX", "0"))
BUDGET_K = int(os.environ.get("GAIUS_WORKLOAD_RECYCLE_BUDGET_K", "3"))
BUDGET_WINDOW_S = int(os.environ.get("GAIUS_WORKLOAD_RECYCLE_WINDOW_S", "3600"))
RECYCLE_COOLDOWN_S = int(os.environ.get("GAIUS_WORKLOAD_RECYCLE_COOLDOWN_S", "240"))
RECONNECT_BACKOFF_S = int(os.environ.get("GAIUS_WORKLOAD_RECONNECT_BACKOFF_S", "10"))
GURU = "#EP.00000018.THINKNOLOAD"

_PHASE = {pb.WORKLOAD_PHASE_SETTLED: "settled", pb.WORKLOAD_PHASE_TRANSITIONING: "transitioning"}
_SERVING = pb.WORKLOAD_STATUS_SERVING


def log(msg: str) -> None:
    print(f"workload-watchdog: {msg}", flush=True)


def now() -> float:
    return time.time()


def _ledger_prune_count() -> int:
    cutoff = now() - BUDGET_WINDOW_S
    try:
        lines = [ln for ln in Path(LEDGER).read_text().splitlines() if ln.strip()]
    except OSError:
        return 0
    kept = [ln for ln in lines if _as_float(ln) >= cutoff]
    try:
        Path(LEDGER).write_text("\n".join(kept) + ("\n" if kept else ""))
    except OSError:
        pass
    return len(kept)


def _as_float(s: str) -> float:
    try:
        return float(s.strip())
    except ValueError:
        return 0.0


def _record_recycle() -> None:
    try:
        with open(LEDGER, "a") as fh:
            fh.write(f"{now()}\n")
    except OSError as e:
        log(f"WARN: could not write ledger: {e}")


def _recycle(reason: str) -> None:
    n = _ledger_prune_count()
    if n >= BUDGET_K:
        log(
            f"{GURU} recycle budget exhausted ({n}/{BUDGET_K} in {BUDGET_WINDOW_S}s) — "
            f"NOT recycling; workload still unmet ({reason}). Needs an operator fix "
            f"(a recycle can't repair e.g. a venv clobber)."
        )
        return
    _record_recycle()
    log(f"{GURU} {reason} — COMPLETE recycle via the unit (recycle {n + 1}/{BUDGET_K})")
    os.system("systemctl restart --no-block gaius.service")


def _warmup_for(intent) -> int:
    """Grace (seconds) the engine has to bring an intent to SERVING, measured from
    when the WATCHDOG first saw it not-serving (so an endpoint crash gets the full
    grace for the engine to self-restore before the watchdog recycles). WARMUP_MAX
    caps it (0 = no cap)."""
    w = int(intent.warmup_seconds)
    return min(w, WARMUP_MAX) if WARMUP_MAX > 0 else w


def _status_name(v: int) -> str:
    return {
        pb.WORKLOAD_STATUS_SERVING: "serving",
        pb.WORKLOAD_STATUS_STARTING: "starting",
        pb.WORKLOAD_STATUS_DEGRADED: "degraded",
        pb.WORKLOAD_STATUS_FAILED: "failed",
        pb.WORKLOAD_STATUS_ABSENT: "absent",
    }.get(v, "unspec")


def _consume(channel) -> None:
    """Consume one WatchWorkload stream until it ends/errors.

    Per intent, track `bad_since` = when the watchdog first saw it not-SERVING in
    the current settled generation. An intent is a MISS once it has been not-SERVING
    for its warmup — i.e. the engine had that long to self-restore and did not.
    Recycle on any miss; hold during transitions; evicted (absent-from-profile)
    intents clear; honor the defer marker.
    """
    call = channel.unary_stream(
        "/zndx.engine.v1.Engine/WatchWorkload",
        request_serializer=lambda m: m.SerializeToString(),
        response_deserializer=pb.WorkloadProfile.FromString,
    )
    stream = call(pb.WatchWorkloadRequest())
    cur_gen = None
    bad_since: dict[str, float] = {}
    for profile in stream:
        if os.path.exists(DEFER_MARKER):
            bad_since.clear()
            continue
        if _PHASE.get(profile.phase) != "settled":
            bad_since.clear()  # hold: never evaluate mid-changeover
            continue
        if profile.generation != cur_gen:
            cur_gen = profile.generation
            bad_since.clear()  # fresh settled generation → fresh warmup windows

        t = now()
        present: set[str] = set()
        misses: list[str] = []
        for it in profile.intents:
            present.add(it.alias)
            if it.actual == _SERVING:
                if bad_since.pop(it.alias, None) is not None:
                    log(f"gen={profile.generation} {it.alias} recovered — serving")
                continue
            if it.alias not in bad_since:
                bad_since[it.alias] = t
                log(
                    f"{GURU} gen={profile.generation} {it.alias} not serving "
                    f"({_status_name(it.actual)}) — {_warmup_for(it)}s grace for the engine"
                )
            waited = int(t - bad_since[it.alias])
            if waited >= _warmup_for(it):
                misses.append(f"{it.alias}({_status_name(it.actual)},down={waited}s)")
        # An intent that dropped out of the profile (evicted) is not a miss.
        for alias in [a for a in bad_since if a not in present]:
            bad_since.pop(alias, None)

        if misses:
            _recycle("settled workload unmet: " + ", ".join(misses))
            bad_since.clear()
            time.sleep(RECYCLE_COOLDOWN_S)  # let the recycle + reload land


def main() -> int:
    log(
        f"watchdog up — stream :{PORT}/WatchWorkload "
        f"warmup_cap={WARMUP_MAX or 'none'} budget={BUDGET_K}/{BUDGET_WINDOW_S}s"
    )
    # keepalive so a dead engine breaks the held-open stream promptly (→ reconnect).
    opts = [
        ("grpc.keepalive_time_ms", 20000),
        ("grpc.keepalive_timeout_ms", 10000),
        ("grpc.keepalive_permit_without_calls", 1),
    ]
    while True:
        channel = grpc.insecure_channel(f"127.0.0.1:{PORT}", options=opts)
        try:
            _consume(channel)
            log("stream ended — reconnecting")
        except grpc.RpcError as e:
            # Engine down / :50051 dark is gaius-engine-ready's job; just wait + retry.
            log(f"stream error ({e.code() if hasattr(e, 'code') else e}) — reconnect in {RECONNECT_BACKOFF_S}s")
        except Exception as e:  # noqa: BLE001
            log(f"unexpected error: {e} — reconnect in {RECONNECT_BACKOFF_S}s")
        finally:
            channel.close()
        time.sleep(RECONNECT_BACKOFF_S)


if __name__ == "__main__":
    raise SystemExit(main())
