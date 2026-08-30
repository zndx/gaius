"""Intended workload-profile publisher for the WatchWorkload stream.

Materializes the engine's live *desired-vs-actual* serving set — the abstraction
the orchestrator lacked — and fans it out to `Engine/WatchWorkload` subscribers so
an out-of-band watchdog can verify without racing changeovers.

Contract (see engine.proto WatchWorkload):
- There is ALWAYS a profile while the engine is alive (empty intents = intentionally
  serving nothing — still a valid SETTLED state).
- The engine emits phase=TRANSITIONING just before it changes the serving set and a
  new SETTLED profile once the change lands (the `_publishes_transition` decorator
  on begin_workload/complete_workload brackets each changeover).
- Each intent carries its ACTUAL status; the watchdog compares desired-vs-actual
  ONLY while SETTLED and past that intent's `warmup_seconds`, then recycles the unit
  (which the engine cannot do to itself) on a sustained settled mismatch.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Actual-status vocabulary (mirrors proto WorkloadStatus; the servicer maps these
# strings to the enum). "serving" is the only non-mismatch state.
STATUS_SERVING = "serving"
STATUS_STARTING = "starting"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"
STATUS_ABSENT = "absent"

PHASE_SETTLED = "settled"
PHASE_TRANSITIONING = "transitioning"

# Per-capability warmup grace (seconds after settle) before actual != SERVING is a
# miss. The 27B thinking baseline (TP=4 cold load via gpu_cleanup) needs the most.
_WARMUP_THINKING = int(os.environ.get("GAIUS_WORKLOAD_WARMUP_THINKING", "330"))
_WARMUP_DEFAULT = int(os.environ.get("GAIUS_WORKLOAD_WARMUP_DEFAULT", "90"))

# Subscriber queue depth. Small: the watchdog only needs the latest; on overflow we
# drop the oldest so a slow/absent consumer never blocks a changeover.
_QUEUE_MAXSIZE = 8


def _map_actual(proc_status: str) -> str:
    s = (proc_status or "").lower().replace("process_status_", "")
    if s in ("healthy", "running", "ready"):
        return STATUS_SERVING
    if s in ("starting", "pending"):
        return STATUS_STARTING
    if s in ("unhealthy",):
        return STATUS_DEGRADED
    if s in ("failed", "stopping", "stopped"):
        return STATUS_FAILED
    return STATUS_DEGRADED  # unknown non-empty → visible, not silently "serving"


@dataclass
class WorkloadProfilePublisher:
    """Holds the intended-profile version state + fans out snapshots to subscribers.

    `orchestrator` is the OrchestratorService (typed loosely to avoid an import
    cycle). Snapshots are plain dicts; the servicer converts them to proto.
    """

    orchestrator: Any
    generation: int = 0
    phase: str = PHASE_SETTLED
    settled_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    detail: str = "init"
    _subs: list[asyncio.Queue] = field(default_factory=list)

    # ── intent computation ────────────────────────────────────────────────────
    def _baseline_aliases(self) -> list[str]:
        cfg = getattr(self.orchestrator, "config", None)
        startup = getattr(cfg, "startup", None) if cfg is not None else None
        return list(getattr(startup, "preload_endpoints", []) or [])

    def _warmup(self, alias: str, caps: list[str]) -> int:
        if alias == "thinking" or "thinking" in (caps or []):
            return _WARMUP_THINKING
        return _WARMUP_DEFAULT

    def compute_intents(self) -> list[dict]:
        """The current intended set with actual status, from live orchestrator state.

        Intended = (running, non-evicted, non-stopping endpoints) ∪ (baseline
        endpoints that intend to be up but have no process at all → ABSENT). An
        evicted baseline (e.g. thinking during a render) is simply absent from the
        list — never a failure.
        """
        orch = self.orchestrator
        try:
            status = orch.get_status() or {}
        except Exception as e:  # noqa: BLE001
            logger.debug(f"workload profile: get_status failed: {e}")
            status = {}
        eps = status.get("endpoints") or {}
        evicted = set(getattr(orch, "_evicted_endpoints", set()) or set())

        intents: list[dict] = []
        seen: set[str] = set()
        for alias, ep in eps.items():
            if alias in evicted or not isinstance(ep, dict):
                continue
            st = str(ep.get("status") or "")
            if _map_actual(st) == STATUS_FAILED and st.lower().replace(
                "process_status_", ""
            ) in ("stopping", "stopped"):
                continue  # being torn down on purpose — not intended
            caps = list(ep.get("capabilities") or [])
            cap = caps[0] if caps else alias
            intents.append(
                {
                    "capability": cap,
                    "alias": alias,
                    "model": str(ep.get("model") or ""),
                    "port": int(ep.get("port") or 0),
                    "gpu_ids": [int(g) for g in (ep.get("gpu_ids") or [])],
                    "backend": "vllm_local",
                    "warmup_seconds": self._warmup(alias, caps),
                    "actual": _map_actual(st),
                }
            )
            seen.add(alias)

        for alias in self._baseline_aliases():
            if alias in evicted or alias in seen:
                continue
            port = int(os.environ.get("GAIUS_THINKING_PORT", "8081")) if alias == "thinking" else 0
            intents.append(
                {
                    "capability": alias,
                    "alias": alias,
                    "model": "",
                    "port": port,
                    "gpu_ids": [],
                    "backend": "vllm_local",
                    "warmup_seconds": self._warmup(alias, [alias]),
                    "actual": STATUS_ABSENT,
                }
            )
        return intents

    def snapshot(self) -> dict:
        return {
            "phase": self.phase,
            "generation": self.generation,
            "settled_at_ms": self.settled_at_ms,
            "detail": self.detail,
            "intents": self.compute_intents(),
        }

    # ── fanout ────────────────────────────────────────────────────────────────
    def _publish(self) -> None:
        snap = self.snapshot()
        for q in list(self._subs):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except Exception:  # noqa: BLE001
                        pass
                q.put_nowait(snap)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"workload profile publish to subscriber failed: {e}")

    def mark_transitioning(self, detail: str) -> None:
        self.phase = PHASE_TRANSITIONING
        self.detail = detail
        logger.debug(f"workload profile → TRANSITIONING: {detail}")
        self._publish()

    def settle(self, detail: str) -> None:
        self.phase = PHASE_SETTLED
        self.generation += 1
        self.settled_at_ms = int(time.time() * 1000)
        self.detail = detail
        logger.debug(f"workload profile → SETTLED gen={self.generation}: {detail}")
        self._publish()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        q.put_nowait(self.snapshot())  # seed a new subscriber with the current profile
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    def current(self) -> dict:
        return self.snapshot()


def _publishes_transition(fn):
    """Bracket a changeover method: TRANSITIONING on entry, SETTLED on exit.

    Applied to OrchestratorService.begin_workload / complete_workload so the phase
    stays TRANSITIONING for the whole changeover (evict/plan/restore) and settles
    once — even on an early return or an exception.
    """

    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        wp = getattr(self, "_workload_profile", None)
        if wp is not None:
            wp.mark_transitioning(fn.__name__)
        try:
            return await fn(self, *args, **kwargs)
        finally:
            if wp is not None:
                wp.settle(fn.__name__)

    return wrapper
