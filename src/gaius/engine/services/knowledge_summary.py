"""Collection summaries for the Summary lineup.

Writes standing catalogs:

- ``current/ontology/summary.md``
- ``current/heuristics/summary.md``
- ``current/articles/summary.md``
- ``current/projects/summary.md``

and the weekly thoughts page:

- ``current/thoughts/summary.md`` from scratch notes in the ISO week
  (not ``*_wWW-summary.md`` zettels). ``current/thoughts/`` may be empty.

Inline ``[[wiki]]`` hops point at the notes. KB-local for now.

The weekly Signals zettel is unchanged. Metaflow ``KnowledgeSummaryFlow``
and ``/summary knowledge`` both call this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gaius.engine.services.agenda_notes import (
    AgendaError,
    kb_root_from_env,
    require_kb,
)
from gaius.engine.services.weekly_signals_summary import (
    GURU_NOKB,
    NAME as WEEKLY_ZETTEL,
    parse_iso_week,
)

TITLE_H = re.compile(r"^#\s+(.+)$", re.M)

COLLECTIONS = ("ontology", "heuristic", "articles", "projects", "thoughts")
SECTIONS = ("ontology", "heuristic")
LENS_COLLECTIONS = ("articles", "projects", "thoughts")
COLLECTION_REL = {
    "ontology": "current/ontology",
    "heuristic": "current/heuristics",
    "articles": "current/articles",
    "projects": "current/projects",
    "thoughts": "current/thoughts",
}
COLLECTION_TITLE = {
    "ontology": "Ontology",
    "heuristic": "Heuristics",
    "articles": "Articles",
    "projects": "Projects",
    "thoughts": "Thoughts",
}
SUMMARY_NAME = "summary.md"

GURU_BADSECTION = (
    "Collection must be ontology, heuristic, articles, projects, or thoughts.\n"
    "  Guru: #WS.00000005.BADSECTION"
)
GURU_NOSECTION = (
    "Knowledge collection directory is missing.\n"
    "  Guru: #WS.00000012.NOSECTION\n"
    "  Try: create current/ontology, current/heuristics, "
    "current/articles, or current/projects under GAIUS_KB_ROOT"
)
GURU_BADPATH = (
    "Collection summary path must stay under current/"
    "{ontology,heuristics,articles,projects,thoughts}.\n"
    "  Guru: #WS.00000013.BADKPATH"
)


class KnowledgeSummaryError(RuntimeError):
    """Fail-fast collection summary error with guru in the message."""


@dataclass(frozen=True)
class KnowledgeNote:
    id: str
    title: str
    excerpt: str
    category: str
    mtime_ms: int = 0


@dataclass
class KnowledgeWritten:
    section: str
    path: str
    notes: int
    body: str = ""
    categories: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "section": self.section,
            "path": self.path,
            "notes": self.notes,
            "categories": list(self.categories),
        }


def validate_section(raw: str) -> str:
    """Accept any collection id (legacy name: section)."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s not in COLLECTIONS:
        raise KnowledgeSummaryError(GURU_BADSECTION)
    return s


def section_relpath(section: str) -> str:
    section = validate_section(section)
    if not section:
        raise KnowledgeSummaryError(GURU_BADSECTION)
    return COLLECTION_REL[section]


def summary_relpath(section: str) -> str:
    return f"{section_relpath(section)}/{SUMMARY_NAME}"


def jail_knowledge(root: Path, rel: str) -> Path:
    rel = (rel or "").strip().lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise KnowledgeSummaryError(GURU_BADPATH)
    if not any(rel.startswith(p + "/") or rel == p for p in COLLECTION_REL.values()):
        raise KnowledgeSummaryError(GURU_BADPATH)
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as e:
        raise KnowledgeSummaryError(GURU_BADPATH) from e
    return path


def _strip_frontmatter(text: str) -> str:
    raw = text or ""
    if not raw.startswith("---"):
        return raw
    rest = raw[3:]
    end = rest.find("\n---")
    if end < 0:
        return raw
    return rest[end + 4 :]


def _title_of(text: str, fallback: str) -> str:
    m = TITLE_H.search(_strip_frontmatter(text) or "")
    if m:
        return m.group(1).strip()
    return fallback


def _excerpt(text: str, n: int = 160) -> str:
    lines: list[str] = []
    for line in _strip_frontmatter(text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---") or s.startswith("```"):
            continue
        lines.append(s)
        if sum(len(x) for x in lines) >= n:
            break
    blob = " ".join(lines)
    if len(blob) <= n:
        return blob
    return blob[: n - 1].rstrip() + "…"


def _mtime_ms(path: Path) -> int:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return 0


def _note_from_path(kb: Path, path: Path, category: str) -> KnowledgeNote:
    rel = str(path.relative_to(kb)).replace("\\", "/")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return KnowledgeNote(
        id=rel,
        title=_title_of(text, path.stem),
        excerpt=_excerpt(text),
        category=category,
        mtime_ms=_mtime_ms(path),
    )


def _category_folder(section: str, rel: str) -> str:
    parts = Path(rel).parts
    if section == "ontology":
        if len(parts) <= 3:
            return "index"
        return parts[2]
    if section == "heuristic":
        if len(parts) >= 5:
            return parts[3]
        return "index"
    if section == "articles":
        return parts[2] if len(parts) >= 3 else "index"
    if section == "projects":
        if len(parts) <= 3:
            return "index"
        return parts[2]
    return "index"


def _require_dir(kb: Path, section: str) -> Path:
    rel = section_relpath(section)
    root = kb / rel
    if not root.is_dir():
        raise KnowledgeSummaryError(f"{GURU_NOSECTION}\n  Missing: {rel}")
    return root


def _list_folder_walk(kb: Path, section: str) -> list[KnowledgeNote]:
    root = _require_dir(kb, section)
    out: list[KnowledgeNote] = []
    for path in sorted(p for p in root.rglob("*.md") if p.is_file()):
        if path.name == SUMMARY_NAME:
            continue
        rel = str(path.relative_to(kb)).replace("\\", "/")
        out.append(_note_from_path(kb, path, _category_folder(section, rel)))
    return out


def _list_articles(kb: Path) -> list[KnowledgeNote]:
    root = _require_dir(kb, "articles")
    out: list[KnowledgeNote] = []
    for slug in sorted(p for p in root.iterdir() if p.is_dir()):
        for name in ("article.md", "base.md"):
            cand = slug / name
            if cand.is_file():
                out.append(_note_from_path(kb, cand, slug.name))
                break
    return out


def _list_projects(kb: Path) -> list[KnowledgeNote]:
    root = _require_dir(kb, "projects")
    out: list[KnowledgeNote] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith(".") or path.name == SUMMARY_NAME:
            continue
        if len(path.relative_to(root).parts) > 2:
            continue
        rel = str(path.relative_to(kb)).replace("\\", "/")
        out.append(_note_from_path(kb, path, _category_folder("projects", rel)))
    return out


def _list_thoughts(kb: Path, window) -> list[KnowledgeNote]:
    """Scratch notes in [start, end). Skip weekly Signals zettels."""
    scratch = kb / "scratch"
    if not scratch.is_dir():
        return []
    out: list[KnowledgeNote] = []
    day = window.start.date()
    end = window.end.date()
    while day < end:
        folder = scratch / day.isoformat()
        if folder.is_dir():
            for path in sorted(folder.glob("*.md")):
                if WEEKLY_ZETTEL.match(path.name):
                    continue
                out.append(_note_from_path(kb, path, day.isoformat()))
        day += timedelta(days=1)
    return out


def list_section_notes(
    kb: Path,
    section: str,
    *,
    window=None,
    week: str = "",
    now: datetime | None = None,
) -> list[KnowledgeNote]:
    """Notes for a collection. Thoughts use the ISO week window."""
    section = validate_section(section)
    if not section:
        raise KnowledgeSummaryError(GURU_BADSECTION)
    if section == "articles":
        return _list_articles(kb)
    if section == "projects":
        return _list_projects(kb)
    if section == "thoughts":
        clock = now or datetime.now(timezone.utc)
        win = window or parse_iso_week(week, now=clock)
        return _list_thoughts(kb, win)
    return _list_folder_walk(kb, section)


def render_section(
    section: str,
    notes: list[KnowledgeNote],
    *,
    week: str,
    now: datetime,
) -> str:
    section = validate_section(section)
    title = COLLECTION_TITLE[section]
    folder = COLLECTION_REL[section]
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if section == "thoughts":
        lead = (
            f"Generated {stamp} for {week}. Scratch notes from this ISO week "
            f"(weekly Signals zettels omitted). Standing page is `{folder}/summary.md`."
        )
    else:
        lead = (
            f"Generated {stamp} for {week}. KB-local collection at `{folder}/`. "
            "Hops are wiki targets on this host; federated lineups join when "
            "peers answer ServerQuery NOTE."
        )
    lines = [f"# {title}", "", lead, ""]
    by_cat: dict[str, list[KnowledgeNote]] = {}
    for note in notes:
        by_cat.setdefault(note.category, []).append(note)
    cats = sorted(by_cat, key=lambda c: (c != "index", c))
    for cat in cats:
        heading = "Index" if cat == "index" else cat
        lines.append(f"## {heading}")
        lines.append("")
        for note in by_cat[cat]:
            if note.excerpt:
                lines.append(f"- [[{note.id}|{note.title}]] — {note.excerpt}")
            else:
                lines.append(f"- [[{note.id}|{note.title}]]")
        lines.append("")
    if not notes:
        if section == "thoughts":
            lines.append("No scratch notes in this week (other than weekly zettels).")
        else:
            lines.append("No markdown notes in this collection yet.")
        lines.append("")
    return "\n".join(lines)


def write_section_summary(
    kb: Path,
    section: str,
    *,
    week: str = "",
    now: datetime | None = None,
) -> KnowledgeWritten:
    try:
        require_kb(kb)
    except AgendaError as e:
        raise KnowledgeSummaryError(GURU_NOKB) from e
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    window = parse_iso_week(week, now=clock)
    notes = list_section_notes(kb, section, window=window, now=clock)
    body = render_section(section, notes, week=window.label, now=clock)
    rel = summary_relpath(section)
    path = jail_knowledge(kb, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    cats = sorted({n.category for n in notes})
    return KnowledgeWritten(
        section=section,
        path=rel,
        notes=len(notes),
        body=body,
        categories=cats,
    )


def run_knowledge_summaries(
    *,
    week: str = "",
    section: str = "",
    kb: Path | None = None,
    now: datetime | None = None,
) -> list[KnowledgeWritten]:
    root = kb or kb_root_from_env()
    try:
        require_kb(root)
    except AgendaError as e:
        raise KnowledgeSummaryError(GURU_NOKB) from e
    chosen = validate_section(section)
    sections = [chosen] if chosen else list(COLLECTIONS)
    return [
        write_section_summary(root, s, week=week, now=now) for s in sections
    ]
