"""A week investigated, not reduced.

Passing thoughts are momentary. They provoke an investigation; they are
not an outline. Notice groups them by a distinctive shared word so a
paraphrase cloud outranks a sentence that was repeated verbatim. Associate
reads earlier weeks' wells and the external sources that share a sharper
inkling's terms. Two thinking passes then do the work: one writes the
well, one distills the standing implication the daily loop reads whole.

Association is not assertion. Class co-occurrence is where admitted items
sat. It is not a role to assign, and it is not a subsumption.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{4,}")
_SEED_RE = re.compile(r"^[a-z][a-z0-9-]{4,}$")
_WELL_RE = re.compile(r"(?im)^(TITLE|WELL)\s*:\s*")
_CARRY_RE = re.compile(r"(?im)^(KNOWN|STOP|OPEN)\s*:\s*")
_FUNCTION_WORDS = frozenset(
    """
    which their there these those about would could should while where
    after before other every being across between through under again
    still something someone another without within
    """.split()
)

_DF_FLOOR_LARGE = 5
# Above this share of a large week the word is the water, not a subject.
_DF_CEILING = 0.18
_CLOUD_LIMIT = 16
_SINGLE_LIMIT = 10
# The loop's own salience. Below this, an unclustered title is not the subject.
_SINGLE_SALIENCE = 0.9
_WELL_MIN = 600
_CARRY_MAX = 900
_KNOWN_MIN = 40
_STOP_MIN = 40
_OPEN_MIN = 40


def _fold(token: str) -> str:
    word = token.casefold()
    if len(word) > 5 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    return {
        _fold(word)
        for word in _WORD_RE.findall(text or "")
        if len(word) >= 5 and word.casefold() not in _FUNCTION_WORDS
    }


def slice_window(slice_id: str) -> tuple[datetime, datetime] | None:
    """UTC ``[monday, next monday)`` for a zero-padded ISO slice."""
    match = re.fullmatch(r"(\d{4})-W(\d{2})", (slice_id or "").strip())
    if match is None:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    try:
        monday = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return monday, monday + timedelta(days=7)


def notice_inklings(rows: list[dict[str, Any]] | None, *, limit: int = _CLOUD_LIMIT) -> list[dict[str, Any]]:
    """Clouds of paraphrase, plus a few inklings that joined no cloud.

    A word above ``_DF_CEILING`` of a large week is the water the thoughts
    swim in, not a subject. A sentence repeated verbatim stays one title,
    inside a cloud only when it uses that cloud's word. A title that joins
    no cloud is kept when the loop already scored it at ``_SINGLE_SALIENCE``
    or above. Its count is fixation, not a separate subject.
    """
    items: list[dict[str, Any]] = []
    for row in rows or []:
        if str(row.get("thought_type") or "") == "consolidation":
            continue
        title = " ".join(str(row.get("title") or "").split())
        if not title:
            continue
        # Titles are the inkling. Bodies repeat the writer's habits
        # ("suggests", source names) and would cluster those instead.
        gist = " ".join(str(row.get("summary") or row.get("content") or "").split())
        items.append(
            {
                "title": title,
                "gist": gist[:180],
                "salience": float(row.get("salience") or 0),
                "tokens": _tokens(title),
            }
        )
    if not items:
        return []
    count = len(items)
    # Above _DF_CEILING of a large week is water, not a subject.
    # The same ratio on a small week is just a real cloud.
    if count >= 40:
        floor = _DF_FLOOR_LARGE
        ceiling = max(floor, int(_DF_CEILING * count))
    else:
        floor = 2
        ceiling = count
    freq: Counter[str] = Counter()
    for item in items:
        freq.update(item["tokens"])
    ranked: list[tuple[float, int, str]] = []
    for token, seen in freq.items():
        if seen < floor or seen > ceiling or not _SEED_RE.fullmatch(token):
            continue
        ranked.append((seen * math.log(count / seen), seen, token))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))

    clouds: list[dict[str, Any]] = []
    selected: set[str] = set()
    for _score, _seen, token in ranked[: max(1, limit)]:
        members = [item for item in items if token in item["tokens"]]
        if len(members) < floor:
            continue
        grouped: dict[str, dict[str, Any]] = {}
        for item in members:
            key = item["title"].casefold()
            slot = grouped.get(key)
            if slot is None:
                grouped[key] = {
                    "title": item["title"],
                    "gist": item["gist"],
                    "n": 1,
                    "salience": item["salience"],
                }
                continue
            slot["n"] += 1
            if item["salience"] >= float(slot["salience"]) and item["gist"]:
                slot["gist"] = item["gist"]
                slot["salience"] = item["salience"]
        lines = sorted(
            grouped.values(),
            key=lambda line: (-int(line["n"]), -float(line["salience"]), str(line["title"])),
        )[:4]
        clouds.append(
            {
                "name": token,
                "kind": "cloud",
                "n": len(members),
                "titles": len(grouped),
                "lines": lines,
            }
        )
        selected.add(token)

    singles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    unclustered = sorted(
        (item for item in items if not (item["tokens"] & selected)),
        key=lambda item: (-float(item["salience"]), str(item["title"])),
    )
    repeats: Counter[str] = Counter(item["title"].casefold() for item in unclustered)
    for item in unclustered:
        if float(item["salience"]) < _SINGLE_SALIENCE:
            break
        key = item["title"].casefold()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        repeats_n = int(repeats[key])
        singles.append(
            {
                "name": item["title"],
                "kind": "inkling",
                "n": repeats_n,
                "titles": 1,
                "lines": [
                    {
                        "title": item["title"],
                        "gist": item["gist"],
                        "n": repeats_n,
                        "salience": item["salience"],
                    }
                ],
            }
        )
        if len(singles) >= _SINGLE_LIMIT:
            break
    return clouds + singles


def sharper_seeds(inklings: list[dict[str, Any]], limit: int = 4) -> list[str]:
    """Smaller clouds, for external lookup. The largest cloud is the water."""
    clouds = [item for item in inklings if item.get("kind") == "cloud" and _SEED_RE.fullmatch(str(item.get("name") or ""))]
    clouds.sort(key=lambda item: (int(item.get("n") or 0), str(item.get("name") or "")))
    return [str(item["name"]) for item in clouds[: max(1, limit)]]


def _sections(text: str, pattern: re.Pattern[str]) -> dict[str, str]:
    matches = list(pattern.finditer(text or ""))
    out: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        out[match.group(1).upper()] = text[start:end].strip()
    return out


def parse_well(text: str) -> dict[str, str] | None:
    parts = _sections(text, _WELL_RE)
    title = " ".join((parts.get("TITLE") or "").split())
    well = (parts.get("WELL") or "").strip()
    if not title or len(well) < _WELL_MIN:
        return None
    return {"title": title[:120], "content": well}


def parse_carry(text: str) -> dict[str, str] | None:
    parts = _sections(text, _CARRY_RE)
    known = " ".join((parts.get("KNOWN") or "").split())
    stop = " ".join((parts.get("STOP") or "").split())
    opened = " ".join((parts.get("OPEN") or "").split())
    if not (known and stop and opened):
        return None
    summary = f"KNOWN: {known}\nSTOP: {stop}\nOPEN: {opened}"
    return {"known": known, "stop": stop, "open": opened, "summary": summary}


def _mentions(text: str, name: str) -> bool:
    """True when the well uses the cloud's stem, including a trailing plural."""
    folded = name.casefold()
    forms = [folded]
    if folded and not folded.endswith("s"):
        forms.append(f"{folded}s")
    hay = text.casefold()
    return any(re.search(rf"\b{re.escape(form)}\b", hay) for form in forms)


def _takes_up_clouds(well: str, inklings: list[dict[str, Any]]) -> bool:
    clouds = [item for item in inklings if item.get("kind") == "cloud"]
    if len(clouds) < 2:
        return True
    named = [item for item in clouds if _mentions(well, str(item.get("name") or ""))]
    return len(named) >= 2


def investigation_holds(record: dict[str, str] | None, inklings: list[dict[str, Any]]) -> bool:
    """A well that takes up more than its loudest cloud, and a carry the loop can read whole."""
    if not record:
        return False
    from gaius.engine.services.theta_understanding import _asserts_subsumption

    well = record.get("content") or ""
    summary = record.get("summary") or ""
    if len(well) < _WELL_MIN or not (_KNOWN_MIN <= len(summary) <= _CARRY_MAX):
        return False
    if len(record.get("known") or "") < _KNOWN_MIN:
        return False
    if len(record.get("stop") or "") < _STOP_MIN:
        return False
    if len(record.get("open") or "") < _OPEN_MIN:
        return False
    if _asserts_subsumption(well) or _asserts_subsumption(summary):
        return False
    return _takes_up_clouds(well, inklings)


def investigation_prompt(
    slice_id: str,
    inklings: list[dict[str, Any]],
    bindings: list[tuple[str, int]],
    prior: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    """Ask for a well. The thoughts are the provocation, not the outline."""
    lines = [
        f"Investigate ISO week {slice_id}.",
        "",
        "Passing thoughts inspired this investigation. Do not shorten them",
        "into a memo. Say what they were reaching for, which clouds are one",
        "subject and which only share a metaphor, and what is still open",
        "because the sources do not settle it.",
        "",
        "Inklings. A cloud counts every thought that used the word, so clouds",
        "overlap. n is thoughts, titles is distinct wordings. A repeated",
        "sentence is fixation, not the subject:",
    ]
    if not inklings:
        lines.append("- (none)")
    for inkling in inklings:
        kind = "cloud" if inkling.get("kind") == "cloud" else "single inkling"
        lines.append(
            f"- {inkling['name']} ({kind}, {int(inkling['n'])} thoughts, "
            f"{int(inkling['titles'])} titles)"
        )
        for line in inkling.get("lines") or []:
            gist = line.get("gist") or ""
            lines.append(f"    ({int(line['n'])}×) {line['title']}: {gist}")
    lines.extend(["", "Earlier weeks already investigated, valid-time order.", "Read them as understanding, not as more passing thoughts:"])
    if not prior:
        lines.append("- (none)")
    for week in prior:
        lines.append(f"- {week.get('slice_id')}: {week.get('title') or ''}")
        carry = (week.get("carry") or "").strip()
        if carry:
            lines.append(f"  standing implication: {carry}")
        well = (week.get("well") or "").strip()
        if well:
            lines.append(f"  well (opening): {well[:800]}")
    lines.extend(
        [
            "",
            "External sources from that week whose text shares a sharper inkling's word.",
            "These are associations, not evidence that the word names one mechanism:",
        ]
    )
    if not sources:
        lines.append("- (none retrieved)")
    for source in sources:
        lines.append(
            f"- [{source.get('seed')}] {source.get('title') or ''}: {source.get('summary') or ''}"
        )
    lines.extend(
        [
            "",
            "Certified classes co-occurring with admitted items this week.",
            "Frequency is where the corpus sat. It is not what the inklings",
            "discovered, and it is not a role to assign to the class:",
        ]
    )
    if not bindings:
        lines.append("- (no groundings)")
    for label, seen in bindings:
        lines.append(f"- {label} ({seen})")
    lines.extend(
        [
            "",
            "Write exactly these sections:",
            "TITLE: one line, at most 80 characters",
            "WELL: the investigation. Distinctions the thoughts did not state.",
            "Several paragraphs. Do not list the titles back. Do not mint a",
            "class for a hypothesis. Do not claim subclass or subsumption.",
        ]
    )
    return "\n".join(lines)


def carry_prompt(slice_id: str, well: str) -> str:
    return "\n".join(
        [
            f"Distill the standing implication of the {slice_id} investigation.",
            "The daily cognition loop will read all of what you write. It will",
            "not read the well. Do not recap titles. Do not assign roles to classes.",
            "Three sections, each at most two sentences:",
            "KNOWN: what is now understood",
            "STOP: what must not be derived again",
            "OPEN: what remains unresolved",
            "",
            well,
        ]
    )


async def load_prior_wells(conn: Any, slice_id: str, limit: int = 2) -> list[dict[str, Any]]:
    """Earlier ISO weeks' wells. A later landing of this week is not one of them."""
    rows = await conn.fetch(
        """
        SELECT title, summary, content,
               generation_context->>'slice_id' AS slice_id
          FROM cognition_thoughts
         WHERE thought_type = 'consolidation'
           AND status = 'active'
           AND char_length(btrim(content)) >= 240
        """
    )
    earlier: list[dict[str, Any]] = []
    for row in rows:
        prior = str(row["slice_id"] or "").strip()
        if not prior or prior >= (slice_id or "").strip():
            continue
        earlier.append(
            {
                "slice_id": prior,
                "title": row["title"],
                "carry": str(row["summary"] or "").strip()[:_CARRY_MAX],
                "well": str(row["content"] or "").strip()[:800],
            }
        )
    earlier.sort(key=lambda item: item["slice_id"], reverse=True)
    return earlier[: max(1, limit)]


async def load_external_sources(
    conn: Any,
    slice_id: str,
    inklings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Content fetched that week which shares a sharper inkling's word."""
    window = slice_window(slice_id)
    if window is None:
        return []
    start, end = window
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed in sharper_seeds(inklings):
        rows = await conn.fetch(
            """
            SELECT title, left(coalesce(summary, ''), 280) AS summary
              FROM content_items
             WHERE fetched_at >= $1
               AND fetched_at < $2
               AND (title ILIKE $3 OR summary ILIKE $3)
             ORDER BY fetched_at DESC
             LIMIT 3
            """,
            start,
            end,
            f"%{seed}%",
        )
        for row in rows:
            title = str(row["title"] or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            found.append({"seed": seed, "title": title, "summary": str(row["summary"] or "").strip()})
    return found


async def investigate_week(
    client: Any,
    slice_id: str,
    inklings: list[dict[str, Any]],
    bindings: list[tuple[str, int]],
    prior: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, str, int, str]:
    """One investigation and one distillation.

    An unusable well (missing, short, or fewer than two clouds) is
    investigated once more. A usable well whose carry does not hold is
    distilled once more. The second case does not spend another
    investigation. Returns (held record or None, last raw investigation,
    tokens, model).
    """
    from gaius.engine.services.theta_understanding import _complete

    prompt = investigation_prompt(slice_id, inklings, bindings, prior, sources)
    text, tokens, model = await _complete(client, prompt)
    record, spent, used, usable = await _distill_if_well(
        client, slice_id, text, tokens, model, inklings
    )
    if record is not None or usable:
        return record, text, spent, used
    clouds = [str(item["name"]) for item in inklings if item.get("kind") == "cloud"]
    retry = (
        prompt
        + "\n\nThe previous well was not usable. Take up at least two of these "
        "clouds and say whether they are one subject or several: "
        + ", ".join(clouds[:8])
        + ". Do not assign roles to classes. Do not assert subclass or subsumption.\n\n"
        + (text or "")[:1500]
    )
    text2, tokens2, model2 = await _complete(client, retry)
    record, spent2, used2, _usable = await _distill_if_well(
        client, slice_id, text2, spent + tokens2, model2 or model, inklings
    )
    return record, text2, spent2, used2


async def _distill_once(
    client: Any,
    slice_id: str,
    well: dict[str, str],
    tokens: int,
    model: str,
    inklings: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, int, str]:
    from gaius.engine.services.theta_understanding import _complete

    carry_text, carry_tokens, carry_model = await _complete(
        client, carry_prompt(slice_id, well["content"])
    )
    carry = parse_carry(carry_text)
    spent = tokens + carry_tokens
    used = carry_model or model
    if carry is None:
        return None, spent, used
    record = {
        "title": well["title"],
        "content": well["content"],
        "summary": carry["summary"],
        "known": carry["known"],
        "stop": carry["stop"],
        "open": carry["open"],
    }
    if investigation_holds(record, inklings):
        return record, spent, used
    return None, spent, used


async def _distill_if_well(
    client: Any,
    slice_id: str,
    text: str,
    tokens: int,
    model: str,
    inklings: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, int, str, bool]:
    """Distill a usable well, once more if the carry does not hold.

    The fourth value is whether the well itself was usable.
    """
    well = parse_well(text)
    if well is None or not _takes_up_clouds(well["content"], inklings):
        return None, tokens, model, False
    record, spent, used = await _distill_once(client, slice_id, well, tokens, model, inklings)
    if record is not None:
        return record, spent, used, True
    record, spent2, used2 = await _distill_once(client, slice_id, well, spent, used, inklings)
    return record, spent2, used2, True
