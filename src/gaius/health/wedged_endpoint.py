"""Detect and remediate a wedged inference endpoint.

A wedged vLLM is alive by every coarse measure and serves nothing: the port
stays bound, the process never exits, the GPUs keep their memory, and the
HTTP surface simply does not answer. Observed 2026-08-25 on thinking :8081 —
healthy at 06:40, silent by 14:06:

    /health           no response in 15s
    GPU utilisation   0% on four cards, memory still held
    worker CPU        86-88%, ~6.5h accumulated
    EngineCore        futex_wait_queue
    :8081 sockets     18 CLOSE-WAIT against 4 established

Nothing recovered it for seven hours, and ``/health fix endpoints`` could not
even see it: that path asks ``Orchestrator.status`` first, and a wedged
endpoint is exactly what blocks the orchestrator, so it reported
``#GR.00000001.ENGINEOFF`` about a perfectly healthy engine.

So this module deliberately depends on **nothing but the host**: it finds
endpoints from the running ``vllm serve`` argv, probes their HTTP surface
directly, and remediates with signals. No gRPC, no orchestrator, no engine.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

GURU_WEDGED = "#EP.00000019.WEDGED"

# A cold start may legitimately take VLLMController._startup_timeout (900s)
# during which the process is alive and unresponsive. Never call anything
# younger than that wedged — killing a loading endpoint would be far worse
# than waiting out a hung one.
DEFAULT_MIN_UPTIME_S = float(os.environ.get("GAIUS_WEDGED_MIN_UPTIME_S", "900"))

# One slow reply is not a wedge. Require several misses in a row.
DEFAULT_PROBES = 3
DEFAULT_PROBE_TIMEOUT_S = 5.0
DEFAULT_PROBE_GAP_S = 1.0


class EndpointVerdict(str, Enum):
    """What a direct probe concluded about one endpoint."""

    HEALTHY = "healthy"
    STARTING = "starting"  # unresponsive, but still inside the startup floor
    WEDGED = "wedged"  # alive, bound, unresponsive well past the floor
    DOWN = "down"  # no process
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EndpointProbe:
    """One endpoint's directly-observed state."""

    port: int
    pid: int | None = None
    model: str = ""
    uptime_s: float = 0.0
    responded: bool = False
    attempts: int = 0
    latency_ms: float = 0.0
    verdict: EndpointVerdict = EndpointVerdict.UNKNOWN
    detail: str = ""
    close_wait: int = 0

    @property
    def is_wedged(self) -> bool:
        return self.verdict is EndpointVerdict.WEDGED

    def guru_report(self) -> str:
        """Actionable text for a fail-fast error path."""
        if not self.is_wedged:
            return f"endpoint :{self.port} is {self.verdict.value}"
        return (
            f"Endpoint :{self.port} ({self.model or 'unknown model'}, pid "
            f"{self.pid}) is wedged: bound and alive for "
            f"{self.uptime_s / 3600:.1f}h but no HTTP reply in "
            f"{self.attempts} probes.\n"
            f"  {self.detail}\n"
            f"  Guru: {GURU_WEDGED}\n"
            "  Try: /health fix endpoints\n"
            "  Or:  devenv processes restart gaius-engine"
        )


@dataclass
class RemediationOutcome:
    """What remediation actually did."""

    port: int
    pid: int | None
    signalled: list[str] = field(default_factory=list)
    exited: bool = False
    error: str = ""

    @property
    def success(self) -> bool:
        return self.exited and not self.error


def _vllm_endpoints() -> list[tuple[int, int, str]]:
    """(pid, port, model) for every running ``vllm serve`` on this host.

    Read from argv rather than from the orchestrator so a blocked engine
    cannot hide an endpoint from us.
    """
    out: list[tuple[int, int, str]] = []
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a hard dep here
        logger.warning("psutil unavailable; cannot enumerate vLLM endpoints")
        return out

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            argv = proc.info.get("cmdline") or []
        except Exception:
            continue
        if not argv or "serve" not in argv:
            continue
        joined = " ".join(argv)
        if "vllm" not in joined:
            continue
        port = _port_from_argv(argv)
        if port is None:
            continue
        out.append((proc.info["pid"], port, _model_from_argv(argv)))
    return _dedupe_by_port(out)


def _listening_pid(port: int) -> int | None:
    """The pid actually holding the listening socket on ``port``."""
    try:
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            if (
                conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and conn.laddr.port == port
                and conn.pid
            ):
                return conn.pid
    except Exception:
        return None
    return None


def _dedupe_by_port(found: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """One entry per port, preferring the process that owns the socket.

    A launcher (``uv run python -m …``) carries the same argv as the server
    it spawned, so both match. Signalling the wrapper would leave the wedged
    child holding the port.
    """
    by_port: dict[int, tuple[int, int, str]] = {}
    for pid, port, model in found:
        owner = _listening_pid(port)
        current = by_port.get(port)
        if current is None or (owner is not None and pid == owner):
            by_port[port] = (pid, port, model)
    return list(by_port.values())


def _port_from_argv(argv: list[str]) -> int | None:
    for i, tok in enumerate(argv):
        if tok == "--port" and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                return None
        if tok.startswith("--port="):
            try:
                return int(tok.split("=", 1)[1])
            except ValueError:
                return None
    return None


def _model_from_argv(argv: list[str]) -> str:
    try:
        i = argv.index("serve")
    except ValueError:
        return ""
    if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
        return argv[i + 1]
    return ""


def _uptime_s(pid: int) -> float:
    try:
        import psutil

        return max(0.0, time.time() - psutil.Process(pid).create_time())
    except Exception:
        return 0.0


def close_wait_count(port: int) -> int:
    """CLOSE-WAIT sockets on ``port`` — the pile-up a wedged server leaves.

    Corroborating only: a healthy busy server has a few. It is never the
    sole basis for a verdict.
    """
    try:
        import psutil

        n = 0
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != "CLOSE_WAIT":
                continue
            if conn.laddr and conn.laddr.port == port:
                n += 1
            elif conn.raddr and conn.raddr.port == port:
                n += 1
        return n
    except Exception:
        return 0


async def _http_ok(port: int, timeout_s: float) -> tuple[bool, float]:
    """One HTTP probe. Returns (answered, latency_ms).

    Any reply at all counts as answered — even 4xx. We are asking whether the
    server is *serving*, not whether it likes the request.
    """
    import httpx

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/health")
            return resp.status_code < 500, (time.monotonic() - started) * 1000
    except Exception:
        return False, (time.monotonic() - started) * 1000


async def probe_endpoint(
    port: int,
    pid: int | None = None,
    model: str = "",
    *,
    probes: int = DEFAULT_PROBES,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
    gap_s: float = DEFAULT_PROBE_GAP_S,
    min_uptime_s: float = DEFAULT_MIN_UPTIME_S,
) -> EndpointProbe:
    """Classify one endpoint from the host, without touching the engine."""
    uptime = _uptime_s(pid) if pid else 0.0

    attempts = 0
    latency = 0.0
    for attempt in range(max(1, probes)):
        attempts = attempt + 1
        ok, latency = await _http_ok(port, timeout_s)
        if ok:
            return EndpointProbe(
                port=port,
                pid=pid,
                model=model,
                uptime_s=uptime,
                responded=True,
                attempts=attempts,
                latency_ms=latency,
                verdict=EndpointVerdict.HEALTHY,
                detail=f"answered in {latency:.0f}ms",
            )
        if attempt + 1 < max(1, probes):
            await asyncio.sleep(gap_s)

    if pid is None:
        return EndpointProbe(
            port=port,
            pid=None,
            model=model,
            attempts=attempts,
            verdict=EndpointVerdict.DOWN,
            detail="no vLLM process owns this port",
        )

    cw = close_wait_count(port)
    if uptime < min_uptime_s:
        return EndpointProbe(
            port=port,
            pid=pid,
            model=model,
            uptime_s=uptime,
            attempts=attempts,
            latency_ms=latency,
            verdict=EndpointVerdict.STARTING,
            close_wait=cw,
            detail=(
                f"unresponsive but only {uptime:.0f}s old; a cold start is "
                f"allowed {min_uptime_s:.0f}s"
            ),
        )

    return EndpointProbe(
        port=port,
        pid=pid,
        model=model,
        uptime_s=uptime,
        attempts=attempts,
        latency_ms=latency,
        verdict=EndpointVerdict.WEDGED,
        close_wait=cw,
        detail=(
            f"{attempts} probes timed out at {timeout_s:.0f}s each; "
            f"process alive {uptime / 3600:.1f}h; {cw} CLOSE-WAIT sockets"
        ),
    )


async def scan_endpoints(**kwargs) -> list[EndpointProbe]:
    """Probe every vLLM endpoint on this host, concurrently."""
    found = _vllm_endpoints()
    if not found:
        return []
    return list(
        await asyncio.gather(
            *(probe_endpoint(port, pid, model, **kwargs) for pid, port, model in found)
        )
    )


async def find_wedged(**kwargs) -> list[EndpointProbe]:
    """Only the endpoints that are actually wedged."""
    return [p for p in await scan_endpoints(**kwargs) if p.is_wedged]


async def remediate_wedged(
    probe: EndpointProbe,
    *,
    term_grace_s: float = 20.0,
    poll_s: float = 1.0,
) -> RemediationOutcome:
    """Free a wedged endpoint by ending its process.

    The engine supervises vLLM: once the child exits, its own health loop
    sees a returncode and starts a replacement. So the cure is to make the
    wedged process exit — SIGTERM first, SIGKILL only if it will not go.
    A futex-blocked engine core frequently ignores SIGTERM, which is why the
    escalation is not optional.
    """
    out = RemediationOutcome(port=probe.port, pid=probe.pid)
    if not probe.is_wedged:
        out.error = f"refusing to signal a {probe.verdict.value} endpoint"
        return out
    if probe.pid is None:
        out.error = "no pid to signal"
        return out

    for sig, grace in ((signal.SIGTERM, term_grace_s), (signal.SIGKILL, 5.0)):
        try:
            os.kill(probe.pid, sig)
            out.signalled.append(sig.name)
        except ProcessLookupError:
            out.exited = True
            return out
        except PermissionError as e:
            out.error = f"cannot signal pid {probe.pid}: {e}"
            return out

        waited = 0.0
        while waited < grace:
            if not _pid_alive(probe.pid):
                out.exited = True
                return out
            await asyncio.sleep(poll_s)
            waited += poll_s

    out.error = f"pid {probe.pid} survived SIGTERM and SIGKILL"
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def summarize(probes: list[EndpointProbe]) -> dict:
    """Shape the scan for the CLI / health report."""
    wedged = [p for p in probes if p.is_wedged]
    return {
        "checked": len(probes),
        "wedged": len(wedged),
        "guru_meditation": GURU_WEDGED if wedged else None,
        "endpoints": [
            {
                "port": p.port,
                "pid": p.pid,
                "model": p.model,
                "verdict": p.verdict.value,
                "uptime_s": round(p.uptime_s, 1),
                "latency_ms": round(p.latency_ms, 1),
                "close_wait": p.close_wait,
                "detail": p.detail,
            }
            for p in probes
        ],
        "remediation": (
            "/health fix endpoints" if wedged else None
        ),
    }


__all__ = [
    "DEFAULT_MIN_UPTIME_S",
    "GURU_WEDGED",
    "EndpointProbe",
    "EndpointVerdict",
    "RemediationOutcome",
    "close_wait_count",
    "find_wedged",
    "probe_endpoint",
    "remediate_wedged",
    "scan_endpoints",
    "summarize",
]
