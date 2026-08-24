"""Server-to-server query helpers (signals-protocol Engine/ServerQuery).

Matrix S2S Queries: pairwise snapshot. Not epidemic gossip. Not CZMQ zgossip.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .generated.zndx.engine.v1 import engine_pb2 as zpb

logger = logging.getLogger(__name__)

GURU_NOGIT = (
    "git is not available for ServerQuery remotes.\n"
    "  Guru: #SS.00000001.NOGIT\n"
    "  Try: install git on the engine host"
)
GURU_NOREPO = (
    "Engine checkout is not a git repository.\n"
    "  Guru: #SS.00000002.NOREPO\n"
    "  Try: set GAIUS_REPO_ROOT or DEVENV_ROOT to the Gaius worktree"
)


class ServerQueryError(RuntimeError):
    """Fail-fast ServerQuery error with guru in the message."""


def repo_root() -> Path:
    raw = os.environ.get("GAIUS_REPO_ROOT") or os.environ.get("DEVENV_ROOT") or ""
    if raw:
        return Path(raw)
    return Path.cwd()


def list_named_remotes(root: Path | None = None) -> list[tuple[str, str]]:
    """Return unique (name, fetch_url) from `git remote -v`. Do not invent remotes."""
    checkout = root or repo_root()
    try:
        proc = subprocess.run(
            ["git", "-C", str(checkout), "remote", "-v"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise ServerQueryError(GURU_NOGIT) from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise ServerQueryError(f"{GURU_NOREPO}\n  git: {err}")
    seen: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        if "(push)" in line and name in seen:
            continue
        if name not in seen:
            seen[name] = url
    return [(name, seen[name]) for name in seen]


def advertised_head(root: Path | None = None) -> str:
    checkout = root or repo_root()
    try:
        proc = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


_LOOPBACK = frozenset({"localhost", "ip6-localhost", "::1", "0.0.0.0", "::"})


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if not h:
        return True
    if h in _LOOPBACK or h.startswith("127."):
        return True
    return False


def advertise_host() -> str:
    """Cluster hostname for S2S. Same resolution as Ægir/Signals.

    Prefer shared lattice env, then FQDN, then ``{short}.dev.vista.zndx.org``
    when it resolves. Never loopback — empty is honest.
    """
    for key in (
        "GAIUS_ADVERTISE_HOST",
        "GAIUS_LATTICE_HOST",
        "SIGNALS_ADVERTISE_HOST",
        "SIGNALS_LATTICE_HOST",
        "SIGNALS_KRB_HOST",
        "AEGIR_ADVERTISE_HOST",
    ):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        host = raw.split("/")[-1].split(":")[0].strip("[]")
        if host and not is_loopback_host(host):
            return host
    try:
        fqdn = (socket.getfqdn() or "").strip()
        if fqdn and not is_loopback_host(fqdn) and "." in fqdn:
            return fqdn
        hn = (socket.gethostname() or "").strip()
        if hn and not is_loopback_host(hn) and "." in hn:
            return hn
        if hn and not is_loopback_host(hn):
            zt = f"{hn}.dev.vista.zndx.org"
            try:
                socket.getaddrinfo(zt, None)
                return zt
            except OSError:
                return hn
    except OSError:
        pass
    return ""


def rewrite_public_url(url: str) -> str:
    host = advertise_host()
    if not url or not host:
        return url
    parsed = urlparse(url)
    if not parsed.hostname or not is_loopback_host(parsed.hostname):
        return url
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse(
        (parsed.scheme or "http", netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def surface_title(project: str) -> str:
    raw = (project or "").strip()
    known = {
        "gaius": "Gaius",
        "signals": "Signals",
        "aegir": "Ægir",
        "atelier": "Atelier",
    }
    if raw.lower() in known:
        return known[raw.lower()]
    if not raw:
        return "Peer"
    return raw.replace("-", " ").replace("_", " ").title()


def local_primary_ui() -> str:
    """Hostname URL for S2S. Never advertise loopback."""
    raw = (os.environ.get("GAIUS_PRIMARY_UI") or "").strip()
    if raw:
        rewritten = rewrite_public_url(raw)
        parsed = urlparse(rewritten)
        if parsed.hostname and not is_loopback_host(parsed.hostname):
            return rewritten
    host = advertise_host()
    if not host:
        return ""
    port = "9890"
    bind = (os.environ.get("GAIUS_UI_BIND") or "").strip()
    if bind:
        maybe = bind.rsplit(":", 1)[-1]
        if maybe.isdigit():
            port = maybe
    return f"http://{host}:{port}"


def local_surfaces() -> list[zpb.Surface]:
    url = local_primary_ui()
    if not url:
        return []
    return [zpb.Surface(kind="primary", url=url, healthy=True)]


def directory_seeds() -> list[tuple[str, str]]:
    """Engine targets to probe. Not a UI roster.

    SIGNALS_ENGINE_TARGET is the lattice hub gRPC (Status/ServerQuery),
    not a canned Signals UI URL.
    """
    hub = (os.environ.get("SIGNALS_ENGINE_TARGET") or "").strip()
    if not hub:
        return []
    return [("", hub.replace("grpc://", ""))]


def primary_ui_of(status: zpb.StatusResponse) -> str:
    for surf in status.surfaces:
        if (surf.kind or "primary") == "primary" and (surf.url or "").strip():
            return surf.url.strip()
    return ""


async def status_peer(target: str) -> zpb.StatusResponse | None:
    import grpc
    from grpc import aio

    from .generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    addr = target.replace("grpc://", "").strip()
    channel = aio.insecure_channel(addr)
    try:
        stub = zpb_grpc.EngineStub(channel)
        return await stub.Status(zpb.StatusRequest(), timeout=4)
    except grpc.RpcError as e:
        logger.info("Status failed at %s: %s", addr, e.code())
        return None
    finally:
        await channel.close()


async def collect_peer_surfaces(
    services: object,
    *,
    skip_project: str = "gaius",
) -> list[dict[str, str]]:
    """S2S: self + PEERS + Status.surfaces. Only advertised primary UIs."""
    queue: list[tuple[str, str]] = list(configured_peers(services))
    queue.extend(directory_seeds())
    seen_addr: set[str] = set()
    by_project: dict[str, dict[str, str]] = {}
    self_ui = local_primary_ui()
    if self_ui:
        host = advertise_host() or "localhost"
        by_project["gaius"] = {
            "project": "gaius",
            "title": surface_title("gaius"),
            "engine_target": f"{host}:50051",
            "primary_ui": self_ui,
        }
    while queue:
        hint_project, target = queue.pop(0)
        addr = target.replace("grpc://", "").strip()
        if not addr or addr in seen_addr:
            continue
        seen_addr.add(addr)
        status = await status_peer(addr)
        if status is None:
            continue
        project = (status.project or hint_project or "").strip()
        if project and project == skip_project:
            continue
        ui = primary_ui_of(status)
        key = (project or addr).lower()
        if ui:
            prev = by_project.get(key)
            if prev is None or _url_is_loopback(prev.get("primary_ui") or ""):
                by_project[key] = {
                    "project": project or addr,
                    "title": surface_title(project or ""),
                    "engine_target": addr,
                    "primary_ui": ui,
                }
        peers = await query_peer(addr, kind=zpb.SERVER_QUERY_KIND_PEERS)
        if peers is None:
            continue
        for peer in peers.peers:
            tgt = (peer.target or "").strip()
            if tgt:
                queue.append((peer.project or "", tgt))
    return sorted(by_project.values(), key=lambda row: row["project"])


def _url_is_loopback(url: str) -> bool:
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    return is_loopback_host(host)


def configured_peers(services: object) -> list[tuple[str, str]]:
    """Peers from engine config. Empty is honest — do not invent Ægir/Atelier."""
    config = getattr(services, "config", None)
    if config is None:
        return []
    fed = getattr(config, "federation", None)
    if fed is None and hasattr(config, "get"):
        try:
            fed = config.get("federation")
        except Exception:
            fed = None
    if fed is None:
        return []
    peers = getattr(fed, "peers", None)
    if peers is None and isinstance(fed, dict):
        peers = fed.get("peers")
    if not peers:
        return []
    out: list[tuple[str, str]] = []
    for peer in peers:
        if isinstance(peer, dict):
            pid = str(peer.get("id") or peer.get("project") or "")
            target = str(peer.get("endpoint") or peer.get("target") or "")
        else:
            pid = str(getattr(peer, "id", "") or getattr(peer, "project", ""))
            target = str(
                getattr(peer, "endpoint", "") or getattr(peer, "target", "")
            )
        target = target.replace("grpc://", "").strip()
        if pid and target:
            out.append((pid, target))
    return out


async def query_peer(
    target: str,
    *,
    kind: int = zpb.SERVER_QUERY_KIND_REMOTES,
    ttl: int = 0,
    nonce: str = "",
    origin_project: str = "gaius",
    note_id: str = "",
) -> zpb.ServerQueryResponse | None:
    """Ask a lattice peer ServerQuery. UNIMPLEMENTED → None (recorded by caller)."""
    import grpc
    from grpc import aio

    from .generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    addr = target.replace("grpc://", "").strip()
    channel = aio.insecure_channel(addr)
    try:
        stub = zpb_grpc.EngineStub(channel)
        return await stub.ServerQuery(
            zpb.ServerQueryRequest(
                kind=kind,
                ttl=ttl,
                nonce=nonce,
                origin_project=origin_project,
                note_id=note_id,
            ),
            timeout=10,
        )
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            logger.info(
                "ServerQuery UNIMPLEMENTED at %s — peer has not adopted S2S yet",
                addr,
            )
            return None
        logger.warning("ServerQuery failed at %s: %s %s", addr, e.code(), e.details())
        return None
    finally:
        await channel.close()


def local_response(
    kind: int,
    services: object,
    *,
    root: Path | None = None,
) -> zpb.ServerQueryResponse:
    """Answer a ServerQuery from this checkout. Unknown kind → empty payload."""
    resp = zpb.ServerQueryResponse(project="gaius")
    if kind in (
        zpb.SERVER_QUERY_KIND_UNSPECIFIED,
        zpb.SERVER_QUERY_KIND_REMOTES,
    ):
        remotes = list_named_remotes(root)
        resp.remotes.extend(
            zpb.GitRemote(name=name, url=url) for name, url in remotes
        )
        resp.head = advertised_head(root)
    if kind == zpb.SERVER_QUERY_KIND_PEERS:
        resp.peers.extend(
            zpb.PeerHint(project=pid, target=tgt)
            for pid, tgt in configured_peers(services)
        )
    if kind == zpb.SERVER_QUERY_KIND_SURFACES:
        for surf in local_surfaces():
            resp.surfaces.append(surf)
    if kind == zpb.SERVER_QUERY_KIND_QUEUES:
        resp.queues.extend(declared_queues())
    if kind == zpb.SERVER_QUERY_KIND_WORKLOADS:
        resp.workloads.extend(declared_workloads())
    # SCHEDULES: empty until the catalog lands (P3). Honest, not invented.
    return resp


def declared_queues() -> list[zpb.QueueHint]:
    """Leaves this engine needs. Signals merges + PromoteScratch. No YK REST."""
    from gaius.engine.sentinel_claim import (
        COMPUTE,
        EMBEDDING,
        EXTRACT,
        HEAVY,
        LIGHT,
        MEDIUM,
    )

    return [
        zpb.QueueHint(
            path=LIGHT.queue,
            resource_class=LIGHT.name,
            gpu_guarantee=1,
            gpu_max=2,
            max_applications=LIGHT.max_applications,
            preemption_delay="5s",
            role="light",
            examples="gaius.ask-agent",
        ),
        zpb.QueueHint(
            path=MEDIUM.queue,
            resource_class=MEDIUM.name,
            gpu_guarantee=2,
            gpu_max=2,
            max_applications=MEDIUM.max_applications,
            preemption_delay="5s",
            role="medium",
            examples="gaius.ask-sae",
        ),
        zpb.QueueHint(
            path=HEAVY.queue,
            resource_class=HEAVY.name,
            gpu_guarantee=4,
            gpu_max=4,
            max_applications=HEAVY.max_applications,
            preemption_policy="fence",
            role="heavy",
            examples="gaius.thinking",
        ),
        zpb.QueueHint(
            path=EMBEDDING.queue,
            resource_class=EMBEDDING.name,
            gpu_guarantee=1,
            gpu_max=1,
            max_applications=EMBEDDING.max_applications,
            role="embedding",
            examples="gaius.embedding",
        ),
        zpb.QueueHint(
            path=EXTRACT.queue,
            resource_class=EXTRACT.name,
            gpu_guarantee=0,
            gpu_max=2,
            max_applications=EXTRACT.max_applications,
            role="offline",
            examples="gaius.article-curate",
        ),
        zpb.QueueHint(
            path=COMPUTE.queue,
            resource_class=COMPUTE.name,
            gpu_guarantee=0,
            gpu_max=0,
            max_applications=COMPUTE.max_applications,
            role="offline",
            examples="gaius.optillm",
        ),
    ]


def declared_workloads() -> list:
    """WRK model + capabilities + tp/pp. Queue names stay resource-class FQNs."""
    return [
        zpb.WorkloadHint(
            wrk="thinking",
            model="Qwen/Qwen3.8-27B",
            capabilities=["thinking", "complete"],
            tensor_parallel=4,
            pipeline_parallel=1,
            gpu_tokens=4,
        ),
        zpb.WorkloadHint(
            wrk="ask-sae",
            model="Qwen/Qwen3-8B",
            capabilities=["complete"],
            tensor_parallel=2,
            pipeline_parallel=1,
            gpu_tokens=2,
        ),
        zpb.WorkloadHint(
            wrk="ask-agent",
            model="Qwen/Qwen3-1.7B",
            capabilities=["complete"],
            tensor_parallel=1,
            pipeline_parallel=1,
            gpu_tokens=1,
        ),
        zpb.WorkloadHint(
            wrk="optillm",
            model="proxy",
            capabilities=["complete"],
            tensor_parallel=0,
            pipeline_parallel=0,
            gpu_tokens=0,
        ),
        zpb.WorkloadHint(
            wrk="article-curate",
            model="",
            capabilities=["extract"],
            tensor_parallel=0,
            pipeline_parallel=0,
            gpu_tokens=1,
        ),
        zpb.WorkloadHint(
            wrk="embedding",
            model="lightonai/ColBERT-Zero",
            capabilities=["open-embedding"],
            tensor_parallel=1,
            pipeline_parallel=1,
            gpu_tokens=1,
        ),
    ]


def attach_local_note(resp: zpb.ServerQueryResponse, note_id: str) -> None:
    """Fill WikiNote from the local KB. Missing page → empty note (honest)."""
    if not (note_id or "").strip():
        return
    try:
        from gaius.engine.services.agenda_notes import kb_root_from_env
        from gaius.engine.services.summary_lineup import (
            SummaryLineupError,
            get_note,
        )

        note = get_note(kb_root_from_env(), note_id)
    except (SummaryLineupError, OSError):
        return
    resp.note.id = note.id
    resp.note.title = note.title
    resp.note.body = note.body
    resp.note.links.extend(note.links)
    resp.note.origin_project = note.origin_project or "gaius"
