"""Session Management for Gaius.

Tracks session lifecycle, preserves context across sessions, and enables
"where we left off" continuity.

Key Concepts:
- Session: A continuous period of user interaction
- Research Thread: An ongoing line of investigation that spans sessions
- Handoff: Summary of previous session for continuity

Usage:
    from gaius.core.session import SessionManager, get_session_manager

    manager = get_session_manager()
    session, handoff = await manager.start_session()
    # ... user interaction ...
    await manager.end_session()
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
import logging

from .config import get_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Enums and Data Classes
# ═══════════════════════════════════════════════════════════════════════════════


class ThreadStatus(str, Enum):
    """Status of a research thread."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ThreadPriority(str, Enum):
    """Priority level of a research thread."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class ResearchThread:
    """An ongoing research investigation that spans sessions."""

    topic: str
    domain: str | None = None
    status: ThreadStatus = ThreadStatus.ACTIVE
    priority: ThreadPriority = ThreadPriority.NORMAL

    # Content
    initial_query: str = ""
    goal: str = ""
    current_focus: str = ""

    # Accumulated work
    queries: list[dict] = field(default_factory=list)  # [{query, timestamp, results_count}]
    kb_entries: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    next_steps: str = ""

    # Metrics
    query_count: int = 0
    entry_count: int = 0
    swarm_run_count: int = 0

    # Timestamps
    id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "topic": self.topic,
            "domain": self.domain,
            "status": self.status.value,
            "priority": self.priority.value,
            "initial_query": self.initial_query,
            "goal": self.goal,
            "current_focus": self.current_focus,
            "queries": self.queries,
            "kb_entries": self.kb_entries,
            "insights": self.insights,
            "next_steps": self.next_steps,
            "query_count": self.query_count,
            "entry_count": self.entry_count,
            "swarm_run_count": self.swarm_run_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
        }

    def to_markdown(self) -> str:
        """Format thread as markdown section."""
        status_indicator = {
            ThreadStatus.ACTIVE: "[*]",
            ThreadStatus.PAUSED: "[=]",
            ThreadStatus.COMPLETED: "[OK]",
            ThreadStatus.ABANDONED: "[X]",
        }.get(self.status, "[?]")

        lines = [f"### {status_indicator} {self.topic}"]

        if self.domain:
            lines.append(f"*Domain: {self.domain}*")

        if self.current_focus:
            lines.append(f"\n**Current focus:** {self.current_focus}")

        if self.insights:
            lines.append("\n**Insights:**")
            for insight in self.insights[-3:]:
                lines.append(f"- {insight}")

        if self.kb_entries:
            lines.append(f"\n**KB entries:** {len(self.kb_entries)}")

        if self.next_steps:
            lines.append(f"\n**Next:** {self.next_steps}")

        return "\n".join(lines)


@dataclass
class Session:
    """A single user session."""

    profile_name: str = "default"
    id: str | None = None

    # Lifecycle
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    duration_seconds: int | None = None

    # Context
    initial_domain: str | None = None
    final_domain: str | None = None

    # Captured state
    open_threads: list[ResearchThread] = field(default_factory=list)
    key_topics: list[str] = field(default_factory=list)
    research_notes: str = ""

    # Metrics
    queries: int = 0
    swarm_runs: int = 0
    kb_entries: int = 0
    domains_visited: list[str] = field(default_factory=list)
    tokens_used: int = 0

    # Handoff
    handoff_generated: bool = False
    handoff_summary: str = ""
    handoff_kb_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "profile_name": self.profile_name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "initial_domain": self.initial_domain,
            "final_domain": self.final_domain,
            "open_threads": [t.to_dict() for t in self.open_threads],
            "key_topics": self.key_topics,
            "research_notes": self.research_notes,
            "metrics": {
                "queries": self.queries,
                "swarm_runs": self.swarm_runs,
                "kb_entries": self.kb_entries,
                "domains_visited": self.domains_visited,
                "tokens_used": self.tokens_used,
            },
            "handoff_generated": self.handoff_generated,
            "handoff_summary": self.handoff_summary,
            "handoff_kb_path": self.handoff_kb_path,
        }


@dataclass
class SessionHandoff:
    """Handoff information from previous session."""

    previous_session: Session | None = None
    time_since_last: timedelta | None = None
    open_threads: list[ResearchThread] = field(default_factory=list)
    summary: str = ""
    quick_context: str = ""  # 1-2 sentence version

    def has_content(self) -> bool:
        """Check if handoff has meaningful content."""
        return bool(self.summary or self.open_threads)

    def to_markdown(self) -> str:
        """Format handoff as markdown section."""
        if not self.has_content():
            return ""

        lines = ["## Where We Left Off"]

        if self.time_since_last:
            hours = self.time_since_last.total_seconds() / 3600
            if hours < 1:
                time_str = f"{int(hours * 60)} minutes ago"
            elif hours < 24:
                time_str = f"{hours:.1f} hours ago"
            else:
                days = hours / 24
                time_str = f"{days:.1f} days ago"
            lines.append(f"*Last session: {time_str}*")

        if self.previous_session:
            ps = self.previous_session
            duration = ""
            if ps.duration_seconds:
                mins = ps.duration_seconds // 60
                duration = f" ({mins} min)"
            lines.append(f"*Duration: {duration}*")

        lines.append("")

        if self.summary:
            lines.append(self.summary)
            lines.append("")

        if self.open_threads:
            lines.append("### Open Threads")
            for thread in self.open_threads[:3]:
                lines.append(thread.to_markdown())
                lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Session Manager
# ═══════════════════════════════════════════════════════════════════════════════


class SessionManager:
    """Manages session lifecycle and continuity.

    Handles:
    - Session start/end tracking
    - Research thread detection and persistence
    - Handoff generation for session continuity
    """

    def __init__(self, profile: str = "default"):
        self.profile = profile
        self.config = get_config()
        self._current_session: Session | None = None
        self._session_gap_hours = 4  # Gap that defines a new session

    @property
    def current_session(self) -> Session | None:
        """Get the current active session."""
        return self._current_session

    async def start_session(
        self,
        domain: str | None = None,
    ) -> tuple[Session, SessionHandoff]:
        """Start a new session.

        Args:
            domain: Initial domain context

        Returns:
            Tuple of (new session, handoff from previous)
        """
        # Get handoff from previous session
        handoff = await self.get_handoff()

        # Create new session
        session = Session(
            profile_name=self.profile,
            started_at=datetime.now(),
            initial_domain=domain,
        )

        # Persist to database
        session.id = await self._save_session(session)

        self._current_session = session

        logger.info(f"Started session {session.id}")

        return session, handoff

    async def end_session(
        self,
        domain: str | None = None,
        generate_handoff: bool = True,
    ) -> Session | None:
        """End the current session.

        Args:
            domain: Final domain context
            generate_handoff: Whether to generate LLM handoff summary

        Returns:
            The completed session
        """
        if self._current_session is None:
            logger.warning("No active session to end")
            return None

        session = self._current_session
        session.ended_at = datetime.now()
        session.final_domain = domain

        # Calculate duration
        if session.started_at:
            delta = session.ended_at - session.started_at
            session.duration_seconds = int(delta.total_seconds())

        # Gather session metrics
        await self._gather_session_metrics(session)

        # Detect open research threads
        session.open_threads = await self._detect_open_threads(session)

        # Generate handoff summary
        if generate_handoff and (session.queries > 0 or session.kb_entries > 0):
            session.handoff_summary = await self._generate_handoff_summary(session)
            session.handoff_generated = True

        # Update in database
        await self._update_session(session)

        logger.info(
            f"Ended session {session.id} "
            f"(duration: {session.duration_seconds}s, "
            f"queries: {session.queries}, "
            f"threads: {len(session.open_threads)})"
        )

        self._current_session = None

        return session

    async def get_handoff(self) -> SessionHandoff:
        """Get handoff information from previous session.

        Returns:
            SessionHandoff with context from previous session
        """
        handoff = SessionHandoff()

        # Get most recent completed session
        prev_session = await self._get_previous_session()

        if prev_session is None:
            return handoff

        handoff.previous_session = prev_session

        # Calculate time since last session
        if prev_session.ended_at:
            handoff.time_since_last = datetime.now() - prev_session.ended_at

        # Get open threads
        handoff.open_threads = await self.get_active_threads()

        # Use existing handoff summary or generate quick context
        if prev_session.handoff_summary:
            handoff.summary = prev_session.handoff_summary
        elif prev_session.key_topics:
            topics = ", ".join(prev_session.key_topics[:3])
            handoff.quick_context = f"Last explored: {topics}"

        return handoff

    async def get_active_threads(self, limit: int = 5) -> list[ResearchThread]:
        """Get active research threads from database."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, topic, domain, status, priority,
                           initial_query, goal, current_focus,
                           queries, kb_entries, insights, next_steps,
                           query_count, entry_count, swarm_run_count,
                           created_at, updated_at, last_activity
                    FROM research_threads
                    WHERE profile_name = $1 AND status = 'active'
                    ORDER BY last_activity DESC
                    LIMIT $2
                    """,
                    self.profile,
                    limit,
                )

                return [
                    ResearchThread(
                        id=str(row["id"]),
                        topic=row["topic"],
                        domain=row["domain"],
                        status=ThreadStatus(row["status"]),
                        priority=ThreadPriority(row["priority"]),
                        initial_query=row["initial_query"] or "",
                        goal=row["goal"] or "",
                        current_focus=row["current_focus"] or "",
                        queries=row["queries"] or [],
                        kb_entries=row["kb_entries"] or [],
                        insights=row["insights"] or [],
                        next_steps=row["next_steps"] or "",
                        query_count=row["query_count"],
                        entry_count=row["entry_count"],
                        swarm_run_count=row["swarm_run_count"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        last_activity=row["last_activity"],
                    )
                    for row in rows
                ]

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to get active threads: {e}")
            return []

    async def create_thread(
        self,
        topic: str,
        domain: str | None = None,
        initial_query: str = "",
        goal: str = "",
    ) -> ResearchThread:
        """Create a new research thread.

        Args:
            topic: Thread topic
            domain: Domain context
            initial_query: The query that started this thread
            goal: Research goal

        Returns:
            Created ResearchThread
        """
        thread = ResearchThread(
            topic=topic,
            domain=domain,
            initial_query=initial_query,
            goal=goal,
            status=ThreadStatus.ACTIVE,
        )

        # Persist to database
        try:
            import asyncpg
            import json

            conn = await asyncpg.connect(self.config.database.url)
            try:
                result = await conn.fetchval(
                    """
                    INSERT INTO research_threads
                        (profile_name, topic, domain, status, priority,
                         initial_query, goal, current_focus,
                         queries, kb_entries, insights, next_steps,
                         created_session_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    RETURNING id
                    """,
                    self.profile,
                    thread.topic,
                    thread.domain,
                    thread.status.value,
                    thread.priority.value,
                    thread.initial_query,
                    thread.goal,
                    thread.current_focus,
                    json.dumps(thread.queries),
                    thread.kb_entries,
                    json.dumps(thread.insights),
                    thread.next_steps,
                    self._current_session.id if self._current_session else None,
                )
                thread.id = str(result)

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to save thread: {e}")

        return thread

    async def update_thread(
        self,
        thread_id: str,
        current_focus: str | None = None,
        next_steps: str | None = None,
        add_query: dict | None = None,
        add_kb_entry: str | None = None,
        add_insight: str | None = None,
        status: ThreadStatus | None = None,
    ) -> bool:
        """Update a research thread.

        Args:
            thread_id: Thread ID to update
            current_focus: New focus area
            next_steps: Updated next steps
            add_query: Query to append
            add_kb_entry: KB entry path to append
            add_insight: Insight to append
            status: New status

        Returns:
            True if updated successfully
        """
        try:
            import asyncpg
            import json

            conn = await asyncpg.connect(self.config.database.url)
            try:
                # Build update dynamically
                updates = ["updated_at = NOW()", "last_activity = NOW()"]
                params = [thread_id]
                param_idx = 2

                if current_focus is not None:
                    updates.append(f"current_focus = ${param_idx}")
                    params.append(current_focus)
                    param_idx += 1

                if next_steps is not None:
                    updates.append(f"next_steps = ${param_idx}")
                    params.append(next_steps)
                    param_idx += 1

                if status is not None:
                    updates.append(f"status = ${param_idx}")
                    params.append(status.value)
                    param_idx += 1

                if add_query is not None:
                    updates.append(f"queries = queries || ${param_idx}::jsonb")
                    updates.append("query_count = query_count + 1")
                    params.append(json.dumps([add_query]))
                    param_idx += 1

                if add_kb_entry is not None:
                    updates.append(f"kb_entries = array_append(kb_entries, ${param_idx})")
                    updates.append("entry_count = entry_count + 1")
                    params.append(add_kb_entry)
                    param_idx += 1

                if add_insight is not None:
                    updates.append(f"insights = insights || ${param_idx}::jsonb")
                    params.append(json.dumps([add_insight]))
                    param_idx += 1

                # Update last session if we have one
                if self._current_session and self._current_session.id:
                    updates.append(f"last_session_id = ${param_idx}::uuid")
                    params.append(self._current_session.id)
                    param_idx += 1

                sql = f"""
                    UPDATE research_threads
                    SET {', '.join(updates)}
                    WHERE id = $1::uuid
                """

                await conn.execute(sql, *params)
                return True

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to update thread: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Private Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def _save_session(self, session: Session) -> str | None:
        """Save session to database."""
        from ..storage.grid_state import check_database_availability

        # Check availability first (cached, logs once)
        if not await check_database_availability():
            return None

        try:
            import asyncpg
            import json

            conn = await asyncpg.connect(self.config.database.url)
            try:
                result = await conn.fetchval(
                    """
                    INSERT INTO sessions
                        (profile_name, started_at, initial_domain, metrics)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id
                    """,
                    session.profile_name,
                    session.started_at,
                    session.initial_domain,
                    json.dumps({
                        "queries": 0,
                        "swarm_runs": 0,
                        "kb_entries": 0,
                        "tokens_used": 0,
                    }),
                )
                return str(result)

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to save session unexpectedly: {e}")
            return None

    async def _update_session(self, session: Session) -> bool:
        """Update session in database."""
        try:
            import asyncpg
            import json

            conn = await asyncpg.connect(self.config.database.url)
            try:
                await conn.execute(
                    """
                    UPDATE sessions
                    SET ended_at = $2,
                        duration_seconds = $3,
                        final_domain = $4,
                        open_threads = $5,
                        key_topics = $6,
                        research_notes = $7,
                        metrics = $8,
                        handoff_generated = $9,
                        handoff_summary = $10,
                        handoff_kb_path = $11
                    WHERE id = $1::uuid
                    """,
                    session.id,
                    session.ended_at,
                    session.duration_seconds,
                    session.final_domain,
                    json.dumps([t.to_dict() for t in session.open_threads]),
                    json.dumps(session.key_topics),
                    session.research_notes,
                    json.dumps({
                        "queries": session.queries,
                        "swarm_runs": session.swarm_runs,
                        "kb_entries": session.kb_entries,
                        "domains_visited": session.domains_visited,
                        "tokens_used": session.tokens_used,
                    }),
                    session.handoff_generated,
                    session.handoff_summary,
                    session.handoff_kb_path,
                )
                return True

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to update session: {e}")
            return False

    async def _get_previous_session(self) -> Session | None:
        """Get most recent completed session."""
        from ..storage.grid_state import check_database_availability

        # Check availability first (cached, logs once)
        if not await check_database_availability():
            return None

        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT id, profile_name, started_at, ended_at, duration_seconds,
                           initial_domain, final_domain, open_threads, key_topics,
                           research_notes, metrics, handoff_generated, handoff_summary,
                           handoff_kb_path
                    FROM sessions
                    WHERE profile_name = $1 AND ended_at IS NOT NULL
                    ORDER BY ended_at DESC
                    LIMIT 1
                    """,
                    self.profile,
                )

                if row is None:
                    return None

                metrics = row["metrics"] or {}

                return Session(
                    id=str(row["id"]),
                    profile_name=row["profile_name"],
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    duration_seconds=row["duration_seconds"],
                    initial_domain=row["initial_domain"],
                    final_domain=row["final_domain"],
                    key_topics=row["key_topics"] or [],
                    research_notes=row["research_notes"] or "",
                    queries=metrics.get("queries", 0),
                    swarm_runs=metrics.get("swarm_runs", 0),
                    kb_entries=metrics.get("kb_entries", 0),
                    domains_visited=metrics.get("domains_visited", []),
                    tokens_used=metrics.get("tokens_used", 0),
                    handoff_generated=row["handoff_generated"],
                    handoff_summary=row["handoff_summary"] or "",
                    handoff_kb_path=row["handoff_kb_path"],
                )

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to get previous session unexpectedly: {e}")
            return None

    async def _gather_session_metrics(self, session: Session) -> None:
        """Gather metrics for the current session from activity log."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                # Get activity summary for session duration
                rows = await conn.fetch(
                    """
                    SELECT event_type, COUNT(*) as count,
                           COALESCE(SUM((details->>'tokens')::int), 0) as tokens
                    FROM activity_events
                    WHERE created_at >= $1 AND created_at <= $2
                    GROUP BY event_type
                    """,
                    session.started_at,
                    session.ended_at or datetime.now(),
                )

                for row in rows:
                    if row["event_type"] == "query":
                        session.queries = row["count"]
                    elif row["event_type"] == "swarm_run":
                        session.swarm_runs = row["count"]
                        session.tokens_used += row["tokens"]
                    elif row["event_type"] == "kb_create":
                        session.kb_entries = row["count"]

                # Get domains visited
                domains = await conn.fetch(
                    """
                    SELECT DISTINCT domain
                    FROM activity_events
                    WHERE created_at >= $1 AND created_at <= $2
                    AND domain IS NOT NULL
                    """,
                    session.started_at,
                    session.ended_at or datetime.now(),
                )
                session.domains_visited = [r["domain"] for r in domains]

                # Extract key topics from queries
                topics = await conn.fetch(
                    """
                    SELECT details->>'query' as query
                    FROM activity_events
                    WHERE created_at >= $1 AND created_at <= $2
                    AND event_type = 'query'
                    AND details ? 'query'
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    session.started_at,
                    session.ended_at or datetime.now(),
                )
                session.key_topics = [r["query"] for r in topics if r["query"]][:5]

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to gather session metrics: {e}")

    async def _detect_open_threads(self, session: Session) -> list[ResearchThread]:
        """Detect open research threads from session activity.

        Uses query clustering to identify related queries that form a thread.
        """
        # Get existing active threads
        active = await self.get_active_threads()

        # If no queries this session, just return active threads
        if session.queries == 0:
            return active

        # Try to detect new threads from queries
        try:
            from gaius.client import get_grpc_client
            import json

            # Get recent queries
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT details->>'query' as query, created_at
                    FROM activity_events
                    WHERE created_at >= $1 AND created_at <= $2
                    AND event_type = 'query'
                    AND details ? 'query'
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    session.started_at,
                    session.ended_at or datetime.now(),
                )
            finally:
                await conn.close()

            queries = [r["query"] for r in rows if r["query"]]

            if len(queries) < 2:
                return active

            # Use LLM to detect thread patterns
            client = await get_grpc_client()

            prompt = f"""Analyze these queries from a research session and identify any coherent research threads.

Queries (newest first):
{chr(10).join(f'- {q}' for q in queries)}

Identify 0-2 research threads (related queries pursuing a specific topic).
For each thread, provide:
- topic: A concise title
- queries: Which queries belong to this thread
- current_focus: What aspect is being explored
- next_steps: Logical next investigation

Existing threads (don't duplicate): {', '.join(t.topic for t in active)}

Format as JSON array: [{{"topic": "...", "queries": [...], "current_focus": "...", "next_steps": "..."}}]
Return empty array [] if no clear threads detected."""

            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 400,
                    "temperature": 0.4,
                },
            )

            # Parse response
            content = result.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            detected = json.loads(content)

            # Create threads for newly detected ones
            new_threads = []
            existing_topics = {t.topic.lower() for t in active}

            for d in detected:
                topic = d.get("topic", "").strip()
                if topic and topic.lower() not in existing_topics:
                    thread = await self.create_thread(
                        topic=topic,
                        domain=session.final_domain or session.initial_domain,
                        initial_query=d.get("queries", [""])[0] if d.get("queries") else "",
                    )
                    thread.current_focus = d.get("current_focus", "")
                    thread.next_steps = d.get("next_steps", "")
                    thread.queries = [
                        {"query": q, "timestamp": datetime.now().isoformat()}
                        for q in d.get("queries", [])
                    ]
                    thread.query_count = len(thread.queries)

                    if thread.id is not None:
                        await self.update_thread(
                            thread.id,
                            current_focus=thread.current_focus,
                            next_steps=thread.next_steps,
                        )

                    new_threads.append(thread)
                    existing_topics.add(topic.lower())

            return active + new_threads

        except Exception as e:
            logger.warning(f"Thread detection failed: {e}")
            return active

    async def _generate_handoff_summary(self, session: Session) -> str:
        """Generate LLM summary for session handoff."""
        try:
            from gaius.client import get_grpc_client

            # Build context
            topics = ", ".join(session.key_topics) if session.key_topics else "various topics"
            domains = ", ".join(session.domains_visited) if session.domains_visited else "general"

            threads_desc = ""
            if session.open_threads:
                threads_desc = "\n".join(
                    f"- {t.topic}: {t.current_focus or 'exploring'}"
                    for t in session.open_threads[:3]
                )

            duration = ""
            if session.duration_seconds:
                mins = session.duration_seconds // 60
                duration = f"{mins} minute" if mins == 1 else f"{mins} minutes"

            prompt = f"""Generate a brief handoff summary for a research session.

Session details:
- Duration: {duration}
- Queries: {session.queries}
- KB entries created: {session.kb_entries}
- Domains: {domains}
- Key topics: {topics}

Open threads:
{threads_desc or 'None'}

Write 2-3 sentences summarizing what was explored and what's unfinished.
Be specific about the topics, not generic. Write in second person ("You were exploring...")."""

            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 150,
                    "temperature": 0.5,
                },
            )

            return result.get("content", "").strip()

        except Exception as e:
            logger.warning(f"Handoff generation failed: {e}")
            # Fallback to simple summary
            if session.key_topics:
                return f"Explored: {', '.join(session.key_topics[:3])}"
            return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_manager: SessionManager | None = None


def get_session_manager(profile: str = "default") -> SessionManager:
    """Get or create the session manager singleton."""
    global _manager
    if _manager is None or _manager.profile != profile:
        _manager = SessionManager(profile)
    return _manager


async def start_session(
    domain: str | None = None,
    profile: str = "default",
) -> tuple[Session, SessionHandoff]:
    """Convenience function to start a session."""
    manager = get_session_manager(profile)
    return await manager.start_session(domain)


async def end_session(
    domain: str | None = None,
    profile: str = "default",
) -> Session | None:
    """Convenience function to end the current session."""
    manager = get_session_manager(profile)
    return await manager.end_session(domain)
