"""Base daemon protocol for engine services.

All engine daemons (HealthObserver, Cognition, Evolution, etc.) implement
this protocol to enable centralized lifecycle management with FAIL-FAST
semantics.

Key Design Decisions:
- CRITICAL daemons: Engine enters DEGRADED mode (doesn't exit) so the ACP agent
  can investigate accumulated error states
- REQUIRED daemons: Engine starts but logs ERROR with Guru code
- OPTIONAL daemons: Engine starts with WARNING

All daemons MUST implement health_check() for continuous monitoring.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class DaemonCriticality(Enum):
    """How daemon failure affects engine startup."""

    CRITICAL = "critical"  # Engine enters DEGRADED mode
    REQUIRED = "required"  # Engine starts but ERROR logged
    OPTIONAL = "optional"  # Engine starts with WARNING


class EngineState(Enum):
    """Overall engine state based on daemon health."""

    STARTING = "starting"  # Startup in progress
    READY = "ready"  # All daemons healthy
    DEGRADED = "degraded"  # CRITICAL daemons failed but engine stays up for ACP
    STOPPING = "stopping"  # Shutdown in progress


@dataclass
class DaemonHealth:
    """Result of a daemon health check."""

    healthy: bool
    message: str
    guru_code: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "healthy": self.healthy,
            "message": self.message,
            "guru_code": self.guru_code,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


class DaemonStartupError(Exception):
    """Raised when a daemon fails to start.

    Includes actionable remediation hints following Gaius FAIL-FAST policy.
    """

    def __init__(self, daemon_name: str, message: str, guru_code: str):
        self.daemon_name = daemon_name
        self.guru_code = guru_code
        self.message = message
        super().__init__(
            f"Daemon '{daemon_name}' failed to start: {message}\n"
            f"  Guru: {guru_code}\n"
            f"  Try: /health fix {daemon_name}"
        )


class DaemonDependencyError(Exception):
    """Raised when a daemon's dependencies are not available."""

    def __init__(self, daemon_name: str, missing_deps: list[str]):
        self.daemon_name = daemon_name
        self.missing_deps = missing_deps
        super().__init__(
            f"Daemon '{daemon_name}' missing dependencies: {', '.join(missing_deps)}\n"
            f"  Guru: #DM.00000004.DEPFAIL\n"
            f"  Fix: Start required daemons first: {', '.join(missing_deps)}"
        )


class BaseDaemon(ABC):
    """Abstract base class for engine daemons.

    All daemons must implement:
    - name: Unique identifier for the daemon
    - criticality: How failure affects engine startup
    - is_running: Current running state
    - start(): Async startup with FAIL-FAST on error
    - stop(): Graceful shutdown
    - health_check(): Return DaemonHealth with status
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique daemon name (e.g., 'health_observer', 'cognition')."""
        ...

    @property
    @abstractmethod
    def criticality(self) -> DaemonCriticality:
        """How this daemon's failure affects engine state."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the daemon is currently running."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the daemon.

        MUST raise DaemonStartupError on failure - no silent degradation.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the daemon gracefully."""
        ...

    @abstractmethod
    async def health_check(self) -> DaemonHealth:
        """Check daemon health.

        Returns DaemonHealth with:
        - healthy: True if operational
        - message: Human-readable status
        - guru_code: Error code if unhealthy
        - details: Additional diagnostic info
        """
        ...

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.name!r}, "
            f"criticality={self.criticality.value}, "
            f"running={self.is_running})"
        )


# Guru Meditation Codes for daemon lifecycle
DAEMON_GURU_CODES = {
    # Generic daemon codes
    "DM.00000001.STARTFAIL": "Daemon failed to start",
    "DM.00000002.HEALTHFAIL": "Health check failed",
    "DM.00000003.TIMEOUT": "Startup timed out",
    "DM.00000004.DEPFAIL": "Dependency not available",
    # HealthObserver codes
    "HO.00000001.NOTRUNNING": "HealthObserver not running",
    "HO.00000002.STARTFAIL": "HealthObserver failed to start",
    "HO.00000003.STALLED": "HealthObserver poll stalled",
    # Cognition codes
    "COG.00000001.NOTRUNNING": "Cognition daemon not running",
    "COG.00000002.STARTFAIL": "Cognition failed to start",
    "COG.00000003.CRASHED": "Cognition task crashed",
    "COG.00000004.STALLED": "Cognition processing stalled",
    # Evolution codes
    "EV.00000001.STARTFAIL": "Evolution failed to start",
    "EV.00000002.NOTRUNNING": "Evolution daemon not running",
    # FlowScheduler codes
    "FS.00000001.STARTFAIL": "FlowScheduler failed to start",
    # Reconciliation codes
    "RC.00000001.NOTRUNNING": "Reconciliation not running",
    "RC.00000002.CRASHED": "Reconciliation task crashed",
    "RC.00000003.HIGHDRIFT": "High drift with low remediation success",
    "RC.00000004.NOOBSERVER": "HealthObserver not configured for escalation",
    "RC.00000005.ESCALATIONFAIL": "Failed to escalate to HealthObserver",
    # ACP (Agent Client Protocol) codes
    "ACP.00000011.NOCONFIG": "ACP config file not found",
    "ACP.00000012.NOREPOS": "No allowed repos in ACP config",
    "ACP.00000013.CONFIGFAIL": "ACP config validation failed",
    "ACP.00000014.GHISSUEFAIL": "GitHub issue creation failed",
    "ACP.00000015.CADENCEBLOCKED": "Cadence policy rate limited",
}
