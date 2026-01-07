"""Database fixtures for BDD testing.

Provides in-memory implementations of database-dependent components
for testing without requiring PostgreSQL.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import uuid


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Version Manager
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TestAgentConfig:
    """Simplified config for testing."""

    system_prompt: str
    model: str = "test-model"
    temperature: float = 0.7
    max_tokens: int = 2048

    def to_dict(self) -> dict:
        return {
            "system_prompt": self.system_prompt,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


@dataclass
class TestAgentVersion:
    """Simplified version for testing."""

    version_id: str
    agent_id: str
    config: TestAgentConfig
    created_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    metrics: dict = field(default_factory=dict)
    evaluation_count: int = 0
    avg_overall_score: float = 0.0
    change_notes: str = ""


class InMemoryVersionManager:
    """In-memory version manager for testing."""

    def __init__(self):
        self._versions: dict[str, TestAgentVersion] = {}
        self._active_versions: dict[str, str] = {}  # agent_id -> version_id

    async def save_version(
        self,
        agent_id: str,
        config: TestAgentConfig,
        metrics: dict | None = None,
        change_notes: str = "",
        set_active: bool = True,
    ) -> TestAgentVersion:
        """Save a new version."""
        version_id = f"{agent_id}-{uuid.uuid4().hex[:8]}"

        version = TestAgentVersion(
            version_id=version_id,
            agent_id=agent_id,
            config=config,
            is_active=set_active,
            metrics=metrics or {},
            change_notes=change_notes,
        )

        self._versions[version_id] = version

        if set_active:
            # Deactivate previous active version
            if agent_id in self._active_versions:
                old_id = self._active_versions[agent_id]
                if old_id in self._versions:
                    self._versions[old_id].is_active = False
            self._active_versions[agent_id] = version_id

        return version

    async def get_versions(
        self, agent_id: str, limit: int = 10
    ) -> list[TestAgentVersion]:
        """Get versions for an agent."""
        versions = [
            v for v in self._versions.values() if v.agent_id == agent_id
        ]
        versions.sort(key=lambda v: v.created_at, reverse=True)
        return versions[:limit]

    async def get_active_version(self, agent_id: str) -> TestAgentVersion | None:
        """Get active version for an agent."""
        version_id = self._active_versions.get(agent_id)
        if version_id:
            return self._versions.get(version_id)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Activity Tracker
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TestActivity:
    """Test activity record."""

    id: str
    event_type: str
    domain: str
    details: dict
    timestamp: datetime = field(default_factory=datetime.now)


class InMemoryActivityTracker:
    """In-memory activity tracker for testing."""

    def __init__(self):
        self._activities: list[TestActivity] = []

    async def log_activity(
        self,
        event_type: str,
        domain: str = "",
        details: dict | None = None,
    ) -> str:
        """Log an activity event."""
        activity_id = f"act-{uuid.uuid4().hex[:8]}"
        activity = TestActivity(
            id=activity_id,
            event_type=event_type,
            domain=domain,
            details=details or {},
        )
        self._activities.append(activity)
        return activity_id

    async def get_stats(self, days: int = 7) -> dict:
        """Get activity statistics."""
        return {
            "total_events": len(self._activities),
            "event_types": list(set(a.event_type for a in self._activities)),
            "days": days,
        }

    async def get_daily_summary(self, date: str = "") -> dict:
        """Get daily summary."""
        return {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "event_count": len(self._activities),
            "domains": list(set(a.domain for a in self._activities if a.domain)),
        }


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Session/Thread Manager
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TestSession:
    """Test session record."""

    session_id: str
    domain: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None


@dataclass
class TestResearchThread:
    """Test research thread."""

    thread_id: str
    topic: str
    domain: str
    initial_query: str
    goal: str
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "open"


class InMemorySessionManager:
    """In-memory session manager for testing."""

    def __init__(self):
        self._sessions: dict[str, TestSession] = {}
        self._threads: dict[str, TestResearchThread] = {}
        self._current_session_id: str | None = None

    async def start_session(self, domain: str = "") -> str:
        """Start a new session."""
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        session = TestSession(
            session_id=session_id,
            domain=domain,
        )
        self._sessions[session_id] = session
        self._current_session_id = session_id
        return session_id

    async def end_session(self, domain: str = "") -> dict:
        """End the current session."""
        if self._current_session_id:
            session = self._sessions.get(self._current_session_id)
            if session:
                session.ended_at = datetime.now()
            self._current_session_id = None
        return {"status": "ended"}

    async def get_session_handoff(self) -> dict:
        """Get handoff info from previous session."""
        return {
            "previous_session": bool(self._sessions),
            "open_threads": len([t for t in self._threads.values() if t.status == "open"]),
        }

    async def list_open_threads(self, limit: int = 10) -> list[dict]:
        """List open research threads."""
        threads = [t for t in self._threads.values() if t.status == "open"]
        threads.sort(key=lambda t: t.created_at, reverse=True)
        return [
            {
                "thread_id": t.thread_id,
                "topic": t.topic,
                "domain": t.domain,
                "status": t.status,
            }
            for t in threads[:limit]
        ]

    async def create_research_thread(
        self,
        topic: str,
        domain: str = "",
        initial_query: str = "",
        goal: str = "",
    ) -> str:
        """Create a new research thread."""
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"
        thread = TestResearchThread(
            thread_id=thread_id,
            topic=topic,
            domain=domain,
            initial_query=initial_query,
            goal=goal,
        )
        self._threads[thread_id] = thread
        return thread_id


# ─────────────────────────────────────────────────────────────────────────────
# Fixture Management
# ─────────────────────────────────────────────────────────────────────────────


_test_version_manager: InMemoryVersionManager | None = None
_test_activity_tracker: InMemoryActivityTracker | None = None
_test_session_manager: InMemorySessionManager | None = None


def get_test_version_manager() -> InMemoryVersionManager:
    """Get or create test version manager."""
    global _test_version_manager
    if _test_version_manager is None:
        _test_version_manager = InMemoryVersionManager()
    return _test_version_manager


def get_test_activity_tracker() -> InMemoryActivityTracker:
    """Get or create test activity tracker."""
    global _test_activity_tracker
    if _test_activity_tracker is None:
        _test_activity_tracker = InMemoryActivityTracker()
    return _test_activity_tracker


def get_test_session_manager() -> InMemorySessionManager:
    """Get or create test session manager."""
    global _test_session_manager
    if _test_session_manager is None:
        _test_session_manager = InMemorySessionManager()
    return _test_session_manager


def reset_test_fixtures():
    """Reset all test fixtures."""
    global _test_version_manager, _test_activity_tracker, _test_session_manager
    _test_version_manager = None
    _test_activity_tracker = None
    _test_session_manager = None


def install_test_fixtures():
    """Install test fixtures by patching module singletons."""
    import gaius.models.versioning as versioning
    import gaius.core.activity as activity
    import gaius.core.session as session

    # Patch the singleton getters
    # InMemoryVersionManager is a test double that implements the same interface
    # as VersionManager but isn't a formal subclass. This is intentional for test isolation.
    versioning._manager = get_test_version_manager()  # type: ignore[invalid-assignment]
    # Note: The actual managers need to be patched at module level
