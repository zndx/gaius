"""Activity tracking for Gaius.

Tracks user actions, queries, and system events for situational awareness
and daily summary generation.

Usage:
    from gaius.core.activity import ActivityTracker, ActivityType

    tracker = ActivityTracker()
    await tracker.log_event(ActivityType.QUERY, details={"query": "...", "results": 10})

    # Get activity summaries
    today = await tracker.get_today()
    week = await tracker.get_this_week()
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False


class ActivityType(str, Enum):
    """Types of tracked activities."""

    QUERY = "query"
    DOMAIN_CHANGE = "domain_change"
    SWARM_RUN = "swarm_run"
    TDA_COMPUTE = "tda_compute"
    PROJECTION = "projection"
    KB_CREATE = "kb_create"
    KB_UPDATE = "kb_update"
    COMMAND = "command"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


@dataclass
class ActivityEvent:
    """A tracked activity event."""

    event_type: ActivityType
    profile_name: str | None = None
    domain: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass
class ActivitySummary:
    """Summary of activity for a time period."""

    period: str  # "today", "yesterday", "this_week"
    start_date: date
    end_date: date
    events_by_type: dict[ActivityType, int] = field(default_factory=dict)
    total_events: int = 0
    domains_active: list[str] = field(default_factory=list)
    queries: int = 0
    swarm_runs: int = 0
    kb_entries: int = 0
    total_tokens: int = 0

    def to_markdown(self) -> str:
        """Format summary as markdown."""
        lines = [f"## Activity: {self.period.replace('_', ' ').title()}"]
        lines.append(f"*{self.start_date} to {self.end_date}*\n")

        if self.total_events == 0:
            lines.append("No activity recorded.")
            return "\n".join(lines)

        lines.append(f"- **Total events:** {self.total_events}")
        if self.queries:
            lines.append(f"- **Queries:** {self.queries}")
        if self.swarm_runs:
            lines.append(f"- **Swarm runs:** {self.swarm_runs}")
        if self.kb_entries:
            lines.append(f"- **KB entries created:** {self.kb_entries}")
        if self.total_tokens:
            lines.append(f"- **Tokens used:** {self.total_tokens:,}")

        if self.domains_active:
            lines.append(f"\n**Active domains:** {', '.join(self.domains_active)}")

        return "\n".join(lines)


class ActivityTracker:
    """Tracks and queries user activity.

    Uses PostgreSQL for persistence when available,
    falls back to in-memory tracking.
    """

    def __init__(self, db_url: str | None = None):
        """Initialize activity tracker.

        Args:
            db_url: PostgreSQL connection URL. If None, uses config or in-memory.
        """
        self._db_url = db_url
        self._pool: "asyncpg.Pool | None" = None
        self._memory_events: list[ActivityEvent] = []
        self._use_memory = not ASYNCPG_AVAILABLE

    async def _get_pool(self) -> "asyncpg.Pool | None":
        """Get or create database connection pool."""
        if self._use_memory:
            return None

        if self._pool is None:
            if self._db_url is None:
                from .config import get_config

                config = get_config()
                self._db_url = config.database.url

            try:
                self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=5)
            except Exception:
                self._use_memory = True
                return None

        return self._pool

    async def log_event(
        self,
        event_type: ActivityType,
        profile_name: str | None = None,
        domain: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ActivityEvent:
        """Log an activity event.

        Args:
            event_type: Type of event
            profile_name: Active profile name
            domain: Current domain context
            details: Additional event details (JSON-serializable)

        Returns:
            The created ActivityEvent
        """
        event = ActivityEvent(
            event_type=event_type,
            profile_name=profile_name,
            domain=domain,
            details=details or {},
            created_at=datetime.now(),
        )

        pool = await self._get_pool()

        if pool is not None:
            try:
                import json

                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO activity_events (event_type, profile_name, domain, details)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id, created_at
                        """,
                        event_type.value,
                        profile_name,
                        domain,
                        json.dumps(details or {}),
                    )
                    event.id = row["id"]
                    event.created_at = row["created_at"]
            except Exception:
                # Fall back to memory on error
                self._memory_events.append(event)
        else:
            self._memory_events.append(event)

        return event

    async def get_today(self) -> ActivitySummary:
        """Get activity summary for today."""
        today = date.today()
        return await self._get_summary("today", today, today)

    async def get_yesterday(self) -> ActivitySummary:
        """Get activity summary for yesterday."""
        yesterday = date.today() - timedelta(days=1)
        return await self._get_summary("yesterday", yesterday, yesterday)

    async def get_this_week(self) -> ActivitySummary:
        """Get activity summary for this week."""
        today = date.today()
        # Start of week (Monday)
        start = today - timedelta(days=today.weekday())
        return await self._get_summary("this_week", start, today)

    async def get_recent_events(
        self,
        limit: int = 20,
        event_type: ActivityType | None = None,
    ) -> list[ActivityEvent]:
        """Get recent activity events.

        Args:
            limit: Maximum number of events to return
            event_type: Filter by event type

        Returns:
            List of recent events, newest first
        """
        pool = await self._get_pool()

        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    if event_type:
                        rows = await conn.fetch(
                            """
                            SELECT id, event_type, profile_name, domain, details, created_at
                            FROM activity_events
                            WHERE event_type = $1
                            ORDER BY created_at DESC
                            LIMIT $2
                            """,
                            event_type.value,
                            limit,
                        )
                    else:
                        rows = await conn.fetch(
                            """
                            SELECT id, event_type, profile_name, domain, details, created_at
                            FROM activity_events
                            ORDER BY created_at DESC
                            LIMIT $1
                            """,
                            limit,
                        )

                    return [
                        ActivityEvent(
                            id=row["id"],
                            event_type=ActivityType(row["event_type"]),
                            profile_name=row["profile_name"],
                            domain=row["domain"],
                            details=row["details"] if isinstance(row["details"], dict) else {},
                            created_at=row["created_at"],
                        )
                        for row in rows
                    ]
            except Exception:
                pass

        # Memory fallback
        events = self._memory_events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return sorted(events, key=lambda e: e.created_at, reverse=True)[:limit]

    async def _get_summary(
        self,
        period: str,
        start_date: date,
        end_date: date,
    ) -> ActivitySummary:
        """Get activity summary for a date range."""
        summary = ActivitySummary(
            period=period,
            start_date=start_date,
            end_date=end_date,
        )

        pool = await self._get_pool()

        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    # Get event counts by type
                    rows = await conn.fetch(
                        """
                        SELECT event_type, COUNT(*) as count
                        FROM activity_events
                        WHERE created_at >= $1 AND created_at < $2 + INTERVAL '1 day'
                        GROUP BY event_type
                        """,
                        datetime.combine(start_date, datetime.min.time()),
                        datetime.combine(end_date, datetime.min.time()),
                    )

                    for row in rows:
                        evt_type = ActivityType(row["event_type"])
                        summary.events_by_type[evt_type] = row["count"]
                        summary.total_events += row["count"]

                        if evt_type == ActivityType.QUERY:
                            summary.queries = row["count"]
                        elif evt_type == ActivityType.SWARM_RUN:
                            summary.swarm_runs = row["count"]
                        elif evt_type == ActivityType.KB_CREATE:
                            summary.kb_entries += row["count"]

                    # Get unique domains
                    domains = await conn.fetch(
                        """
                        SELECT DISTINCT domain
                        FROM activity_events
                        WHERE created_at >= $1 AND created_at < $2 + INTERVAL '1 day'
                        AND domain IS NOT NULL
                        """,
                        datetime.combine(start_date, datetime.min.time()),
                        datetime.combine(end_date, datetime.min.time()),
                    )
                    summary.domains_active = [r["domain"] for r in domains]

                    # Get total tokens from swarm runs
                    tokens = await conn.fetchval(
                        """
                        SELECT COALESCE(SUM((details->>'tokens')::int), 0)
                        FROM activity_events
                        WHERE created_at >= $1 AND created_at < $2 + INTERVAL '1 day'
                        AND event_type = 'swarm_run'
                        AND details ? 'tokens'
                        """,
                        datetime.combine(start_date, datetime.min.time()),
                        datetime.combine(end_date, datetime.min.time()),
                    )
                    summary.total_tokens = tokens or 0

            except Exception:
                pass
        else:
            # Memory fallback
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

            for event in self._memory_events:
                if start_dt <= event.created_at < end_dt:
                    summary.total_events += 1
                    summary.events_by_type[event.event_type] = (
                        summary.events_by_type.get(event.event_type, 0) + 1
                    )
                    if event.domain and event.domain not in summary.domains_active:
                        summary.domains_active.append(event.domain)

                    if event.event_type == ActivityType.QUERY:
                        summary.queries += 1
                    elif event.event_type == ActivityType.SWARM_RUN:
                        summary.swarm_runs += 1
                        summary.total_tokens += event.details.get("tokens", 0)
                    elif event.event_type == ActivityType.KB_CREATE:
                        summary.kb_entries += 1

        return summary

    async def close(self) -> None:
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None


# Module-level singleton
_tracker: ActivityTracker | None = None


def get_activity_tracker() -> ActivityTracker:
    """Get or create the activity tracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = ActivityTracker()
    return _tracker


async def log_activity(
    event_type: ActivityType,
    profile_name: str | None = None,
    domain: str | None = None,
    details: dict[str, Any] | None = None,
) -> ActivityEvent:
    """Convenience function to log an activity event."""
    tracker = get_activity_tracker()
    return await tracker.log_event(event_type, profile_name, domain, details)
