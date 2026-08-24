"""Independent Publishing FIFO (article curation, arxiv/biorxiv)."""

from __future__ import annotations

from gaius.engine.services.ambient_buffer import AmbientBuffer, BufferEntry, BufferRole


class PublishingBuffer(AmbientBuffer):
    """Separate deque from Ambient and Prospects; same compaction contract."""


def publishing_entry(
    content: str,
    *,
    source: str,
    url: str = "",
    topic: str = "",
    margin: float = 0.0,
    clt: list | None = None,
    starve: dict | None = None,
) -> BufferEntry:
    meta: dict = {
        "axis": "publish",
        "source": source,
        "topic": topic,
        "margin": margin,
        "clt": clt or [],
    }
    if starve:
        meta["starve"] = starve
    return BufferEntry.create(
        BufferRole.CONTENT, content, source_url=url, metadata=meta
    )
