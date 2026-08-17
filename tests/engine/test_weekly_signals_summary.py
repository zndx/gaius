"""Weekly Signals Summary: S2S participants only, wWW-summary zettel."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.services.weekly_signals_summary import (
    WeeklySummaryError,
    discover_participants,
    gather_commits,
    gather_notes,
    list_summaries,
    parse_iso_week,
    read_summary,
    render_facts,
    run_weekly_summary,
    zettel_name,
    zettel_relpath,
)
from gaius.engine.s2s import list_named_remotes


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "gaius"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ws@test")
    _git(repo, "config", "user.name", "ws")
    (repo / "README").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")
    _git(repo, "remote", "add", "origin", "git@github.com:zndx/gaius.git")
    _git(repo, "remote", "add", "internal", "/raid/repos/zndx-gaius")
    return repo


def test_parse_iso_week_and_skewer() -> None:
    now = datetime(2026, 8, 17, 16, 5, 0, tzinfo=timezone.utc)
    current = parse_iso_week("", now=now)
    assert current.label == "2026-W34"
    assert current.start.isoformat() == "2026-08-17T00:00:00+00:00"
    prev = parse_iso_week("", now=now, previous=True)
    assert prev.label == "2026-W33"
    named = parse_iso_week("2026-W33", now=now)
    assert named.label == "2026-W33"
    assert zettel_name(current, now) == "2026-08-17-160500_w34-summary.md"
    assert zettel_relpath(current, now) == (
        "scratch/2026-08-17/2026-08-17-160500_w34-summary.md"
    )


def test_bad_week_fails_fast() -> None:
    with pytest.raises(WeeklySummaryError, match="WS.00000002"):
        parse_iso_week("34")
    with pytest.raises(WeeklySummaryError, match="WS.00000002"):
        parse_iso_week("2026-W99")


def test_gather_commits_from_observed_remote(git_repo: Path) -> None:
    from gaius.engine.services.weekly_signals_summary import Participant, RemoteRef

    window = parse_iso_week("2026-W34", now=datetime(2026, 8, 17, tzinfo=timezone.utc))
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-08-17T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-08-17T12:00:00+00:00",
    }
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "--allow-empty", "-m", "server query"],
        check=True,
        capture_output=True,
        env=env,
    )
    remotes = [RemoteRef(name=n, url=u) for n, u in list_named_remotes(git_repo)]
    p = Participant(
        project="gaius",
        remotes=remotes,
        head="abc",
        source="s2s-local",
        checkout=git_repo,
    )
    commits = gather_commits(p, window)
    subjects = {c.subject for c in commits}
    assert "server query" in subjects
    # origin has no tracking refs yet — do not invent
    assert all(c.ref == "HEAD" or c.ref.startswith("origin") for c in commits)


def test_gather_notes_only_in_window(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch" / "2026-08-16").mkdir(parents=True)
    (kb / "scratch" / "2026-08-17").mkdir()
    (kb / "scratch" / "2026-08-16" / "2026-08-16-010000_old.md").write_text(
        "# Old\n", encoding="utf-8"
    )
    (kb / "scratch" / "2026-08-17" / "2026-08-17-010000_in.md").write_text(
        "# In week\n", encoding="utf-8"
    )
    window = parse_iso_week("2026-W34")
    notes = gather_notes([kb], window)
    assert [n.title for n in notes] == ["In week"]


@pytest.mark.asyncio
async def test_discover_skips_unimplemented_peers(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAIUS_REPO_ROOT", str(git_repo))
    services = SimpleNamespace(
        config=SimpleNamespace(
            federation=SimpleNamespace(
                peers=[{"id": "signals", "endpoint": "127.0.0.1:50151"}]
            )
        )
    )
    monkeypatch.setattr(
        "gaius.engine.services.weekly_signals_summary.query_peer",
        AsyncMock(return_value=None),
    )
    found = await discover_participants(services)
    assert [p.project for p in found] == ["gaius"]
    assert {r.name for r in found[0].remotes} == {"origin", "internal"}


@pytest.mark.asyncio
async def test_discover_includes_peer_that_answers(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAIUS_REPO_ROOT", str(git_repo))
    services = SimpleNamespace(
        config=SimpleNamespace(
            federation=SimpleNamespace(
                peers=[{"id": "signals", "endpoint": "127.0.0.1:50151"}]
            )
        )
    )
    peer = zpb.ServerQueryResponse(project="signals", head="deadbeef")
    peer.remotes.add(name="origin", url="git@github.com:weathership/signals.git")

    async def _peer(_target: str, **_kw: object) -> zpb.ServerQueryResponse:
        return peer

    monkeypatch.setattr(
        "gaius.engine.services.weekly_signals_summary.query_peer",
        _peer,
    )
    found = await discover_participants(services)
    assert [p.project for p in found] == ["gaius", "signals"]
    assert found[1].checkout is None
    assert found[1].remotes[0].url.endswith("signals.git")


@pytest.mark.asyncio
async def test_run_writes_www_summary_and_lists(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    monkeypatch.setenv("GAIUS_REPO_ROOT", str(git_repo))
    monkeypatch.setenv("GAIUS_KB_ROOT", str(kb))
    now = datetime(2026, 8, 17, 16, 22, 11, tzinfo=timezone.utc)

    async def _compose(facts: str) -> str:
        assert "gaius" in facts
        assert "signals.git" not in facts
        return "## Readout\n\nGaius remotes moved. No other S2S participants."

    result = await run_weekly_summary(
        week="2026-W34",
        now=now,
        kb=kb,
        services=SimpleNamespace(config=None),
        composer=_compose,
    )
    assert result.path == "scratch/2026-08-17/2026-08-17-162211_w34-summary.md"
    assert result.acp_used
    body = (kb / result.path).read_text(encoding="utf-8")
    assert body.startswith("# Weekly Signals Summary · 2026-W34")
    assert "origin: `git@github.com:zndx/gaius.git`" in body
    assert "## Readout" in body
    listed = list_summaries(kb)
    assert listed[0]["path"] == result.path
    assert "w34-summary" in listed[0]["path"]
    assert "Gaius remotes" in read_summary(kb, result.path)


@pytest.mark.asyncio
async def test_compose_strips_preamble() -> None:
    from gaius.engine.services.weekly_signals_summary import compose_readout

    async def _compose(_facts: str) -> str:
        return "thinking out loud\n## Readout\n\nOnly listed facts."

    text = await compose_readout("facts", composer=_compose)
    assert text.startswith("## Readout")
    assert "thinking out loud" not in text


def test_read_rejects_non_summary(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch" / "2026-08-17").mkdir(parents=True)
    rel = "scratch/2026-08-17/2026-08-17-010000_other.md"
    (kb / rel).write_text("nope\n", encoding="utf-8")
    with pytest.raises(WeeklySummaryError, match="WS.00000004"):
        read_summary(kb, rel)


def test_render_peer_without_checkout_is_honest() -> None:
    from gaius.engine.services.weekly_signals_summary import Participant, RemoteRef

    window = parse_iso_week("2026-W34")
    facts = render_facts(
        window,
        [
            Participant(
                project="signals",
                remotes=[RemoteRef("origin", "git@example/signals.git")],
                head="abc",
                source="s2s-peer",
                checkout=None,
            )
        ],
        [],
        [],
    )
    assert "no local checkout" in facts
    assert "sdg-" not in facts
