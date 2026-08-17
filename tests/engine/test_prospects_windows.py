"""Aegir-grain windows and SEC table detect — no GPU."""

from __future__ import annotations

from gaius.flows.prospects.tables import detect_tables, tables_text
from gaius.flows.prospects.windows import admitted_text, scan_windows, token_windows


def _char_offsets(text: str) -> list[tuple[int, int]]:
    return [(i, i + 1) for i in range(len(text))]


def test_token_windows_stride() -> None:
    text = "abcdefghij" * 80  # 800 chars → 800 fake tokens
    spans = token_windows(
        text, stride=256, size=512, max_windows=8, encode_offsets=_char_offsets
    )
    assert spans
    assert spans[0][0] == 0
    assert spans[0][1] - spans[0][0] <= 512
    if len(spans) > 1:
        assert spans[1][0] == 256


def test_scan_windows_maxsim_nonoverlap() -> None:
    text = "x" * 900

    def maxsim(chunk: str) -> tuple[str, float]:
        return ("mda", 0.5)

    scan = scan_windows(
        text,
        encode_offsets=_char_offsets,
        maxsim=maxsim,
        tau=0.1,
        max_windows=8,
    )
    admitted = [w for w in scan.windows if w.admitted]
    assert admitted
    for i, a in enumerate(admitted):
        for b in admitted[i + 1 :]:
            assert a.end <= b.start or b.end <= a.start
    assert "x" in admitted_text(scan)


def test_detect_markdown_table() -> None:
    md = """
# Intro

| Metric | 2024 | 2025 |
| --- | --- | --- |
| Revenue | $100 | $120 |
| Margin | 10% | 12% |
| YoY |  | year-over-year |

trailing prose
"""
    tables = detect_tables(md, min_salience=0.0)
    assert tables
    assert tables[0].kind == "markdown"
    assert tables[0].rows >= 3
    blob = tables_text(tables)
    assert "Revenue" in blob
