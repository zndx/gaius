"""Server-to-server remotes: named git remotes, no invented URLs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.grpc.servicers.zndx_engine_servicer import GaiusZndxEngineServicer
from gaius.engine.s2s import (
    ServerQueryError,
    advertised_head,
    collect_peer_surfaces,
    declared_queues,
    list_named_remotes,
    local_primary_ui,
    local_response,
    local_surfaces,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "s2s@test")
    _git(repo, "config", "user.name", "s2s")
    (repo / "README").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")
    _git(repo, "remote", "add", "origin", "git@github.com:zndx/example.git")
    _git(repo, "remote", "add", "internal", "/raid/repos/example.git")
    return repo


def test_list_named_remotes_is_key_value(git_repo: Path) -> None:
    remotes = dict(list_named_remotes(git_repo))
    assert remotes["origin"] == "git@github.com:zndx/example.git"
    assert remotes["internal"] == "/raid/repos/example.git"
    assert advertised_head(git_repo)


def test_missing_repo_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ServerQueryError, match="SS.00000002"):
        list_named_remotes(tmp_path)


def test_local_response_remotes(git_repo: Path) -> None:
    resp = local_response(
        zpb.SERVER_QUERY_KIND_REMOTES,
        SimpleNamespace(config=None),
        root=git_repo,
    )
    assert resp.project == "gaius"
    names = {r.name: r.url for r in resp.remotes}
    assert names["origin"].endswith("example.git")
    assert names["internal"] == "/raid/repos/example.git"
    assert resp.head


def test_local_surfaces_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAIUS_PRIMARY_UI", "http://127.0.0.1:9890")
    surf = local_surfaces()
    assert len(surf) == 1
    assert surf[0].kind == "primary"
    assert surf[0].url == "http://127.0.0.1:9890"
    assert local_primary_ui() == "http://127.0.0.1:9890"


def test_local_response_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAIUS_PRIMARY_UI", "http://127.0.0.1:9890")
    resp = local_response(
        zpb.SERVER_QUERY_KIND_SURFACES,
        SimpleNamespace(config=None),
    )
    assert [s.url for s in resp.surfaces] == ["http://127.0.0.1:9890"]


@pytest.mark.asyncio
async def test_collect_skips_peers_without_primary_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _status(target: str):
        return zpb.StatusResponse(project="signals", endpoints=[], total_gpus=0)

    async def _query(*_a, **_k):
        return zpb.ServerQueryResponse(project="signals")

    monkeypatch.setattr("gaius.engine.s2s.status_peer", _status)
    monkeypatch.setattr("gaius.engine.s2s.query_peer", _query)
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", "127.0.0.1:50551")
    rows = await collect_peer_surfaces(SimpleNamespace(config=None))
    assert rows == []


@pytest.mark.asyncio
async def test_collect_lists_advertised_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _status(target: str):
        return zpb.StatusResponse(
            project="signals",
            surfaces=[
                zpb.Surface(
                    kind="primary",
                    url="http://127.0.0.1:9889",
                    healthy=True,
                )
            ],
        )

    async def _query(*_a, **_k):
        return zpb.ServerQueryResponse(project="signals")

    monkeypatch.setattr("gaius.engine.s2s.status_peer", _status)
    monkeypatch.setattr("gaius.engine.s2s.query_peer", _query)
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", "127.0.0.1:50551")
    rows = await collect_peer_surfaces(SimpleNamespace(config=None))
    assert rows == [
        {
            "project": "signals",
            "engine_target": "127.0.0.1:50551",
            "primary_ui": "http://127.0.0.1:9889",
        }
    ]


def test_declared_queues_light_medium_heavy() -> None:
    paths = {q.path for q in declared_queues()}
    assert "root.internal.inference.light" in paths
    assert "root.internal.inference.medium" in paths
    assert "root.internal.inference.heavy" in paths
    light = next(q for q in declared_queues() if q.role == "light")
    assert light.gpu_guarantee == 1
    med = next(q for q in declared_queues() if q.role == "medium")
    assert med.gpu_max == 2


def test_local_response_peers_empty_is_honest() -> None:
    resp = local_response(
        zpb.SERVER_QUERY_KIND_PEERS,
        SimpleNamespace(config=None),
    )
    assert list(resp.peers) == []


@pytest.mark.asyncio
async def test_server_query_rpc(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAIUS_REPO_ROOT", str(git_repo))
    servicer = GaiusZndxEngineServicer(SimpleNamespace(config=None))
    resp = await servicer.ServerQuery(
        zpb.ServerQueryRequest(
            kind=zpb.SERVER_QUERY_KIND_REMOTES,
            origin_project="gaius",
        ),
        MagicMock(),
    )
    assert resp.project == "gaius"
    assert any(r.name == "origin" for r in resp.remotes)


@pytest.mark.asyncio
async def test_server_query_git_miss_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAIUS_REPO_ROOT", str(tmp_path))
    servicer = GaiusZndxEngineServicer(SimpleNamespace(config=None))
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=grpc.aio.AbortError("failed"))
    with pytest.raises(grpc.aio.AbortError):
        await servicer.ServerQuery(
            zpb.ServerQueryRequest(kind=zpb.SERVER_QUERY_KIND_REMOTES),
            ctx,
        )
    assert "SS.00000002" in ctx.abort.await_args.args[1]
