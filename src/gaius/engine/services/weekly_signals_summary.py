"""Weekly Signals Summary from S2S-participating remotes.

Only projects that answer Engine/ServerQuery REMOTES participate.
Gaius is the first. Peers join when they implement signals-protocol
ServerQuery — do not walk sibling checkouts (Signals, sdg-*) as a stand-in.

Scratch zettel: scratch/YYYY-MM-DD/YYYY-MM-DD-HHmmss_wWW-summary.md
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.s2s import (
    advertised_head,
    configured_peers,
    local_response,
    query_peer,
    repo_root,
)
from gaius.engine.services.agenda_notes import (
    AgendaError,
    jail_path,
    kb_root_from_env,
    require_kb,
)

logger = logging.getLogger(__name__)

NAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{6})_w(?P<week>\d{2})-summary\.md$"
)
ISO_WEEK = re.compile(r"^(?P<year>\d{4})-[wW](?P<week>\d{1,2})$")

GURU_NOKB = (
    "Knowledge base root missing or not a directory.\n"
    "  Guru: #WS.00000001.NOKB\n"
    "  Try: set GAIUS_KB_ROOT (default build/dev)"
)
GURU_BADWEEK = (
    "ISO week must be YYYY-Www (e.g. 2026-W34).\n"
    "  Guru: #WS.00000002.BADWEEK"
)
GURU_ACPFAIL = (
    "ACP could not compose the weekly Signals Summary.\n"
    "  Guru: #WS.00000003.ACPFAIL\n"
    "  Try: grok login --device-auth (or set acp.agent)\n"
    "  Or:  /health fix engine"
)
GURU_BADPATH = (
    "Weekly summary path must stay under scratch/ and match *_wWW-summary.md.\n"
    "  Guru: #WS.00000004.BADPATH"
)


class WeeklySummaryError(RuntimeError):
    """Fail-fast weekly Signals Summary error with guru in the message."""


class Composer(Protocol):
    async def __call__(self, facts: str) -> str: ...


@dataclass(frozen=True)
class RemoteRef:
    name: str
    url: str


@dataclass
class Participant:
    project: str
    remotes: list[RemoteRef]
    head: str
    source: str
    checkout: Path | None = None


@dataclass(frozen=True)
class CommitLine:
    project: str
    sha: str
    when: str
    subject: str
    ref: str


@dataclass(frozen=True)
class NoteLine:
    path: str
    title: str


@dataclass
class WeekWindow:
    year: int
    week: int
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"{self.year}-W{self.week:02d}"


@dataclass
class WeeklySummary:
    week: WeekWindow
    path: str
    body: str
    participants: list[Participant]
    commits: list[CommitLine]
    notes: list[NoteLine]
    acp_used: bool


def parse_iso_week(raw: str, *, now: datetime | None = None, previous: bool = False) -> WeekWindow:
    """Resolve YYYY-Www, or the ISO week containing `now` (optionally previous)."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    text = (raw or "").strip()
    if text:
        m = ISO_WEEK.match(text)
        if not m:
            raise WeeklySummaryError(GURU_BADWEEK)
        year = int(m.group("year"))
        week = int(m.group("week"))
        if week < 1 or week > 53:
            raise WeeklySummaryError(GURU_BADWEEK)
        try:
            start_date = date.fromisocalendar(year, week, 1)
        except ValueError as e:
            raise WeeklySummaryError(GURU_BADWEEK) from e
    else:
        iso = clock.isocalendar()
        year, week = iso.year, iso.week
        if previous:
            start_date = date.fromisocalendar(year, week, 1) - timedelta(days=7)
            year, week, _ = start_date.isocalendar()
        else:
            start_date = date.fromisocalendar(year, week, 1)
    start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    return WeekWindow(year=year, week=week, start=start, end=end)


def zettel_name(week: WeekWindow, now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return f"{stamp}_w{week.week:02d}-summary.md"


def zettel_relpath(week: WeekWindow, now: datetime) -> str:
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return f"scratch/{day}/{zettel_name(week, now)}"


def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        from gaius.engine.s2s import GURU_NOGIT

        raise WeeklySummaryError(GURU_NOGIT) from e


def _tracking_refs(checkout: Path, remote: str) -> list[str]:
    proc = _git(
        checkout,
        "for-each-ref",
        "--format=%(refname:short)",
        f"refs/remotes/{remote}",
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def gather_commits(
    participant: Participant,
    window: WeekWindow,
) -> list[CommitLine]:
    """Commits observable in this checkout for the advertised remotes.

    No checkout → no invented log. Missing remote-tracking refs → skip that remote.
    """
    checkout = participant.checkout
    if checkout is None:
        return []
    since = window.start.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = window.end.strftime("%Y-%m-%dT%H:%M:%SZ")
    refs = ["HEAD"]
    for remote in participant.remotes:
        refs.extend(_tracking_refs(checkout, remote.name))
    seen: set[str] = set()
    out: list[CommitLine] = []
    for ref in refs:
        proc = _git(
            checkout,
            "log",
            ref,
            f"--since={since}",
            f"--until={until}",
            "--pretty=format:%H\t%cI\t%s",
        )
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            sha, when, subject = parts[0], parts[1], parts[2]
            if sha in seen:
                continue
            seen.add(sha)
            out.append(
                CommitLine(
                    project=participant.project,
                    sha=sha,
                    when=when,
                    subject=subject,
                    ref=ref,
                )
            )
    out.sort(key=lambda c: c.when, reverse=True)
    return out


def _note_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path.stem
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem


def gather_notes(roots: list[Path], window: WeekWindow) -> list[NoteLine]:
    """Scratch notes whose directory date falls in [start, end). Do not invent."""
    out: list[NoteLine] = []
    day = window.start.date()
    end = window.end.date()
    while day < end:
        stamp = day.isoformat()
        for root in roots:
            folder = root / "scratch" / stamp
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.md")):
                rel = f"scratch/{stamp}/{path.name}"
                out.append(NoteLine(path=rel, title=_note_title(path)))
        day += timedelta(days=1)
    return out


def note_roots(kb: Path, checkout: Path | None) -> list[Path]:
    roots = [kb]
    if checkout is not None:
        docs = checkout / "docs"
        if docs.is_dir() and docs.resolve() != kb.resolve():
            roots.append(docs)
    return roots


async def discover_participants(services: object | None = None) -> list[Participant]:
    """Local ServerQuery remotes plus peers that actually answer REMOTES."""
    svc = services if services is not None else SimpleNamespace(config=None)
    local = local_response(zpb.SERVER_QUERY_KIND_REMOTES, svc)
    checkout = repo_root()
    participants = [
        Participant(
            project=local.project or "gaius",
            remotes=[RemoteRef(name=r.name, url=r.url) for r in local.remotes],
            head=local.head or advertised_head(checkout),
            source="s2s-local",
            checkout=checkout,
        )
    ]
    for pid, target in configured_peers(svc):
        resp = await query_peer(target, kind=zpb.SERVER_QUERY_KIND_REMOTES)
        if resp is None:
            logger.info(
                "S2S peer %s at %s has not adopted ServerQuery — skipped",
                pid,
                target,
            )
            continue
        participants.append(
            Participant(
                project=resp.project or pid,
                remotes=[RemoteRef(name=r.name, url=r.url) for r in resp.remotes],
                head=resp.head,
                source="s2s-peer",
                checkout=None,
            )
        )
    return participants


def render_facts(
    window: WeekWindow,
    participants: list[Participant],
    commits: list[CommitLine],
    notes: list[NoteLine],
) -> str:
    lines = [
        f"# Weekly Signals Summary · {window.label}",
        "",
        f"Window (UTC): {window.start.isoformat()} → {window.end.isoformat()} (exclusive).",
        "Participants are engines that answered `Engine/ServerQuery` REMOTES.",
        "Peers that have not implemented signals-protocol ServerQuery are omitted.",
        "",
        "## Remotes",
        "",
    ]
    for p in participants:
        lines.append(f"### {p.project} ({p.source})")
        if p.head:
            lines.append(f"- head: `{p.head}`")
        if not p.remotes:
            lines.append("- remotes: none advertised")
        for r in p.remotes:
            lines.append(f"- {r.name}: `{r.url}`")
        if p.checkout is None:
            lines.append(
                "- commits: no local checkout — remotes observed via ServerQuery only"
            )
        lines.append("")
    lines.append("## Commits")
    lines.append("")
    if not commits:
        lines.append("No commits in this window on observed checkouts.")
        lines.append("")
    else:
        current = ""
        for c in commits:
            if c.project != current:
                current = c.project
                lines.append(f"### {c.project}")
                lines.append("")
            lines.append(f"- `{c.sha[:12]}` {c.when} ({c.ref}) {c.subject}")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    if not notes:
        lines.append("No scratch notes in this window.")
        lines.append("")
    else:
        for n in notes:
            lines.append(f"- [[{n.path}]] — {n.title}")
        lines.append("")
    return "\n".join(lines)


ACP_PROMPT = """You are writing the weekly Signals Summary for the zndx federation.

Write a formal executive readout in Markdown. Use only the facts in the
context. Do not invent projects, remotes, commits, notes, or peers.

Rules:
- Cover only S2S participants listed (projects that answered ServerQuery REMOTES).
- Do not mention Signals, the protocol checkout, or sdg-* unless they appear
  as participants in the facts.
- No warehouse of unobserved remotes. Named remotes only as listed.
- Structure: one short headline, then What moved, Risks / open questions,
  Next week. Keep it tight.

Return Markdown only. The first line must be `## Readout`. No preamble."""


async def compose_readout(facts: str, composer: Composer | None = None) -> str:
    if composer is not None:
        text = await composer(facts)
    else:
        text = await _acp_compose(facts)
    body = (text or "").strip()
    if not body:
        raise WeeklySummaryError(GURU_ACPFAIL)
    idx = body.find("## Readout")
    if idx >= 0:
        body = body[idx:].strip()
    else:
        body = "## Readout\n\n" + body
    return body


async def _acp_compose(facts: str) -> str:
    try:
        from gaius.acp import ACPConfig, ACPConnectionError, GaiusACPClient
    except Exception as e:
        raise WeeklySummaryError(f"{GURU_ACPFAIL}\n  Error: {e}") from e
    cwd = os.environ.get("GAIUS_REPO_ROOT") or os.environ.get("DEVENV_ROOT") or os.getcwd()
    try:
        # Exec readout escalates to subscription grok-build. Default ACP
        # elsewhere is local thinking (Qwen3.8-27B).
        async with GaiusACPClient(
            ACPConfig(agent="grok", working_directory=cwd, include_gaius_mcp=False)
        ) as client:
            return await client.prompt(ACP_PROMPT, context={"facts": facts})
    except ACPConnectionError as e:
        raise WeeklySummaryError(f"{GURU_ACPFAIL}\n  Error: {e}") from e


def write_zettel(kb: Path, rel: str, body: str) -> Path:
    require_kb(kb)
    path = jail_path(kb, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return path


def list_summaries(kb: Path, *, limit: int = 12) -> list[dict[str, str]]:
    try:
        require_kb(kb)
    except AgendaError as e:
        raise WeeklySummaryError(GURU_NOKB) from e
    scratch = kb / "scratch"
    if not scratch.is_dir():
        return []
    found: list[tuple[str, str, str]] = []
    for path in scratch.glob("*/*_w??-summary.md"):
        m = NAME.match(path.name)
        if not m:
            continue
        rel = str(path.relative_to(kb)).replace("\\", "/")
        week = f"{m.group('date')[:4]}-W{m.group('week')}"
        # ISO year can differ near year boundaries; prefer folder date year
        # only as a display hint — week number is in the skewer.
        title = _note_title(path)
        found.append((rel, week, title))
    found.sort(key=lambda t: t[0], reverse=True)
    return [
        {"path": rel, "week": week, "title": title}
        for rel, week, title in found[: max(1, limit)]
    ]


def read_summary(kb: Path, rel: str) -> str:
    require_kb(kb)
    if not NAME.search(Path(rel).name):
        raise WeeklySummaryError(GURU_BADPATH)
    try:
        path = jail_path(kb, rel)
    except AgendaError as e:
        raise WeeklySummaryError(GURU_BADPATH) from e
    if not path.is_file():
        raise WeeklySummaryError(GURU_BADPATH)
    return path.read_text(encoding="utf-8")


async def run_weekly_summary(
    *,
    week: str = "",
    previous: bool = False,
    now: datetime | None = None,
    services: object | None = None,
    kb: Path | None = None,
    composer: Composer | None = None,
) -> WeeklySummary:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    window = parse_iso_week(week, now=clock, previous=previous)
    root = kb or kb_root_from_env()
    if not root.is_dir():
        raise WeeklySummaryError(GURU_NOKB)
    participants = await discover_participants(services)
    commits: list[CommitLine] = []
    for p in participants:
        commits.extend(gather_commits(p, window))
    local_checkout = next((p.checkout for p in participants if p.checkout), None)
    notes = gather_notes(note_roots(root, local_checkout), window)
    facts = render_facts(window, participants, commits, notes)
    rel = zettel_relpath(window, clock)
    write_zettel(root, rel, facts)
    try:
        readout = await compose_readout(facts, composer=composer)
    except WeeklySummaryError as e:
        raise WeeklySummaryError(f"{e}\n  Facts: {rel}") from e
    body = facts.rstrip() + "\n\n" + readout.strip() + "\n"
    write_zettel(root, rel, body)
    return WeeklySummary(
        week=window,
        path=rel,
        body=body,
        participants=participants,
        commits=commits,
        notes=notes,
        acp_used=True,
    )
