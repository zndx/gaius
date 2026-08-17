"""Ambient default-on vs operator-disable vs Yield pause."""

from __future__ import annotations

import pytest

from gaius.engine.services.ambient_service import ambient_boot_action


def test_boot_starts_when_never_ran() -> None:
    assert ambient_boot_action(None, auto_start=True) == "start"
    assert ambient_boot_action({"running": False}, auto_start=True) == "start"


def test_boot_resumes_if_was_running() -> None:
    assert ambient_boot_action({"running": True}, auto_start=True) == "resume"


def test_boot_skips_operator_disabled() -> None:
    assert (
        ambient_boot_action(
            {"running": False, "operator_disabled": True},
            auto_start=True,
        )
        == "skip"
    )


def test_boot_skips_when_flag_off() -> None:
    assert ambient_boot_action({"running": True}, auto_start=False) == "skip"


def test_pause_gpu_keeps_buffer() -> None:
    from gaius.engine.services.ambient_buffer import AmbientBuffer, BufferEntry, BufferRole
    from gaius.engine.config import EngineConfig
    from gaius.engine.services.ambient_service import AmbientWorkloadService

    class _Orch:
        pass

    class _Router:
        pass

    svc = AmbientWorkloadService(
        config=EngineConfig(),
        orchestrator=_Orch(),  # type: ignore[arg-type]
        backend_router=_Router(),  # type: ignore[arg-type]
        db_pool=None,
    )
    import asyncio

    async def _go() -> None:
        await svc._buffer.add_entry(
            BufferEntry.create(role=BufferRole.CONTENT, content="hn item")
        )
        await svc.pause_gpu("yield:extract")
        assert svc._gpu_paused is True
        stats = svc._buffer.get_stats()
        assert stats["entry_count"] >= 1

    asyncio.run(_go())
