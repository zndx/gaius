"""Ambient cycle ticks Prospects and Publishing independently before synthesis."""

from __future__ import annotations

import pytest

from gaius.engine.services.ambient_service import AmbientWorkloadService


class _Buf:
    def __init__(self) -> None:
        self.compacted = 0

    async def compact_if_needed(self, _fn) -> dict:
        self.compacted += 1
        return {"skipped": False, "dropped": 0, "bytes": 1}


class _Prospects:
    def __init__(self) -> None:
        self.ingests = 0
        self.compacts = 0
        self._buffer = _Buf()

    async def ingest_market_buffer(self) -> dict:
        self.ingests += 1
        return {"ingested": 3, "buffer_bytes": 99}

    async def compact_buffer(self) -> dict:
        self.compacts += 1
        return {"skipped": False, "dropped": 1}


class _PublishAxis:
    def __init__(self) -> None:
        self.ingests = 0
        self.buffer = _Buf()
        self._summarize = lambda t: t

    async def ingest(self) -> dict:
        self.ingests += 1
        return {"ingested": 2, "buffer_bytes": 40}


@pytest.mark.asyncio
async def test_cycle_ticks_prospects_and_publishing_before_synthesis() -> None:
    svc = AmbientWorkloadService.__new__(AmbientWorkloadService)
    svc._prospects_service = _Prospects()
    axis = _PublishAxis()
    svc.attach_publishing_axis(axis)
    svc._summarize_compaction = lambda t: t

    p = await svc._tick_prospects_ingest()
    u = await svc._tick_publishing_ingest()
    assert p["ingested"] == 3
    assert u["ingested"] == 2
    assert svc._prospects_service.ingests == 1
    assert axis.ingests == 1

    pc = await svc._tick_prospects_compact()
    uc = await svc._tick_publishing_compact()
    assert pc["dropped"] == 1
    assert uc["dropped"] == 0
    assert svc._prospects_service.compacts == 1
    assert axis.buffer.compacted == 1


@pytest.mark.asyncio
async def test_missing_axis_is_error_not_skip() -> None:
    svc = AmbientWorkloadService.__new__(AmbientWorkloadService)
    svc._prospects_service = None
    svc._publishing_axis = None
    svc._publishing_buffer = None
    p = await svc._tick_prospects_ingest()
    u = await svc._tick_publishing_ingest()
    assert "error" in p
    assert "error" in u
