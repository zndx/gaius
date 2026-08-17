"""KB topology board places real paths; Iceberg is a flag, not a warehouse."""

from __future__ import annotations

from pathlib import Path

from gaius.storage.kb_board import build_board_snapshot, place_path


def test_place_current_domain_is_stable() -> None:
    domains = ("articles", "domains", "prospects")
    a = place_path("current/prospects/slb.md", domains)
    b = place_path("current/prospects/slb.md", domains)
    assert a == b
    assert 0 <= a[0] < 19 and 3 <= a[1] < 13


def test_scratch_and_archive_use_different_bands() -> None:
    _, y_cur = place_path("current/foo/a.md")
    _, y_scr = place_path("scratch/2026-08-16/a.md")
    _, y_arc = place_path("archive/2025Q4/a.md")
    assert 3 <= y_cur < 13
    assert 13 <= y_scr < 19
    assert 0 <= y_arc < 3


def test_build_snapshot_from_files(tmp_path: Path) -> None:
    (tmp_path / "current" / "prospects").mkdir(parents=True)
    (tmp_path / "scratch" / "2026-08-16").mkdir(parents=True)
    (tmp_path / "current" / "prospects" / "note.md").write_text("# n\n")
    (tmp_path / "scratch" / "2026-08-16" / "jot.md").write_text("# j\n")
    snap = build_board_snapshot(tmp_path, catalog={})
    assert snap.n_documents == 2
    assert snap.cells_occupied >= 1
    assert snap.projection_method == "kb_topology"
    assert snap.n_iceberg == 0
    assert any(d.path.endswith("note.md") for d in snap.documents)
