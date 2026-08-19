"""Temporal Summary lineup: FedWiki trail over the KB.

SECTION: ontology | heuristic
LENS: articles | projects | thoughts

The default seed is this ISO week's Signals Summary. Items are what
moved in that week (mtime) or what the weekly note already [[links]].
Empty intersections stay empty.

KNOWLEDGE (section=ontology|heuristic, no lens) is the standing collection
at current/ontology or current/heuristics. The generated summary.md is
the seed when present; notes are not week-filtered.

Fork copies a page into scratch with origin metadata. Peer fork uses
Engine/ServerQuery NOTE when the peer has adopted it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gaius.engine.services.agenda_notes import (
    AgendaError,
    kb_root_from_env,
    require_kb,
    skewer,
)
from gaius.engine.services.weekly_signals_summary import (
    NAME as WEEKLY_NAME,
    WeekWindow,
    WeeklySummaryError,
    list_summaries,
    parse_iso_week,
)

logger = logging.getLogger(__name__)

SECTIONS = ("corpus", "ontology", "heuristic")
LENSES = ("articles", "projects", "thoughts")
WIKI = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
TITLE_H = re.compile(r"^#\s+(.+)$", re.M)
ALLOWED_PREFIX = ("current/", "scratch/", "archive/", "lens/")

GURU_NOKB = (
    "Knowledge base root missing or not a directory.\n"
    "  Guru: #WS.00000001.NOKB\n"
    "  Try: set GAIUS_KB_ROOT (default build/dev)"
)
GURU_BADSECTION = (
    "Summary section must be corpus, ontology, or heuristic.\n"
    "  Guru: #WS.00000005.BADSECTION"
)
GURU_BADLENS = (
    "Summary lens must be articles, projects, or thoughts.\n"
    "  Guru: #WS.00000006.BADLENS"
)
GURU_NOLINK = (
    "Wiki target does not resolve to a Summary page.\n"
    "  Guru: #WS.00000007.NOLINK"
)
GURU_NOPAGE = (
    "Summary page not found.\n"
    "  Guru: #WS.00000008.NOPAGE"
)
GURU_NOTHOUGHT = (
    "That cognition thought is not in cognition_thoughts.\n"
    "  Guru: #WS.00000014.NOTHOUGHT\n"
    "  Try: open it from /cognition"
)
GURU_THOUGHTDB = (
    "Summary needs the engine database pool to load a thought.\n"
    "  Guru: #COG.00000025.NODB\n"
    "  Try: /health fix postgres"
)
THOUGHT_UUID = re.compile(
    r"^(?:thought/)?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
GURU_NOFORK = (
    "Cannot fork that page (virtual lens index, or peer NOTE unimplemented).\n"
    "  Guru: #WS.00000009.NOFORK"
)


class SummaryLineupError(RuntimeError):
    """Fail-fast Summary lineup error with guru in the message."""


@dataclass
class LineupNote:
    id: str
    title: str
    body: str = ""
    section: str = ""
    lens: str = ""
    week: str = ""
    mtime_ms: int = 0
    links: list[str] = field(default_factory=list)
    origin_project: str = "gaius"
    origin_id: str = ""
    excerpt: str = ""
    virtual: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "section": self.section,
            "lens": self.lens,
            "week": self.week,
            "mtime_ms": self.mtime_ms,
            "links": list(self.links),
            "origin_project": self.origin_project,
            "origin_id": self.origin_id,
            "excerpt": self.excerpt or _excerpt(self.body),
            "virtual": self.virtual,
        }


def validate_section(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s not in SECTIONS:
        raise SummaryLineupError(GURU_BADSECTION)
    return s


def validate_lens(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s not in LENSES:
        raise SummaryLineupError(GURU_BADLENS)
    return s


def extract_links(text: str) -> list[str]:
    seen: list[str] = []
    for m in WIKI.finditer(text or ""):
        target = m.group(1).strip()
        if target and target not in seen:
            seen.append(target)
    return seen


def _excerpt(text: str, n: int = 220) -> str:
    lines = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        lines.append(s)
        if sum(len(x) for x in lines) >= n:
            break
    blob = " ".join(lines)
    if len(blob) <= n:
        return blob
    return blob[: n - 1].rstrip() + "…"


def _title_of(text: str, fallback: str) -> str:
    m = TITLE_H.search(text or "")
    if m:
        return m.group(1).strip()
    return fallback


def _mtime_ms(path: Path) -> int:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return 0


def jail_kb(root: Path, rel: str) -> Path:
    rel = (rel or "").strip().lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise SummaryLineupError(GURU_NOPAGE)
    if not any(rel.startswith(p) for p in ALLOWED_PREFIX):
        raise SummaryLineupError(GURU_NOPAGE)
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as e:
        raise SummaryLineupError(GURU_NOPAGE) from e
    return path


def lens_id(section: str, lens: str) -> str:
    if section and lens:
        return f"lens/{section}/{lens}"
    if lens:
        return f"lens/{lens}"
    return "lens/week"


def _in_week(mtime_ms: int, window: WeekWindow) -> bool:
    if not mtime_ms:
        return False
    ts = datetime.fromtimestamp(mtime_ms / 1000, tz=timezone.utc)
    return window.start <= ts < window.end


def _section_of_path(rel: str) -> str:
    if rel.startswith("current/ontology/") or rel.startswith("current/ontology"):
        return "ontology"
    if rel.startswith("current/heuristics/"):
        return "heuristic"
    return ""


def _lens_of_path(rel: str) -> str:
    if rel.startswith("current/articles/"):
        return "articles"
    if rel.startswith("current/projects/"):
        return "projects"
    if "thoughts" in Path(rel).name or rel.startswith("scratch/"):
        return "thoughts"
    return ""


def _touches_section(note: LineupNote, section: str) -> bool:
    if not section:
        return True
    if note.section == section:
        return True
    if any(section in link or _section_of_path(link) == section for link in note.links):
        return True
    blob = f"{note.id} {note.title} {note.body}".lower()
    if section == "ontology":
        return "ontology" in blob or "owl" in blob
    if section == "heuristic":
        return "heuristic" in blob or "guru" in blob or "#ws." in blob or "#ag." in blob
    return False


def _read_file_note(kb: Path, rel: str, window: WeekWindow) -> LineupNote:
    path = jail_kb(kb, rel)
    if not path.is_file():
        raise SummaryLineupError(GURU_NOPAGE)
    text = path.read_text(encoding="utf-8", errors="replace")
    return LineupNote(
        id=rel.replace("\\", "/"),
        title=_title_of(text, path.stem),
        body=text,
        section=_section_of_path(rel),
        lens=_lens_of_path(rel),
        week=window.label,
        mtime_ms=_mtime_ms(path),
        links=extract_links(text),
        excerpt=_excerpt(text),
    )


def _article_cards(kb: Path) -> list[Path]:
    root = kb / "current" / "articles"
    if not root.is_dir():
        return []
    out: list[Path] = []
    for slug in sorted(p for p in root.iterdir() if p.is_dir()):
        for name in ("article.md", "base.md"):
            cand = slug / name
            if cand.is_file():
                out.append(cand)
                break
    return out


def _project_cards(kb: Path) -> list[Path]:
    root = kb / "current" / "projects"
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith("."):
            continue
        rel_depth = len(p.relative_to(root).parts)
        if rel_depth <= 2:
            out.append(p)
    return out


def _ontology_cards(kb: Path) -> list[Path]:
    root = kb / "current" / "ontology"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def _heuristic_cards(kb: Path) -> list[Path]:
    root = kb / "current" / "heuristics"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def _thought_files(kb: Path, window: WeekWindow) -> list[Path]:
    scratch = kb / "scratch"
    if not scratch.is_dir():
        return []
    out: list[Path] = []
    day = window.start.date()
    end = window.end.date()
    from datetime import timedelta

    while day < end:
        folder = scratch / day.isoformat()
        if folder.is_dir():
            for p in sorted(folder.glob("*.md")):
                name = p.name.lower()
                if "thought" in name or "cognition" in name:
                    out.append(p)
        day += timedelta(days=1)
    return out


def _thought_files_latest(kb: Path, limit: int) -> list[Path]:
    """Agentic thought notes, newest date folders first. Not a directory walk of the 90s."""
    scratch = kb / "scratch"
    if not scratch.is_dir():
        return []
    days = sorted(
        (p for p in scratch.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    out: list[Path] = []
    for folder in days:
        hits = [
            p
            for p in folder.glob("*.md")
            if "thought" in p.name.lower() or "cognition" in p.name.lower()
        ]
        hits.sort(key=lambda p: p.name, reverse=True)
        out.extend(hits)
        if len(out) >= limit:
            return out[:limit]
    return out


def _rel(kb: Path, path: Path) -> str:
    return str(path.relative_to(kb)).replace("\\", "/")


def collect_candidates(kb: Path, lens: str) -> list[Path]:
    if lens == "articles":
        return _article_cards(kb)
    if lens == "projects":
        return _project_cards(kb)
    if lens == "thoughts":
        return []
    return []


def weekly_landing(kb: Path, window: WeekWindow) -> str:
    for item in list_summaries(kb, limit=24):
        if item.get("week") == window.label or WEEKLY_NAME.match(Path(item["path"]).name):
            if item.get("week") == window.label:
                return item["path"]
    for item in list_summaries(kb, limit=1):
        return item["path"]
    return ""


def _linked_from(weekly: LineupNote | None) -> set[str]:
    if weekly is None:
        return set()
    return set(weekly.links)


async def _db_thoughts(
    db_pool: object | None,
    window: WeekWindow,
    limit: int,
    *,
    latest: bool = False,
) -> list[LineupNote]:
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:  # type: ignore[union-attr]
            if latest:
                rows = await conn.fetch(
                    """
                    SELECT id, thought_type, title, summary, content, created_at, note_path
                    FROM cognition_thoughts
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, thought_type, title, summary, content, created_at, note_path
                    FROM cognition_thoughts
                    WHERE created_at >= $1 AND created_at < $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    window.start,
                    window.end,
                    limit,
                )
    except Exception as e:
        logger.warning("summary thoughts query: %s", e)
        return []
    out: list[LineupNote] = []
    for row in rows:
        body = (row.get("summary") or row.get("content") or "").strip()
        title = row["title"] or f"Thought {row['id']}"
        note_path = row.get("note_path") or ""
        tid = note_path or f"thought/{row['id']}"
        created = row["created_at"]
        if created is not None and getattr(created, "tzinfo", None) is None:
            created = created.replace(tzinfo=timezone.utc)
        ms = int(created.timestamp() * 1000) if created else 0
        out.append(
            LineupNote(
                id=tid,
                title=title,
                body=body,
                section="",
                lens="thoughts",
                week=window.label,
                mtime_ms=ms,
                links=extract_links(body),
                excerpt=_excerpt(body),
            )
        )
    return out


def _collection_axes(key: str) -> tuple[str, str]:
    if key in SECTIONS:
        return key, "knowledge"
    return "", key


def _render_knowledge_seed(
    window: WeekWindow,
    key: str,
    items: list[LineupNote],
) -> LineupNote:
    """Virtual catalog when summary.md has not been generated yet."""
    from gaius.engine.services.knowledge_summary import (
        COLLECTION_REL,
        COLLECTION_TITLE,
    )

    title = COLLECTION_TITLE.get(key, key.title())
    folder = COLLECTION_REL.get(key, f"current/{key}")
    section, lens = _collection_axes(key)
    lines = [
        f"# {title}",
        "",
        f"{len(items)} note(s) in `{folder}/`. "
        "Generate `summary.md` with `/summary knowledge` "
        "(or KnowledgeSummaryFlow) for the standing catalog.",
        "",
    ]
    for it in items:
        lines.append(f"- [[{it.id}|{it.title}]]")
    if not items:
        lines.append("Empty — no markdown notes in this collection.")
    body = "\n".join(lines) + "\n"
    return LineupNote(
        id=f"lens/{key}",
        title=title,
        body=body,
        section=section,
        lens=lens or "knowledge",
        week=window.label,
        links=extract_links(body),
        virtual=True,
        excerpt=_excerpt(body),
    )


def _collection_index(
    root: Path,
    key: str,
    window: WeekWindow,
    cap: int,
) -> dict[str, object]:
    from gaius.engine.services.knowledge_summary import (
        KnowledgeSummaryError,
        list_section_notes,
        summary_relpath,
    )

    try:
        catalog = list_section_notes(root, key, window=window)
    except KnowledgeSummaryError as e:
        raise SummaryLineupError(str(e)) from e
    items: list[LineupNote] = []
    for kn in catalog:
        try:
            items.append(_read_file_note(root, kn.id, window))
        except SummaryLineupError:
            continue
        if len(items) >= cap:
            break
    landing = summary_relpath(key)
    section, lens = _collection_axes(key)
    if (root / landing).is_file():
        seed = _read_file_note(root, landing, window)
        seed.section = section
        seed.lens = lens or "knowledge"
    else:
        landing = ""
        seed = _render_knowledge_seed(window, key, items)
    return {
        "week": window.label,
        "landing_id": landing,
        "seed": seed,
        "items": items,
    }


def _render_lens_seed(
    window: WeekWindow,
    section: str,
    lens: str,
    items: list[LineupNote],
    landing_id: str,
) -> LineupNote:
    lid = lens_id(section, lens)
    if not lens:
        title = f"Weekly Signals Summary · {window.label}"
        lines = [
            f"# {title}",
            "",
            f"Temporal landing for {window.label}. SECTION = Ontology / Heuristic; "
            "LENS = Articles / Projects / Thoughts.",
            "",
        ]
        if landing_id:
            lines.append(f"This week's readout: [[{landing_id}]]")
            lines.append("")
        if items:
            lines.append("## Moved or linked this week")
            lines.append("")
            for it in items:
                lines.append(f"- [[{it.id}|{it.title}]]")
        else:
            lines.append("Nothing in this slice moved this week.")
        body = "\n".join(lines) + "\n"
        return LineupNote(
            id=lid,
            title=title,
            body=body,
            section=section or "week",
            lens="week",
            week=window.label,
            links=extract_links(body),
            virtual=True,
            excerpt=_excerpt(body),
        )
    label = lens.title()
    lines = [f"# {label}", "", f"{len(items)} trailhead(s), latest first.", ""]
    for it in items:
        lines.append(f"- [[{it.id}|{it.title}]]")
    if not items:
        lines.append("Empty — nothing in this lens this week.")
    body = "\n".join(lines) + "\n"
    return LineupNote(
        id=lid,
        title=label,
        body=body,
        section=section,
        lens=lens,
        week=window.label,
        links=extract_links(body),
        virtual=True,
        excerpt=_excerpt(body),
    )


async def build_index(
    kb: Path | None = None,
    *,
    section: str = "",
    lens: str = "",
    week: str = "",
    limit: int = 48,
    db_pool: object | None = None,
) -> dict[str, object]:
    root = kb or kb_root_from_env()
    try:
        require_kb(root)
    except AgendaError as e:
        raise SummaryLineupError(GURU_NOKB) from e
    section = validate_section(section)
    lens = validate_lens(lens)
    window = parse_iso_week(week)
    cap = max(1, min(int(limit or 48), 200))

    if section == "corpus":
        from gaius.engine.services.summary_corpus import build_corpus_index

        return await build_corpus_index(db_pool, window.label, cap)
    if section:
        return _collection_index(root, section, window, cap)
    if lens:
        return _collection_index(root, lens, window, cap)

    landing = weekly_landing(root, window)
    weekly_note: LineupNote | None = None
    if landing:
        try:
            weekly_note = _read_file_note(root, landing, window)
            weekly_note.section = "week"
            weekly_note.lens = "week"
        except SummaryLineupError:
            weekly_note = None
    linked = _linked_from(weekly_note)

    items: list[LineupNote] = []
    if not lens:
        items.extend(await _db_thoughts(db_pool, window, cap))
        for path in _thought_files(root, window):
            rel = _rel(root, path)
            try:
                items.append(_read_file_note(root, rel, window))
            except SummaryLineupError:
                continue

    if not lens:
        for path in _article_cards(root):
            rel = _rel(root, path)
            try:
                note = _read_file_note(root, rel, window)
            except SummaryLineupError:
                continue
            if _in_week(note.mtime_ms, window) or rel in linked or any(
                rel.startswith(x.rstrip("/")) or x.startswith(rel) for x in linked
            ):
                items.append(note)

        for path in _project_cards(root):
            rel = _rel(root, path)
            try:
                note = _read_file_note(root, rel, window)
            except SummaryLineupError:
                continue
            if _in_week(note.mtime_ms, window) or rel in linked:
                items.append(note)

    if not lens:
        for target in linked:
            try:
                rel = resolve_hop(root, landing or "", target)
                items.append(_read_file_note(root, rel, window))
            except SummaryLineupError:
                continue

    # Dedup by id, section filter, cap
    seen: set[str] = set()
    filtered: list[LineupNote] = []
    for note in items:
        if note.id in seen:
            continue
        if lens and note.lens and note.lens != lens and note.section != section:
            if lens == "thoughts" and note.lens != "thoughts":
                continue
            if lens == "articles" and note.lens not in ("articles", "") and note.section != "ontology":
                continue
            if lens == "projects" and note.lens != "projects":
                continue
        if not _touches_section(note, section):
            continue
        seen.add(note.id)
        filtered.append(note)
        if len(filtered) >= cap:
            break

    seed = _render_lens_seed(window, section, lens, filtered, landing)
    return {
        "week": window.label,
        "landing_id": landing,
        "seed": seed,
        "items": filtered,
    }


def get_note(
    kb: Path,
    note_id: str,
    *,
    section: str = "",
    lens: str = "",
    week: str = "",
    index: dict[str, object] | None = None,
) -> LineupNote:
    nid = (note_id or "").strip()
    if not nid:
        raise SummaryLineupError(GURU_NOPAGE)
    window = parse_iso_week(week)
    if nid.startswith("lens/"):
        if index is None:
            raise SummaryLineupError(GURU_NOPAGE)
        seed = index.get("seed")
        if isinstance(seed, LineupNote) and seed.id == nid:
            return seed
        raise SummaryLineupError(GURU_NOPAGE)
    return _read_file_note(kb, nid, window)


def parse_thought_id(note_id: str) -> str:
    m = THOUGHT_UUID.match((note_id or "").strip())
    return m.group(1).lower() if m else ""


def _thought_body(row: object) -> str:
    title = row["title"] or f"Thought {row['id']}"
    kind = (row["thought_type"] or "").strip() or "thought"
    summary = (row.get("summary") or "").strip()
    content = (row.get("content") or "").strip()
    body_src = content or summary
    cycle = (row.get("note_path") or "").strip()
    salience = row.get("salience")
    lines = [f"# {title}", "", f"**{kind}**"]
    if salience is not None:
        lines[2] += f" · salience {float(salience):.2f}"
    lines.append("")
    if body_src:
        lines.append(body_src)
        lines.append("")
    if cycle:
        lines.append(f"Cycle note: [[{cycle}]]")
        lines.append("")
    return "\n".join(lines)


async def load_db_thought(
    db_pool: object | None,
    note_id: str,
    *,
    week: str = "",
) -> LineupNote:
    tid = parse_thought_id(note_id)
    if not tid:
        raise SummaryLineupError(GURU_NOPAGE)
    if db_pool is None:
        raise SummaryLineupError(GURU_THOUGHTDB)
    try:
        async with db_pool.acquire() as conn:  # type: ignore[union-attr]
            row = await conn.fetchrow(
                """
                SELECT id, thought_type, title, summary, content,
                       salience, generation, note_path, created_at
                FROM cognition_thoughts
                WHERE id = $1::uuid
                """,
                tid,
            )
    except Exception as e:
        raise SummaryLineupError(f"{GURU_THOUGHTDB}\n  Error: {e}") from e
    if row is None:
        raise SummaryLineupError(GURU_NOTHOUGHT)
    window = parse_iso_week(week)
    created = row["created_at"]
    if created is not None and getattr(created, "tzinfo", None) is None:
        created = created.replace(tzinfo=timezone.utc)
    ms = int(created.timestamp() * 1000) if created else 0
    body = _thought_body(row)
    cycle = (row.get("note_path") or "").strip()
    return LineupNote(
        id=f"thought/{tid}",
        title=row["title"] or f"Thought {tid}",
        body=body,
        section="",
        lens="thoughts",
        week=window.label,
        mtime_ms=ms,
        links=extract_links(body),
        origin_id=cycle,
        excerpt=_excerpt(body),
        virtual=True,
    )


def resolve_hop(kb: Path, from_id: str, target: str) -> str:
    raw = (target or "").strip()
    if not raw:
        raise SummaryLineupError(GURU_NOLINK)
    raw = raw.lstrip("/")
    if raw.endswith(".md"):
        cand = raw
    else:
        cand = raw
    try:
        path = jail_kb(kb, cand)
        if path.is_file():
            return cand
        if path.with_suffix(".md").is_file():
            return str(path.with_suffix(".md").relative_to(kb.resolve())).replace("\\", "/")
    except SummaryLineupError:
        pass
    # suffix / stem search under current + scratch (bounded)
    stem = Path(raw).name
    for folder in (kb / "current", kb / "scratch"):
        if not folder.is_dir():
            continue
        matches = list(folder.rglob(stem)) + list(folder.rglob(stem + ".md"))
        files = [m for m in matches if m.is_file()]
        if len(files) == 1:
            return _rel(kb, files[0])
        if from_id:
            here = Path(from_id).parent
            near = [m for m in files if here.as_posix() in _rel(kb, m)]
            if len(near) == 1:
                return _rel(kb, near[0])
    raise SummaryLineupError(GURU_NOLINK)


def fork_local(kb: Path, note: LineupNote, *, now: datetime | None = None) -> LineupNote:
    if note.virtual:
        raise SummaryLineupError(GURU_NOFORK)
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    day = clock.strftime("%Y-%m-%d")
    name = f"{clock.strftime('%Y-%m-%d-%H%M%S')}_fork-{skewer(note.title, 'page')}.md"
    rel = f"scratch/{day}/{name}"
    dest = jail_kb(kb, rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"origin: {note.origin_project or 'gaius'}\n"
        f"origin_id: {note.id}\n"
        f"forked_at: {clock.isoformat()}\n\n"
    )
    dest.write_text(header + (note.body or "").lstrip() + "\n", encoding="utf-8")
    window = parse_iso_week("", now=clock)
    forked = _read_file_note(kb, rel, window)
    forked.origin_project = note.origin_project or "gaius"
    forked.origin_id = note.id
    return forked


async def fork_note(
    kb: Path,
    note_id: str,
    *,
    origin_project: str = "",
    services: object | None = None,
    now: datetime | None = None,
) -> LineupNote:
    peer = (origin_project or "").strip()
    if peer and peer != "gaius":
        from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
        from gaius.engine.s2s import configured_peers, query_peer

        target = ""
        for pid, tgt in configured_peers(services):
            if pid == peer:
                target = tgt
                break
        if not target:
            raise SummaryLineupError(GURU_NOFORK)
        resp = await query_peer(
            target,
            kind=zpb.SERVER_QUERY_KIND_NOTE,
            origin_project="gaius",
            note_id=note_id,
        )
        if resp is None or not resp.note.id:
            raise SummaryLineupError(GURU_NOFORK)
        n = resp.note
        remote = LineupNote(
            id=n.id,
            title=n.title or n.id,
            body=n.body,
            links=list(n.links),
            origin_project=n.origin_project or peer,
            origin_id=n.id,
        )
        return fork_local(kb, remote, now=now)
    window = parse_iso_week("", now=now)
    note = _read_file_note(kb, note_id, window)
    return fork_local(kb, note, now=now)
