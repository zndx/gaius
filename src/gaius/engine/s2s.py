"""Server-to-server query helpers (signals-protocol Engine/ServerQuery).

Matrix S2S Queries: pairwise snapshot. Not epidemic gossip. Not CZMQ zgossip.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

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


def local_primary_ui() -> str:
    """This engine's advertised board URL. Env only — do not invent peer UIs."""
    raw = (os.environ.get("GAIUS_PRIMARY_UI") or "").strip()
    if raw:
        return raw
    bind = (os.environ.get("GAIUS_UI_BIND") or "0.0.0.0:9890").strip()
    port = bind.rsplit(":", 1)[-1]
    if port.isdigit():
        return f"http://127.0.0.1:{port}"
    return ""


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
    """S2S: PEERS + Status.surfaces. Only peers that advertise a primary UI."""
    queue: list[tuple[str, str]] = list(configured_peers(services))
    queue.extend(directory_seeds())
    seen: set[str] = set()
    found: list[dict[str, str]] = []
    while queue:
        hint_project, target = queue.pop(0)
        addr = target.replace("grpc://", "").strip()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        status = await status_peer(addr)
        if status is None:
            continue
        project = (status.project or hint_project or "").strip()
        if project and project == skip_project:
            continue
        ui = primary_ui_of(status)
        if ui:
            found.append(
                {
                    "project": project or addr,
                    "engine_target": addr,
                    "primary_ui": ui,
                }
            )
        peers = await query_peer(addr, kind=zpb.SERVER_QUERY_KIND_PEERS)
        if peers is None:
            continue
        for peer in peers.peers:
            tgt = (peer.target or "").strip()
            if tgt:
                queue.append((peer.project or "", tgt))
    found.sort(key=lambda row: row["project"])
    return found


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
    # SCHEDULES: empty until the catalog lands (P3). Honest, not invented.
    return resp


def declared_queues() -> list[zpb.QueueHint]:
    """Leaves this engine needs. Signals merges + PromoteScratch. No YK REST."""
    from gaius.engine.sentinel_claim import EXTRACT, HEAVY, LIGHT, MEDIUM

    return [
        zpb.QueueHint(
            path=LIGHT.queue,
            resource_class=LIGHT.name,
            gpu_guarantee=1,
            gpu_max=2,
            max_applications=2,
            preemption_delay="5s",
            role="light",
            examples="gaius.ask-agent;1.7b",
        ),
        zpb.QueueHint(
            path=MEDIUM.queue,
            resource_class=MEDIUM.name,
            gpu_guarantee=2,
            gpu_max=2,
            max_applications=1,
            preemption_delay="5s",
            role="medium",
            examples="gaius.ask-sae;9b-tp2",
        ),
        zpb.QueueHint(
            path=HEAVY.queue,
            resource_class=HEAVY.name,
            gpu_guarantee=4,
            gpu_max=4,
            max_applications=2,
            preemption_policy="fence",
            role="heavy",
            examples="gaius.thinking;tp4-27b",
        ),
        zpb.QueueHint(
            path=EXTRACT.queue,
            resource_class=EXTRACT.name,
            gpu_guarantee=0,
            gpu_max=2,
            max_applications=16,
            role="offline",
            examples="gaius.extract;docling",
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
