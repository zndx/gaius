"""In-memory FIFO for prospects, same byte contract as AmbientBuffer."""

from __future__ import annotations

from enum import Enum

from gaius.engine.services.ambient_buffer import AmbientBuffer, BufferEntry


class ProspectsRole(Enum):
    FILING = "filing"
    TABLE = "table"
    WINDOW = "window"
    COMPACT = "compact"
    SUMMARY = "summary"
    FMP = "fmp"


class ProspectsBuffer(AmbientBuffer):
    """Separate deque from Ambient; same FIFO / 90% target."""


def entry(role: ProspectsRole, content: str, **metadata: object) -> BufferEntry:
    from gaius.engine.services.ambient_buffer import BufferRole

    # Ambient BufferEntry requires BufferRole; store prospects role in metadata
    # and use ASSISTANT/CONTENT as the FIFO role bucket.
    bucket = {
        ProspectsRole.FILING: BufferRole.CONTENT,
        ProspectsRole.FMP: BufferRole.CONTENT,
        ProspectsRole.TABLE: BufferRole.CONTENT,
        ProspectsRole.WINDOW: BufferRole.CONTENT,
        ProspectsRole.COMPACT: BufferRole.SUMMARY,
        ProspectsRole.SUMMARY: BufferRole.SUMMARY,
    }[role]
    meta = dict(metadata)
    meta["prospects_role"] = role.value
    return BufferEntry.create(bucket, content, metadata=meta)
