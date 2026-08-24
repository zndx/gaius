"""Ambient buffer for structured content storage.

Provides a byte-sized FIFO buffer for ambient workload content with
role-based organization. Supports multiple entry types (content, summary,
system, etc.) with configurable size limits from 256KB to 1GB.

Key features:
- Byte-based sizing (not entry count) for flexible capacity
- FIFO eviction of complete entries when limit exceeded
- Role-based filtering and querying
- Thread-safe for async context
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BufferRole(Enum):
    """Semantic roles for buffer entries.

    Each role has a specific purpose in the ambient workload cycle:
    - CONTENT: Raw fetched content (e.g., HN articles/comments)
    - SYSTEM: System prompts or configuration
    - ASSISTANT: LLM-generated responses
    - SUMMARY: Reasoning-derived summaries of content
    - OBJECTIVE: Goals/objectives for processing
    - BENCHMARK: Reference data for comparison
    - SEARCH_QUERY: Generated Brave Search query candidates
    """

    CONTENT = "content"
    SYSTEM = "system"
    ASSISTANT = "assistant"
    SUMMARY = "summary"
    OBJECTIVE = "objective"
    BENCHMARK = "benchmark"
    SEARCH_QUERY = "search_query"


@dataclass
class BufferEntry:
    """A single entry in the ambient buffer.

    Attributes:
        id: Unique identifier (UUID)
        role: Semantic role of this entry
        content: The actual content text
        content_bytes: Cached byte size for efficient sizing
        created_at: When this entry was added
        source_url: Optional URL where content originated
        metadata: Additional context (e.g., title, score, source_id)
    """

    id: str
    role: BufferRole
    content: str
    content_bytes: int
    created_at: datetime
    source_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Calculate byte size if not provided."""
        if self.content_bytes == 0:
            self.content_bytes = len(self.content.encode("utf-8"))

    @classmethod
    def create(
        cls,
        role: BufferRole,
        content: str,
        source_url: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> BufferEntry:
        """Factory method for creating entries with auto-generated ID.

        Args:
            role: Semantic role for this entry
            content: The content text
            source_url: Optional source URL
            metadata: Optional metadata dict

        Returns:
            New BufferEntry with generated ID and calculated byte size
        """
        content_bytes = len(content.encode("utf-8"))
        return cls(
            id=str(uuid.uuid4()),
            role=role,
            content=content,
            content_bytes=content_bytes,
            created_at=datetime.now(),
            source_url=source_url,
            metadata=metadata or {},
        )

    @property
    def content_preview(self) -> str:
        """Get first 200 characters of content for display."""
        if len(self.content) <= 200:
            return self.content
        return self.content[:200] + "..."


class AmbientBuffer:
    """Byte-sized FIFO buffer for ambient workload content.

    Proactively evicts complete entries (oldest first) on every update
    to maintain buffer below the configured capacity target.
    Default 256KB, configurable to 500KB, 5MB, or 1GB.

    Thread-safe using asyncio.Lock for async context.

    Example:
        >>> buffer = AmbientBuffer(max_bytes=256 * 1024)  # 256KB
        >>> entry = BufferEntry.create(BufferRole.CONTENT, "Hello world")
        >>> await buffer.add_entry(entry)
        >>> latest = await buffer.get_latest(role=BufferRole.CONTENT)
    """

    # Size presets for convenience
    SIZE_256KB = 256 * 1024
    SIZE_500KB = 500 * 1024
    SIZE_5MB = 5 * 1024 * 1024
    SIZE_1GB = 1024 * 1024 * 1024

    # Target utilization (evict proactively to maintain headroom)
    TARGET_UTILIZATION = 0.90  # Keep buffer at 90% to allow for new entries

    def __init__(self, max_bytes: int = SIZE_256KB) -> None:
        """Initialize buffer with byte capacity.

        Args:
            max_bytes: Maximum buffer size in bytes (default 256KB)
        """
        self._max_bytes = max_bytes
        self._target_bytes = int(max_bytes * self.TARGET_UTILIZATION)
        self._current_bytes = 0
        self._entries: deque[BufferEntry] = deque()
        self._lock = asyncio.Lock()
        self._eviction_count = 0  # Track total evictions

    async def add_entry(self, entry: BufferEntry) -> str:
        """Add entry to buffer, proactively evicting to maintain target capacity.

        Evicts complete entries (oldest first) until buffer is below target
        capacity. This ensures headroom for new entries and prevents the
        buffer from constantly hitting the hard limit.

        Args:
            entry: The BufferEntry to add

        Returns:
            The entry ID
        """
        async with self._lock:
            # Hard cap only. 90% target is compacted (summarized), not FIFO-dropped.
            while (
                self._current_bytes + entry.content_bytes > self._max_bytes
                and self._entries
            ):
                evicted = self._entries.popleft()
                self._current_bytes -= evicted.content_bytes
                self._eviction_count += 1
            self._entries.append(entry)
            self._current_bytes += entry.content_bytes
            return entry.id

    def token_estimate(self) -> int:
        from gaius.engine.services.buffer_compaction import estimate_tokens

        return sum(estimate_tokens(e.content) for e in self._entries)

    def needs_compact(self) -> bool:
        from gaius.engine.services.buffer_compaction import (
            KEEP_RECENT_TOKENS,
            over_token_budget,
        )

        if self._current_bytes > self._target_bytes:
            return True
        tokens = self.token_estimate()
        return over_token_budget(tokens) or tokens > KEEP_RECENT_TOKENS * 2

    async def compact_if_needed(self, summarize) -> dict[str, object]:
        """Replace prefix with a structured summary. ``summarize(prompt) -> str``."""
        from gaius.engine.services.buffer_compaction import (
            GURU,
            compaction_prompt,
            plan_compaction,
        )

        async with self._lock:
            snapshot = list(self._entries)
        if not self.needs_compact() and self._current_bytes <= self._target_bytes:
            return {"skipped": True, "reason": "under budget"}
        from gaius.engine.services.buffer_compaction import (
            CHARS_PER_TOKEN,
            KEEP_RECENT_TOKENS,
        )

        keep_bytes = None
        if self._current_bytes > self._target_bytes:
            keep_bytes = min(
                KEEP_RECENT_TOKENS * CHARS_PER_TOKEN,
                max(self._target_bytes // 2, 1),
            )
        plan = plan_compaction(snapshot, keep_recent_bytes=keep_bytes)
        if plan is None:
            return {"skipped": True, "reason": "nothing to cut"}
        drop_ids = {e.id for e in snapshot[: plan.cut_index]}
        prompt = compaction_prompt(plan.material, plan.prior)
        try:
            summary = await summarize(prompt)
        except Exception as e:
            raise RuntimeError(f"{GURU}\n  {e}") from e
        if not (summary or "").strip():
            raise RuntimeError(f"{GURU}\n  empty summary")
        compact_entry = BufferEntry.create(
            role=BufferRole.SUMMARY,
            content=summary.strip(),
            metadata={
                "kind": "compaction",
                "first_kept_id": plan.first_kept_id,
                "dropped": plan.dropped,
            },
        )
        async with self._lock:
            kept = [e for e in self._entries if e.id not in drop_ids]
            self._entries = deque([compact_entry, *kept])
            self._current_bytes = sum(e.content_bytes for e in self._entries)
        return {
            "success": True,
            "dropped": plan.dropped,
            "first_kept_id": plan.first_kept_id,
            "bytes": self._current_bytes,
        }

    async def get_entries_by_role(
        self,
        role: BufferRole,
        limit: int | None = None,
    ) -> list[BufferEntry]:
        """Get all entries with the given role.

        Args:
            role: The BufferRole to filter by
            limit: Optional max entries to return (most recent N)

        Returns:
            List of matching entries, ordered oldest to newest
        """
        async with self._lock:
            matches = [e for e in self._entries if e.role == role]
            if limit is not None:
                matches = matches[-limit:]
            return list(matches)

    async def get_latest(
        self,
        role: BufferRole | None = None,
        n: int = 1,
    ) -> list[BufferEntry]:
        """Get N most recent entries, optionally filtered by role.

        Args:
            role: Optional role filter (None = all roles)
            n: Number of entries to return (default 1)

        Returns:
            List of entries, newest first
        """
        async with self._lock:
            if role is not None:
                candidates = [e for e in self._entries if e.role == role]
            else:
                candidates = list(self._entries)

            # Take last N and reverse for newest-first order
            return list(reversed(candidates[-n:]))

    async def get_latest_one(
        self,
        role: BufferRole | None = None,
    ) -> BufferEntry | None:
        """Get the single most recent entry.

        Convenience method for getting just one entry.

        Args:
            role: Optional role filter

        Returns:
            Most recent entry or None if buffer empty/no matches
        """
        entries = await self.get_latest(role=role, n=1)
        return entries[0] if entries else None

    async def evict_oldest(self, n: int = 1) -> list[BufferEntry]:
        """Explicitly evict N oldest entries.

        Args:
            n: Number of entries to evict

        Returns:
            List of evicted entries
        """
        async with self._lock:
            evicted = []
            for _ in range(min(n, len(self._entries))):
                entry = self._entries.popleft()
                self._current_bytes -= entry.content_bytes
                evicted.append(entry)
            return evicted

    async def clear(self, role: BufferRole | None = None) -> int:
        """Clear all entries or entries with a specific role.

        Args:
            role: Optional role filter (None = clear all)

        Returns:
            Number of entries cleared
        """
        async with self._lock:
            if role is None:
                count = len(self._entries)
                self._entries.clear()
                self._current_bytes = 0
                return count

            # Filter out entries with matching role
            original_count = len(self._entries)
            remaining = deque(e for e in self._entries if e.role != role)
            self._entries = remaining
            self._current_bytes = sum(e.content_bytes for e in remaining)
            return original_count - len(remaining)

    def get_stats(self) -> dict[str, Any]:
        """Get buffer statistics (sync method for status reporting).

        Returns:
            Dict with current_bytes, max_bytes, utilization, entry_count,
            and entries_by_role breakdown.
        """
        entries_by_role = {
            role.value: sum(1 for e in self._entries if e.role == role)
            for role in BufferRole
        }
        bytes_by_role = {
            role.value: sum(e.content_bytes for e in self._entries if e.role == role)
            for role in BufferRole
        }

        return {
            "current_bytes": self._current_bytes,
            "max_bytes": self._max_bytes,
            "target_bytes": self._target_bytes,
            "utilization": (
                self._current_bytes / self._max_bytes if self._max_bytes > 0 else 0.0
            ),
            "entry_count": len(self._entries),
            "eviction_count": self._eviction_count,
            "entries_by_role": entries_by_role,
            "bytes_by_role": bytes_by_role,
        }

    @property
    def current_bytes(self) -> int:
        """Current buffer size in bytes."""
        return self._current_bytes

    @property
    def max_bytes(self) -> int:
        """Maximum buffer size in bytes."""
        return self._max_bytes

    @property
    def entry_count(self) -> int:
        """Current number of entries."""
        return len(self._entries)

    def __len__(self) -> int:
        """Return number of entries."""
        return len(self._entries)
