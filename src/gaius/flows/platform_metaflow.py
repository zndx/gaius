"""Adopt Signals platform Metaflow when the lattice engine supplies it.

Signals Status on :50551 advertises capability=scheduler (YuniKorn) today.
A future ``metaflow`` capability is preferred when present. Metadata health
is the peer-contract ping on :30180 — not a synthetic always-healthy
endpoint on this engine.

Standalone Gaius (Signals unreachable) keeps the local Tilt profile.
Federated + scheduler/metaflow unhealthy, or federated + :30180 down, is
fail-fast — do not silently use Gaius-local Tilt as SoR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterable, Literal
from urllib.error import URLError
from urllib.request import urlopen

Mode = Literal["platform", "local"]

SIGNALS_ENGINE_DEFAULT = "127.0.0.1:50551"
METAFLOW_PING_DEFAULT = "http://127.0.0.1:30180"
PLATFORM_CAPABILITIES = ("metaflow", "scheduler")

# Existing #MF.00000001–04 are query/stack codes. These are lattice-adopt.
GURU_NOSCHED = "#MF.00000005.NOSCHED"
GURU_NOPLATFORM = "#MF.00000006.NOPLATFORM"
GURU_NOPROFILE = "#MF.00000007.NOPROFILE"


class PlatformMetaflowError(RuntimeError):
    """Fail-fast when federation is present but platform Metaflow is not usable."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(
            f"{code} {detail}\n"
            "  Try: just metaflow-platform   # in ~/local/src/wxs/signals\n"
            "  Or:  just signals-ready\n"
            "  Do not start Gaius Tilt Metaflow — it is not SoR when federated"
        )


@dataclass(frozen=True)
class PlatformMetaflowDecision:
    mode: Mode
    reason: str
    signals_project: str | None
    capabilities: tuple[tuple[str, bool], ...]
    metaflow_ping_ok: bool


StatusProbe = Callable[[str, float], tuple[str, list[tuple[str, bool]]] | None]
PingProbe = Callable[[str, float], bool]


def _probe_signals_status(addr: str, timeout: float) -> tuple[str, list[tuple[str, bool]]] | None:
    try:
        import grpc

        from gaius.engine.generated.zndx.engine.v1 import engine_pb2
        from gaius.engine.generated.zndx.engine.v1 import engine_pb2_grpc
    except ImportError:
        return None

    channel = grpc.insecure_channel(addr)
    try:
        stub = engine_pb2_grpc.EngineStub(channel)
        resp = stub.Status(engine_pb2.StatusRequest(), timeout=timeout)
        caps = [(ep.capability, bool(ep.healthy)) for ep in resp.endpoints]
        return resp.project, caps
    except Exception:
        return None
    finally:
        channel.close()


def _ping_metaflow(base_url: str, timeout: float) -> bool:
    ping = base_url.rstrip("/") + "/ping"
    try:
        with urlopen(ping, timeout=timeout) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
            body = resp.read().decode("utf-8", "replace").strip().lower()
        return ok and ("pong" in body or body == "ok")
    except (URLError, OSError, TimeoutError, ValueError):
        return False


def _cap_map(caps: Iterable[tuple[str, bool]]) -> dict[str, bool]:
    return {name.lower(): healthy for name, healthy in caps if name}


def resolve_metaflow_mode(
    *,
    environ: dict[str, str] | None = None,
    status_probe: StatusProbe | None = None,
    ping_probe: PingProbe | None = None,
    engine_addr: str | None = None,
    metaflow_url: str | None = None,
    timeout: float = 2.0,
) -> PlatformMetaflowDecision:
    """Decide platform vs local from Signals Engine/Status + Metaflow ping.

    ``GAIUS_METAFLOW_MODE=platform|local`` forces the mode (tests / break-glass).
    Forced ``platform`` still requires a ping unless ``GAIUS_METAFLOW_SKIP_PING=1``.
    """
    env = environ if environ is not None else os.environ
    override = (env.get("GAIUS_METAFLOW_MODE") or "").strip().lower()
    addr = engine_addr or env.get("SIGNALS_ENGINE_GRPC") or SIGNALS_ENGINE_DEFAULT
    url = metaflow_url or env.get("METAFLOW_SERVICE_URL") or METAFLOW_PING_DEFAULT
    probe = status_probe or _probe_signals_status
    ping = ping_probe or _ping_metaflow
    skip_ping = (env.get("GAIUS_METAFLOW_SKIP_PING") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    if override in ("local", "platform"):
        ping_ok = True if skip_ping else ping(url, timeout)
        if override == "platform" and not ping_ok:
            raise PlatformMetaflowError(
                GURU_NOPLATFORM,
                f"GAIUS_METAFLOW_MODE=platform but Metaflow ping failed at {url}/ping",
            )
        return PlatformMetaflowDecision(
            mode=override,  # type: ignore[arg-type]
            reason=f"GAIUS_METAFLOW_MODE={override}",
            signals_project=None,
            capabilities=(),
            metaflow_ping_ok=ping_ok,
        )

    probed = probe(addr, timeout)
    if probed is None:
        return PlatformMetaflowDecision(
            mode="local",
            reason=f"Signals Engine/Status unreachable at {addr} — standalone Tilt profile",
            signals_project=None,
            capabilities=(),
            metaflow_ping_ok=False,
        )

    project, caps = probed
    cmap = _cap_map(caps)
    if (project or "").lower() != "signals":
        return PlatformMetaflowDecision(
            mode="local",
            reason=f"Engine at {addr} project={project!r} is not signals",
            signals_project=project,
            capabilities=tuple(caps),
            metaflow_ping_ok=False,
        )

    platform_caps = {k: cmap[k] for k in PLATFORM_CAPABILITIES if k in cmap}
    if not platform_caps:
        raise PlatformMetaflowError(
            GURU_NOSCHED,
            f"Signals Status at {addr} advertises no metaflow/scheduler capability",
        )
    if "metaflow" in platform_caps and not platform_caps["metaflow"]:
        raise PlatformMetaflowError(
            GURU_NOPLATFORM,
            f"Signals Status capability=metaflow is unhealthy at {addr}",
        )
    if "scheduler" in platform_caps and not platform_caps["scheduler"]:
        raise PlatformMetaflowError(
            GURU_NOSCHED,
            f"Signals Status capability=scheduler is unhealthy at {addr} "
            "(YuniKorn is the Metaflow compute admitter)",
        )

    ping_ok = True if skip_ping else ping(url, timeout)
    if not ping_ok:
        raise PlatformMetaflowError(
            GURU_NOPLATFORM,
            f"Signals scheduler is healthy but Metaflow metadata is down at {url}/ping",
        )

    chosen = "metaflow" if platform_caps.get("metaflow") else "scheduler"
    return PlatformMetaflowDecision(
        mode="platform",
        reason=f"Signals Engine/Status {chosen} healthy; Metaflow {url} ready",
        signals_project=project,
        capabilities=tuple(caps),
        metaflow_ping_ok=True,
    )
