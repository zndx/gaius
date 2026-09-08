"""Agenda artifacts as scratch zettels (note | list | event).

KB is the store. prev:/next: chains match existing Gaius project notes.
New writes: scratch/YYYY-MM-DD/YYYY-MM-DD-HHmmss_<skewer>.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KINDS = ("note", "list", "event")
INTENTS = ("brief", "reminder", "session")
HEADER_LINK = "[[current/agenda]]"
MAX_SKEWER = 48
SESSION_MINUTES = 30

GURU_NOKB = (
    "Knowledge base root missing or not a directory.\n"
    "  Guru: #AG.00000001.NOKB\n"
    "  Try: set GAIUS_KB_ROOT (default build/dev)"
)
GURU_BADKIND = (
    "Agenda kind must be note, list, or event.\n"
    "  Guru: #AG.00000002.BADKIND"
)
GURU_BADPATH = (
    "Agenda path must stay under scratch/.\n"
    "  Guru: #AG.00000003.BADPATH"
)
GURU_MISSING = (
    "Agenda item not found.\n"
    "  Guru: #AG.00000003.BADPATH"
)
GURU_NOMEETTIME = (
    "Session intent requires starts (Agenda is the calendar).\n"
    "  Guru: #AG.00000006.NOMEETTIME"
)
GURU_BADINTENT = (
    "Agenda intent must be brief, reminder, or session.\n"
    "  Guru: #AG.00000007.BADINTENT"
)
GURU_BADORIGIN = (
    "Agenda origin must be YYYY-MM-DD (caller's calendar today).\n"
    "  Guru: #AG.00000009.BADORIGIN"
)
GURU_BADTZ = (
    "Agenda timezone must be a valid IANA name (e.g. America/Denver).\n"
    "  Guru: #AG.00000010.BADTZ"
)

NEW_NAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{6})_(?P<skewer>[a-z0-9][a-z0-9-]{0,47})\.md$"
)
OLD_NAME = re.compile(r"^(?P<time>\d{6})_(?P<skewer>.+)\.md$")
CHECK_LINE = re.compile(r"^- \[([ xX])\]\s*(.*)$")
WIKI = re.compile(r"\[\[([^\]]+)\]\]")


class AgendaError(ValueError):
    """Fail-fast agenda error with guru in the message."""


def kb_root_from_env() -> Path:
    import os

    raw = os.environ.get("GAIUS_KB_ROOT", "build/dev")
    root = Path(raw)
    if not root.is_absolute():
        devenv = os.environ.get("DEVENV_ROOT")
        if devenv:
            root = Path(devenv) / raw
        else:
            root = Path.cwd() / raw
    return root.resolve()


def require_kb(root: Path) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise AgendaError(GURU_NOKB)
    return root


def skewer(title: str, fallback: str = "item") -> str:
    raw = (title or "").strip().lower().replace("'", "").replace("\u2019", "")
    out = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not out:
        out = fallback
    return out[:MAX_SKEWER]


def validate_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in KINDS:
        raise AgendaError(GURU_BADKIND)
    return k


def default_intent(kind: str) -> str:
    if kind == "list":
        return "reminder"
    return "brief"


def validate_intent(intent: str, kind: str) -> str:
    raw = (intent or "").strip().lower()
    if not raw:
        return default_intent(kind)
    if raw not in INTENTS:
        raise AgendaError(GURU_BADINTENT)
    return raw


def validate_timezone(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as e:
        raise AgendaError(GURU_BADTZ) from e
    return raw


def parse_origin(origin: str) -> date | None:
    raw = (origin or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as e:
        raise AgendaError(GURU_BADORIGIN) from e


def item_calendar_day(item: AgendaItem, *, tz_name: str = "") -> str:
    """Calendar day of starts (or created) in tz_name, else UTC date of the instant."""
    dt = parse_when(item.starts) if item.starts else None
    if dt is None and item.created_ms:
        dt = datetime.fromtimestamp(item.created_ms / 1000, tz=timezone.utc)
    if dt is None:
        return ""
    if tz_name:
        dt = dt.astimezone(ZoneInfo(tz_name))
    return dt.date().isoformat()


def parse_when(iso: str) -> datetime | None:
    raw = (iso or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


CAL_MARKDOWN = re.compile(
    r"\[Add to Google Calendar\]\([^)]+\)",
    re.IGNORECASE,
)
# presenterm deck: off-invite presentation guide (slides, speaker notes, wiki links).
DECK_HEADING = re.compile(r"(?im)^##\s+Deck\s*$")
DEFAULT_JOIN_URL = "https://tinybox.dev.vista.zndx.org/listen"


def split_public_deck(body: str) -> tuple[str, str]:
    """(invite-safe public prose, presenterm deck). Deck is never calendar details."""
    text = body or ""
    m = DECK_HEADING.search(text)
    if not m:
        return strip_calendar_markup(text), ""
    public = strip_calendar_markup(text[: m.start()])
    deck = text[m.end() :].strip()
    return public, deck


def agent_rtc_join_url(item_path: str, *, base: str = "") -> str:
    """Cloudflare-FQDN Listen deep link. Query is the Agenda note path."""
    import os
    from urllib.parse import quote

    root = (
        (base or "").strip()
        or os.environ.get("HERMES_AGENT_RTC_JOIN_URL", "").strip()
        or os.environ.get("GAIUS_AGENDA_JOIN_URL", "").strip()
        or DEFAULT_JOIN_URL
    )
    root = root.rstrip("/")
    path = (item_path or "").strip()
    if not path:
        return root
    return f"{root}?agenda={quote(path, safe='')}"


def strip_calendar_markup(text: str) -> str:
    """Drop the Agenda's own calendar CTA so it is not pasted into Google."""
    return re.sub(r"\n{3,}", "\n\n", CAL_MARKDOWN.sub("", text or "")).strip()


def google_calendar_url(
    *,
    title: str,
    starts: str,
    ends: str = "",
    details: str = "",
    location: str = "",
) -> str:
    """TEMPLATE URL that iPad Safari / Google Calendar.app can open."""
    from urllib.parse import urlencode

    start = parse_when(starts)
    if start is None:
        return ""
    stop = parse_when(ends) or (start + timedelta(minutes=SESSION_MINUTES))

    def stamp(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    q: dict[str, str] = {
        "action": "TEMPLATE",
        "text": title or "Gaius session",
        "dates": f"{stamp(start)}/{stamp(stop)}",
        "details": strip_calendar_markup(details or "")[:1500],
    }
    if (location or "").strip():
        q["location"] = location.strip()
    return f"https://calendar.google.com/calendar/render?{urlencode(q)}"


def jail_path(root: Path, rel: str) -> Path:
    rel = (rel or "").strip().lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise AgendaError(GURU_BADPATH)
    if not (rel.startswith("scratch/") or rel == "current/agenda.md"):
        raise AgendaError(GURU_BADPATH)
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as e:
        raise AgendaError(GURU_BADPATH) from e
    return path


@dataclass
class AgendaItem:
    path: str
    kind: str
    title: str
    body: str
    prev: str = ""
    next: str = ""
    starts: str = ""
    ends: str = ""
    tags: list[str] = field(default_factory=list)
    pin: bool = False
    checks: list[dict[str, object]] = field(default_factory=list)
    created_ms: int = 0
    explicit_kind: bool = False
    intent: str = "brief"
    with_whom: str = ""
    timezone: str = ""

    def join_url(self) -> str:
        if self.intent != "session":
            return ""
        return agent_rtc_join_url(self.path)

    def calendar_url(self) -> str:
        if self.intent != "session":
            return ""
        public, _deck = split_public_deck(self.body)
        join = self.join_url()
        details = public
        if join:
            details = (public + "\n\nJoin AgentRTC: " + join).strip()
        return google_calendar_url(
            title=self.title,
            starts=self.starts,
            ends=self.ends,
            details=details[:1500],
            location=join,
        )

    def excerpt(self, n: int = 180) -> str:
        text, _deck = split_public_deck(self.body)
        if len(text) <= n:
            return text
        return text[: n - 1].rstrip() + "…"


def _wiki_target(value: str) -> str:
    value = value.strip()
    m = WIKI.search(value)
    if m:
        return m.group(1).strip()
    return value


def _parse_header(text: str) -> tuple[dict[str, str], str, str]:
    """Return (fields, title, body). Fields are raw header lines."""
    lines = text.splitlines()
    fields: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            break
        if line.startswith("[[") or not line.strip():
            i += 1
            continue
        if ":" in line and not line.startswith("-"):
            key, _, rest = line.partition(":")
            key = key.strip().lower()
            if key in (
                "kind",
                "prev",
                "next",
                "starts",
                "ends",
                "tags",
                "pin",
                "intent",
                "with",
                "timezone",
            ):
                fields[key] = rest.strip()
                i += 1
                continue
        break
    title = ""
    if i < len(lines) and lines[i].startswith("# "):
        title = lines[i][2:].strip()
        i += 1
        if i < len(lines) and lines[i].strip() == "":
            i += 1
    body = "\n".join(lines[i:]).strip("\n")
    if body:
        body += "\n"
    return fields, title, body


def parse_item(root: Path, path: Path) -> AgendaItem:
    rel = str(path.relative_to(root)).replace("\\", "/")
    text = path.read_text(encoding="utf-8")
    fields, title, body = _parse_header(text)
    explicit_kind = fields.get("kind", "") in KINDS
    kind = fields.get("kind", "note")
    if kind not in KINDS:
        kind = "note"
        explicit_kind = False
    raw_intent = fields.get("intent", "").strip().lower()
    intent = raw_intent if raw_intent in INTENTS else default_intent(kind)
    with_whom = fields.get("with", "").strip()
    tags = [t.strip() for t in fields.get("tags", "").split(",") if t.strip()]
    checks: list[dict[str, object]] = []
    if kind == "list":
        for line in body.splitlines():
            m = CHECK_LINE.match(line)
            if m:
                checks.append(
                    {"done": m.group(1).lower() == "x", "text": m.group(2)}
                )
    created_ms = 0
    name = path.name
    mnew = NEW_NAME.match(name)
    mold = OLD_NAME.match(name)
    if mnew:
        try:
            dt = datetime.strptime(
                f"{mnew.group('date')}{mnew.group('time')}", "%Y-%m-%d%H%M%S"
            )
            created_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            created_ms = int(path.stat().st_mtime * 1000)
    elif mold and path.parent.name.count("-") == 2:
        try:
            dt = datetime.strptime(
                f"{path.parent.name}{mold.group('time')}", "%Y-%m-%d%H%M%S"
            )
            created_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            created_ms = int(path.stat().st_mtime * 1000)
    else:
        created_ms = int(path.stat().st_mtime * 1000)
    if not title:
        title = (mnew.group("skewer") if mnew else path.stem).replace("-", " ")
    return AgendaItem(
        path=rel,
        kind=kind,
        title=title,
        body=body,
        prev=_wiki_target(fields.get("prev", "")),
        next=_wiki_target(fields.get("next", "")),
        starts=fields.get("starts", ""),
        ends=fields.get("ends", ""),
        tags=tags,
        pin=fields.get("pin", "").lower() in ("true", "1", "yes"),
        checks=checks,
        created_ms=created_ms,
        explicit_kind=explicit_kind,
        intent=intent,
        with_whom=with_whom or ("agents" if intent == "session" else ""),
        timezone=(fields.get("timezone") or "").strip(),
    )


def render_item(item: AgendaItem) -> str:
    tags = ", ".join(item.tags)
    prev = f"[[{item.prev}]]" if item.prev else ""
    nxt = f"[[{item.next}]]" if item.next else ""
    lines = [
        HEADER_LINK,
        f"kind: {item.kind}",
        f"prev: {prev}",
        f"next: {nxt}",
        f"starts: {item.starts}",
        f"ends: {item.ends}",
        f"tags: {tags}",
        f"pin: {'true' if item.pin else 'false'}",
        f"intent: {item.intent}",
        f"with: {item.with_whom}",
        f"timezone: {item.timezone}",
        "",
        f"# {item.title}",
        "",
        item.body.rstrip(),
        "",
    ]
    return "\n".join(lines)


def iter_scratch_md(root: Path) -> list[Path]:
    scratch = root / "scratch"
    if not scratch.is_dir():
        return []
    out: list[Path] = []
    for day in sorted(scratch.iterdir()):
        if not day.is_dir():
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.name):
            continue
        for p in sorted(day.glob("*.md")):
            out.append(p)
    return out


STANDING_WEEKLY_RE = re.compile(r"_w\d{2}-summary\.md$")


def find_standing_brief(root: Path, slug: str = "w34-summary") -> AgendaItem | None:
    """Latest weekly memo card (``*_w34-summary.md``), else latest ``*_wNN-summary``."""
    root = require_kb(root)
    preferred = [p for p in iter_scratch_md(root) if p.name.endswith(f"_{slug}.md")]
    if preferred:
        preferred.sort(key=lambda p: p.as_posix())
        return parse_item(root, preferred[-1])
    weekly = [p for p in iter_scratch_md(root) if STANDING_WEEKLY_RE.search(p.name)]
    if not weekly:
        return None
    weekly.sort(key=lambda p: p.as_posix())
    return parse_item(root, weekly[-1])


def find_by_slug(root: Path, day: str, slug: str) -> Path | None:
    folder = root / "scratch" / day
    if not folder.is_dir():
        return None
    needle = f"_{slug}"
    hits = sorted(p for p in folder.glob("*.md") if needle in p.name)
    return hits[0] if hits else None


def find_prev(root: Path, kind: str) -> Path | None:
    for path in reversed(iter_scratch_md(root)):
        try:
            item = parse_item(root, path)
        except OSError:
            continue
        if item.kind != kind:
            continue
        if item.explicit_kind or NEW_NAME.match(path.name):
            return path
    return None


def _update_next(root: Path, prev: Path, new_rel: str) -> None:
    text = prev.read_text(encoding="utf-8")
    updated = re.sub(
        r"^(next:)\s*$",
        rf"\1 [[{new_rel}]]",
        text,
        flags=re.MULTILINE,
    )
    if updated != text:
        prev.write_text(updated, encoding="utf-8")


def create_item(
    root: Path,
    *,
    kind: str,
    title: str,
    body: str = "",
    starts: str = "",
    ends: str = "",
    tags: list[str] | None = None,
    pin: bool = False,
    now: datetime | None = None,
    intent: str = "",
    with_whom: str = "",
    tz_name: str = "",
) -> AgendaItem:
    root = require_kb(root)
    kind = validate_kind(kind)
    intent = validate_intent(intent, kind)
    tz_name = validate_timezone(tz_name)
    if intent == "session" and not (starts or "").strip():
        raise AgendaError(GURU_NOMEETTIME)
    if intent == "session" and not (ends or "").strip():
        start_dt = parse_when(starts)
        if start_dt is not None:
            ends = (start_dt + timedelta(minutes=SESSION_MINUTES)).isoformat()
    if intent == "session" and not with_whom.strip():
        with_whom = "agents"
    now = now or datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    stem = f"{date_str}-{time_str}_{skewer(title, kind)}"
    day_dir = root / "scratch" / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{stem}.md"
    n = 1
    while path.exists():
        path = day_dir / f"{stem}-{n}.md"
        n += 1
    rel = str(path.relative_to(root)).replace("\\", "/")
    prev_path = find_prev(root, kind)
    prev_rel = ""
    if prev_path is not None:
        prev_rel = str(prev_path.relative_to(root)).replace("\\", "/")
    if kind == "list" and body.strip() == "":
        body = "- [ ] \n"
    item = AgendaItem(
        path=rel,
        kind=kind,
        title=title.strip() or kind.title(),
        body=body if body.endswith("\n") or not body else body + "\n",
        prev=prev_rel,
        next="",
        starts=starts,
        ends=ends,
        tags=list(tags or []),
        pin=pin,
        created_ms=int(now.timestamp() * 1000),
        intent=intent,
        with_whom=with_whom,
        timezone=tz_name,
    )
    path.write_text(render_item(item), encoding="utf-8")
    if prev_path is not None:
        _update_next(root, prev_path, rel)
    return parse_item(root, path)


def get_item(root: Path, rel: str) -> AgendaItem:
    root = require_kb(root)
    path = jail_path(root, rel)
    if not path.is_file():
        raise AgendaError(GURU_MISSING)
    return parse_item(root, path)


def update_item(
    root: Path,
    rel: str,
    *,
    title: str | None = None,
    body: str | None = None,
    starts: str | None = None,
    ends: str | None = None,
    tags: list[str] | None = None,
    pin: bool | None = None,
    checks: list[dict[str, object]] | None = None,
    intent: str | None = None,
    with_whom: str | None = None,
    kind: str | None = None,
    tz_name: str | None = None,
) -> AgendaItem:
    item = get_item(root, rel)
    if kind is not None:
        item.kind = validate_kind(kind)
        item.explicit_kind = True
    if title is not None:
        item.title = title.strip() or item.title
    if body is not None:
        item.body = body if body.endswith("\n") or not body else body + "\n"
    if starts is not None:
        item.starts = starts
    if ends is not None:
        item.ends = ends
    if tags is not None:
        item.tags = tags
    if pin is not None:
        item.pin = pin
    if intent is not None:
        item.intent = validate_intent(intent, item.kind)
    if with_whom is not None:
        item.with_whom = with_whom
    if tz_name is not None:
        item.timezone = validate_timezone(tz_name)
    if item.intent == "session" and not item.starts.strip():
        raise AgendaError(GURU_NOMEETTIME)
    if item.intent == "session" and not item.with_whom.strip():
        item.with_whom = "agents"
    if item.intent == "session" and not item.ends.strip():
        start_dt = parse_when(item.starts)
        if start_dt is not None:
            item.ends = (start_dt + timedelta(minutes=SESSION_MINUTES)).isoformat()
    if checks is not None and item.kind == "list":
        lines = []
        for c in checks:
            mark = "x" if c.get("done") else " "
            lines.append(f"- [{mark}] {c.get('text', '')}")
        item.body = "\n".join(lines) + "\n"
    path = jail_path(root, item.path)
    path.write_text(render_item(item), encoding="utf-8")
    return parse_item(root, path)


def list_items(
    root: Path,
    *,
    window_days: int = 14,
    kind: str = "",
    tag: str = "",
    now: datetime | None = None,
    origin: str = "",
    tz_name: str = "",
) -> list[AgendaItem]:
    root = require_kb(root)
    days = int(window_days or 14)
    if days < 1 or days > 3660:
        raise AgendaError(
            "window_days must be in 1..3660.\n  Guru: #AG.00000004.BADWINDOW"
        )
    kind_f = kind.strip().lower()
    if kind_f and kind_f not in KINDS:
        raise AgendaError(GURU_BADKIND)
    tag_f = tag.strip().lower()
    zone = validate_timezone(tz_name)
    now = now or datetime.now(timezone.utc)
    origin_day = parse_origin(origin)
    if origin_day is not None:
        today = origin_day
    elif zone:
        today = now.astimezone(ZoneInfo(zone)).date()
    else:
        today = now.date()
    lo = (today - timedelta(days=days)).isoformat()
    hi = (today + timedelta(days=days)).isoformat()
    cutoff = now - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    out: list[AgendaItem] = []
    for path in iter_scratch_md(root):
        try:
            item = parse_item(root, path)
        except OSError:
            continue
        if not item.explicit_kind and not NEW_NAME.match(path.name):
            continue
        if kind_f and item.kind != kind_f:
            continue
        if tag_f and tag_f not in [t.lower() for t in item.tags]:
            continue
        day = item_calendar_day(item, tz_name=zone)
        if day:
            if day < lo or day > hi:
                continue
        elif item.created_ms and item.created_ms < cutoff_ms:
            continue
        out.append(item)
    out.sort(key=lambda i: (not i.pin, -(i.created_ms or 0)))
    return out
