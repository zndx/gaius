"""Prospects check counts filings new to the KB, not the lookback window."""
from __future__ import annotations

from pathlib import Path

from gaius.engine.services.prospects_service import ProspectsConfig, ProspectsService
from gaius.engine.services.scheduled_task_processor import (
    prospects_catchup_should_enqueue,
)


def test_booked_filing_stems_match_update_flow_names(tmp_path: Path) -> None:
    filings = tmp_path / "current/prospects/slb/filings"
    filings.mkdir(parents=True)
    (filings / "8-k_2026-08-31.md").write_text("booked")
    (filings / "4_2026-09-01.md").write_text("booked")
    svc = ProspectsService(pool=None, config=ProspectsConfig(kb_root=tmp_path))
    stems = svc._booked_filing_stems("SLB")
    assert "8-k_2026-08-31" in stems
    assert "4_2026-09-01" in stems


def test_catchup_does_not_steal_airflow_0700() -> None:
    assert prospects_catchup_should_enqueue(True, hour=6) is False
    assert prospects_catchup_should_enqueue(True, hour=7) is True
    assert prospects_catchup_should_enqueue(False, hour=12) is False
