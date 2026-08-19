"""Corpus clock: watermark, overlap, quarantine, exemplar staleness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gaius.engine.services.clt_skos_clock import (
    ExtractMiss,
    exemplar_hash,
    is_stale,
    jaccard,
    next_watermark,
    require_extracted,
)


def test_watermark_advances_per_doc_not_backwards() -> None:
    t0 = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)
    t_late = t0 - timedelta(minutes=10)
    assert next_watermark(None, t0) == t0
    assert next_watermark(t0, t1) == t1
    assert next_watermark(t1, t_late) == t1


def test_jaccard_stale_threshold() -> None:
    assert jaccard({1, 2, 3}, {1, 2, 3}) == 1.0
    assert is_stale([1, 2, 3, 4, 5], [9, 8, 7, 6, 5])
    assert not is_stale([1, 2, 3, 4, 5, 6, 7, 8], [1, 2, 3, 4, 5, 6, 7, 9])
    assert exemplar_hash([(1, 0, 10), (2, 3, 8)]) == exemplar_hash(
        [(2, 3, 8), (1, 0, 10)]
    )


def test_require_extracted_quarantines_without_body(tmp_path) -> None:
    doc = {
        "title": "Stressor identity shapes plasma proteomic and metabolic responses in humans",
        "summary": "A short blurb.",
        "kb_path": "",
        "iceberg_id": "",
        "source_id": "21819",
    }
    with pytest.raises(ExtractMiss, match="NOEXTRACT") as ei:
        require_extracted(doc, kb_root=tmp_path)
    assert "no kb_path, no Iceberg body" in ei.value.reason


def test_require_extracted_reads_kb(tmp_path) -> None:
    rel = "current/content/example.md"
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True)
    dest.write_text("# Full\n\nBody of the article.\n", encoding="utf-8")
    doc = {
        "title": "Full",
        "summary": "blurb",
        "kb_path": rel,
        "iceberg_id": "",
        "source_id": "1",
    }
    text, origin = require_extracted(doc, kb_root=tmp_path)
    assert "Body of the article" in text
    assert origin.startswith("kb:")
