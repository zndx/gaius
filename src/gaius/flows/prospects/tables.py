"""Plain-text / markdown table detect for SEC extracts (docling output)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MD_ROW = re.compile(r"^\s*\|.+\|\s*$")
_MD_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")
_HTML_TABLE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
_NUM = re.compile(r"[\d,.]+%?|\$[\d,.]+")
_YOY = re.compile(
    r"year[\s-]over[\s-]year|three months|nine months|fiscal|compared to",
    re.IGNORECASE,
)


@dataclass
class FilingTable:
    start: int
    end: int
    text: str
    rows: int
    numeric_cells: int
    salience: float
    kind: str  # markdown | html


def detect_tables(text: str, *, min_salience: float = 0.15) -> list[FilingTable]:
    """Find markdown and HTML tables; score numeric / YoY density."""
    found: list[FilingTable] = []
    found.extend(_markdown_tables(text))
    found.extend(_html_tables(text))
    found.sort(key=lambda t: t.start)
    return [t for t in found if t.salience >= min_salience]


def tables_text(tables: list[FilingTable], *, max_chars: int = 120_000) -> str:
    parts: list[str] = []
    used = 0
    for t in sorted(tables, key=lambda x: -x.salience):
        block = f"\n## TABLE ({t.kind}, salience={t.salience:.2f})\n{t.text}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def _score(text: str, rows: int) -> float:
    nums = len(_NUM.findall(text))
    yoy = 1.2 if _YOY.search(text) else 1.0
    density = nums / max(rows, 1)
    return min(1.0, (density / 8.0) * yoy)


def _markdown_tables(text: str) -> list[FilingTable]:
    lines = text.splitlines(keepends=True)
    out: list[FilingTable] = []
    i = 0
    pos = 0
    while i < len(lines):
        if _MD_ROW.match(lines[i]):
            start = pos
            buf = [lines[i]]
            j = i + 1
            p = pos + len(lines[i])
            while j < len(lines) and (
                _MD_ROW.match(lines[j]) or _MD_SEP.match(lines[j])
            ):
                buf.append(lines[j])
                p += len(lines[j])
                j += 1
            body = "".join(buf)
            rows = sum(1 for ln in buf if _MD_ROW.match(ln))
            if rows >= 3:
                out.append(
                    FilingTable(
                        start=start,
                        end=p,
                        text=body,
                        rows=rows,
                        numeric_cells=len(_NUM.findall(body)),
                        salience=_score(body, rows),
                        kind="markdown",
                    )
                )
            i = j
            pos = p
            continue
        pos += len(lines[i])
        i += 1
    return out


def _html_tables(text: str) -> list[FilingTable]:
    out: list[FilingTable] = []
    for m in _HTML_TABLE.finditer(text):
        body = m.group(0)
        rows = body.lower().count("<tr")
        out.append(
            FilingTable(
                start=m.start(),
                end=m.end(),
                text=body,
                rows=max(rows, 1),
                numeric_cells=len(_NUM.findall(body)),
                salience=_score(body, max(rows, 1)),
                kind="html",
            )
        )
    return out
