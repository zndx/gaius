"""Weekly Signals Summary RPCs list and jail paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gaius.engine.generated import (
    WeeklySignalsSummaryGetRequest,
    WeeklySignalsSummaryListRequest,
)
from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer
from gaius.engine.services.weekly_signals_summary import write_zettel


@pytest.mark.asyncio
async def test_list_and_get(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GAIUS_KB_ROOT", str(tmp_path))
    (tmp_path / "scratch").mkdir()
    rel = "scratch/2026-08-17/2026-08-17-160500_w34-summary.md"
    write_zettel(tmp_path, rel, "# Weekly Signals Summary · 2026-W34\n\nbody\n")
    servicer = GaiusServicer(SimpleNamespace())  # type: ignore[arg-type]
    listed = await servicer.WeeklySignalsSummaryList(
        WeeklySignalsSummaryListRequest(limit=5), MagicMock()
    )
    assert listed.error == ""
    assert listed.items[0].path == rel
    got = await servicer.WeeklySignalsSummaryGet(
        WeeklySignalsSummaryGetRequest(path=rel), MagicMock()
    )
    assert "2026-W34" in got.body


@pytest.mark.asyncio
async def test_get_rejects_other_zettel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GAIUS_KB_ROOT", str(tmp_path))
    (tmp_path / "scratch" / "2026-08-17").mkdir(parents=True)
    rel = "scratch/2026-08-17/2026-08-17-010000_other.md"
    (tmp_path / rel).write_text("nope\n", encoding="utf-8")
    servicer = GaiusServicer(SimpleNamespace())  # type: ignore[arg-type]
    resp = await servicer.WeeklySignalsSummaryGet(
        WeeklySignalsSummaryGetRequest(path=rel), MagicMock()
    )
    assert "WS.00000004" in resp.error


def test_weekly_handler_name() -> None:
    from gaius.engine.services.scheduled_task_processor import ScheduledTaskProcessor

    proc = ScheduledTaskProcessor(database_url="postgres://unused")

    async def _fake(_task):  # type: ignore[no-untyped-def]
        return {}

    proc.register_handler("weekly_signals_summary", _fake)
    assert "weekly_signals_summary" in proc._handlers


@pytest.mark.asyncio
async def test_knowledge_handler_name() -> None:
    from gaius.engine.services.scheduled_task_processor import ScheduledTaskProcessor

    proc = ScheduledTaskProcessor(database_url="postgres://unused")
    await proc._register_default_handlers()
    assert "knowledge_summary" in proc._handlers
    assert "weekly_signals_summary" in proc._handlers
