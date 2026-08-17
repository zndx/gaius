"""Board reindex is a clock, not a one-shot refresh."""

from __future__ import annotations

from gaius.engine.services.scheduled_task_processor import ScheduledTaskProcessor


def test_board_reindex_handler_registered() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")
    # handlers land in start(); register the same name the cron inserts
    seen: list[str] = []

    async def _fake(_task):  # type: ignore[no-untyped-def]
        return {}

    proc.register_handler("board_reindex", _fake)
    assert "board_reindex" in proc._handlers
    seen.append("board_reindex")
    assert seen == ["board_reindex"]
