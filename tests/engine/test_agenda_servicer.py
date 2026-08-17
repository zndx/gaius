"""Agenda RPCs jail paths and map cards."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gaius.engine.generated import (
    AgendaGetRequest,
    AgendaListRequest,
    AgendaUpdateRequest,
)
from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer
from gaius.engine.services.agenda_notes import create_item


@pytest.mark.asyncio
async def test_agenda_get_bad_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GAIUS_KB_ROOT", str(tmp_path))
    (tmp_path / "scratch").mkdir()
    servicer = GaiusServicer(SimpleNamespace())  # type: ignore[arg-type]
    resp = await servicer.AgendaGet(AgendaGetRequest(path="../x.md"), MagicMock())
    assert "AG.00000003" in resp.error


@pytest.mark.asyncio
async def test_agenda_list_after_create(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GAIUS_KB_ROOT", str(tmp_path))
    (tmp_path / "scratch").mkdir()
    create_item(tmp_path, kind="note", title="Hello")
    servicer = GaiusServicer(SimpleNamespace())  # type: ignore[arg-type]
    resp = await servicer.AgendaList(AgendaListRequest(window_days=14), MagicMock())
    assert resp.error == ""
    assert len(resp.items) == 1
    assert resp.items[0].title == "Hello"
    assert resp.items[0].kind == "note"


@pytest.mark.asyncio
async def test_agenda_update_missing_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GAIUS_KB_ROOT", str(tmp_path))
    (tmp_path / "scratch").mkdir()
    servicer = GaiusServicer(SimpleNamespace())  # type: ignore[arg-type]
    resp = await servicer.AgendaUpdate(
        AgendaUpdateRequest(path="scratch/2026-08-16/missing.md", title="x"),
        MagicMock(),
    )
    assert "AG.00000003" in resp.error
