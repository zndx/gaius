"""Daemon Registry - Centralized lifecycle management for engine daemons.

Provides:
- Dependency-ordered startup (topological sort)
- FAIL-FAST on CRITICAL daemon failures (engine enters DEGRADED mode)
- Continuous health monitoring
- Graceful shutdown in reverse order

Usage:
    registry = DaemonRegistry()
    registry.register(health_observer, after=[])
    registry.register(cognition, after=["health_observer"])

    results = await registry.start_all()
    # If CRITICAL daemon fails, engine enters DEGRADED state

Design Decisions:
- CRITICAL failures: Engine stays running in DEGRADED mode for ACP investigation
- No silent failures - all startup issues are logged and tracked
- Health checks return aggregate status for HealthObserver monitoring
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from .services.base_daemon import (
    BaseDaemon,
    DaemonCriticality,
    DaemonHealth,
    DaemonDependencyError,
    DaemonStartupError,
    EngineState,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class DaemonRegistration:
    """Registration entry for a daemon."""

    daemon: BaseDaemon
    dependencies: list[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    startup_error: Optional[str] = None
    last_health: Optional[DaemonHealth] = None


@dataclass
class StartupResult:
    """Result of starting a daemon."""

    daemon_name: str
    success: bool
    duration_ms: int
    error: Optional[str] = None
    guru_code: Optional[str] = None


@dataclass
class RegistryStatus:
    """Overall registry status."""

    engine_state: EngineState
    daemons: dict[str, dict[str, Any]]
    healthy_count: int
    unhealthy_count: int
    critical_failures: list[str]
    required_failures: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_state": self.engine_state.value,
            "daemons": self.daemons,
            "healthy_count": self.healthy_count,
            "unhealthy_count": self.unhealthy_count,
            "critical_failures": self.critical_failures,
            "required_failures": self.required_failures,
        }


class DaemonRegistry:
    """Central registry for daemon lifecycle management.

    Handles:
    - Registration with dependency ordering
    - Topological startup (dependencies first)
    - FAIL-FAST with DEGRADED mode for CRITICAL failures
    - Continuous health monitoring
    - Graceful shutdown in reverse order
    """

    def __init__(self, startup_timeout: float = 30.0):
        """Initialize registry.

        Args:
            startup_timeout: Max seconds to wait for each daemon to start
        """
        self._daemons: dict[str, DaemonRegistration] = {}
        self._startup_order: list[str] = []
        self._engine_state = EngineState.STARTING
        self._startup_timeout = startup_timeout
        self._critical_failures: list[str] = []
        self._required_failures: list[str] = []

    @property
    def engine_state(self) -> EngineState:
        """Current engine state based on daemon health."""
        return self._engine_state

    def register(
        self,
        daemon: BaseDaemon,
        after: Optional[list[str]] = None,
    ) -> None:
        """Register a daemon with optional dependencies.

        Args:
            daemon: The daemon instance
            after: List of daemon names that must start first
        """
        name = daemon.name
        deps = after or []

        # Validate dependencies exist
        for dep in deps:
            if dep not in self._daemons:
                logger.warning(
                    f"Daemon '{name}' depends on '{dep}' which is not yet registered"
                )

        self._daemons[name] = DaemonRegistration(daemon=daemon, dependencies=deps)
        logger.debug(f"Registered daemon: {name} (deps: {deps})")

        # Invalidate startup order - will recompute on start_all()
        self._startup_order = []

    def _compute_startup_order(self) -> list[str]:
        """Compute topological order for daemon startup."""
        # Build dependency graph
        in_degree: dict[str, int] = defaultdict(int)
        graph: dict[str, list[str]] = defaultdict(list)

        for name, reg in self._daemons.items():
            in_degree[name] = len(reg.dependencies)
            for dep in reg.dependencies:
                graph[dep].append(name)

        # Kahn's algorithm
        queue = [name for name, degree in in_degree.items() if degree == 0]
        order = []

        while queue:
            # Sort for deterministic order
            queue.sort()
            current = queue.pop(0)
            order.append(current)

            for dependent in graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._daemons):
            # Cycle detected
            missing = set(self._daemons.keys()) - set(order)
            raise ValueError(f"Circular dependency detected in daemons: {missing}")

        return order

    async def start_all(self) -> list[StartupResult]:
        """Start all registered daemons in dependency order.

        Returns:
            List of StartupResult for each daemon

        Note:
            - CRITICAL failures put engine in DEGRADED mode (doesn't exit)
            - REQUIRED failures log ERROR but engine continues
            - OPTIONAL failures log WARNING
        """
        self._engine_state = EngineState.STARTING
        self._critical_failures = []
        self._required_failures = []

        # Compute startup order
        self._startup_order = self._compute_startup_order()
        logger.info(f"Starting daemons in order: {self._startup_order}")

        results = []

        for name in self._startup_order:
            reg = self._daemons[name]
            daemon = reg.daemon

            # Check dependencies are running
            missing_deps = []
            for dep in reg.dependencies:
                dep_reg = self._daemons.get(dep)
                if not dep_reg or not dep_reg.daemon.is_running:
                    missing_deps.append(dep)

            if missing_deps:
                error = DaemonDependencyError(name, missing_deps)
                logger.error(str(error))
                reg.startup_error = str(error)
                results.append(
                    StartupResult(
                        daemon_name=name,
                        success=False,
                        duration_ms=0,
                        error=str(error),
                        guru_code="#DM.00000004.DEPFAIL",
                    )
                )
                self._handle_startup_failure(daemon, str(error))
                continue

            # Start daemon with timeout
            start_time = datetime.now()
            try:
                await asyncio.wait_for(
                    daemon.start(),
                    timeout=self._startup_timeout,
                )
                duration_ms = int(
                    (datetime.now() - start_time).total_seconds() * 1000
                )
                reg.started_at = datetime.now()
                results.append(
                    StartupResult(
                        daemon_name=name,
                        success=True,
                        duration_ms=duration_ms,
                    )
                )
                logger.info(
                    f"Daemon '{name}' started successfully in {duration_ms}ms"
                )

            except asyncio.TimeoutError:
                duration_ms = int(self._startup_timeout * 1000)
                error_msg = f"Startup timed out after {self._startup_timeout}s"
                reg.startup_error = error_msg
                results.append(
                    StartupResult(
                        daemon_name=name,
                        success=False,
                        duration_ms=duration_ms,
                        error=error_msg,
                        guru_code="#DM.00000003.TIMEOUT",
                    )
                )
                self._handle_startup_failure(daemon, error_msg)

            except DaemonStartupError as e:
                duration_ms = int(
                    (datetime.now() - start_time).total_seconds() * 1000
                )
                reg.startup_error = str(e)
                results.append(
                    StartupResult(
                        daemon_name=name,
                        success=False,
                        duration_ms=duration_ms,
                        error=str(e),
                        guru_code=e.guru_code,
                    )
                )
                self._handle_startup_failure(daemon, str(e))

            except Exception as e:
                duration_ms = int(
                    (datetime.now() - start_time).total_seconds() * 1000
                )
                error_msg = f"Unexpected error: {e}"
                reg.startup_error = error_msg
                results.append(
                    StartupResult(
                        daemon_name=name,
                        success=False,
                        duration_ms=duration_ms,
                        error=error_msg,
                        guru_code="#DM.00000001.STARTFAIL",
                    )
                )
                self._handle_startup_failure(daemon, error_msg)

        # Determine final engine state
        if self._critical_failures:
            self._engine_state = EngineState.DEGRADED
            logger.error(
                f"Engine entering DEGRADED mode - CRITICAL daemons failed: "
                f"{self._critical_failures}"
            )
        else:
            self._engine_state = EngineState.READY
            logger.info("All daemons started - engine READY")

        return results

    def _handle_startup_failure(self, daemon: BaseDaemon, error: str) -> None:
        """Handle daemon startup failure based on criticality."""
        name = daemon.name
        criticality = daemon.criticality

        if criticality == DaemonCriticality.CRITICAL:
            logger.error(
                f"CRITICAL daemon '{name}' failed to start: {error}\n"
                f"  Engine will enter DEGRADED mode for ACP investigation"
            )
            self._critical_failures.append(name)

        elif criticality == DaemonCriticality.REQUIRED:
            logger.error(
                f"REQUIRED daemon '{name}' failed to start: {error}\n"
                f"  Guru: #DM.00000001.STARTFAIL"
            )
            self._required_failures.append(name)

        else:  # OPTIONAL
            logger.warning(
                f"OPTIONAL daemon '{name}' failed to start: {error}\n"
                f"  Engine continuing without this daemon"
            )

    async def stop_all(self) -> None:
        """Stop all daemons in reverse startup order."""
        self._engine_state = EngineState.STOPPING
        logger.info("Stopping all daemons...")

        # Stop in reverse order
        for name in reversed(self._startup_order):
            reg = self._daemons.get(name)
            if not reg:
                continue

            daemon = reg.daemon
            if not daemon.is_running:
                continue

            try:
                await asyncio.wait_for(daemon.stop(), timeout=10.0)
                logger.info(f"Daemon '{name}' stopped")
            except asyncio.TimeoutError:
                logger.warning(f"Daemon '{name}' stop timed out")
            except Exception as e:
                logger.error(f"Error stopping daemon '{name}': {e}")

    async def check_all_health(self) -> dict[str, DaemonHealth]:
        """Check health of all registered daemons.

        Returns:
            Dict mapping daemon name to health status
        """
        results = {}

        for name, reg in self._daemons.items():
            try:
                health = await reg.daemon.health_check()
                reg.last_health = health
                results[name] = health
            except Exception as e:
                health = DaemonHealth(
                    healthy=False,
                    message=f"Health check failed: {e}",
                    guru_code="#DM.00000002.HEALTHFAIL",
                )
                reg.last_health = health
                results[name] = health

        return results

    def get_status(self) -> RegistryStatus:
        """Get overall registry status."""
        daemons = {}
        healthy_count = 0
        unhealthy_count = 0

        for name, reg in self._daemons.items():
            is_running = reg.daemon.is_running
            is_healthy = reg.last_health.healthy if reg.last_health else is_running

            if is_healthy:
                healthy_count += 1
            else:
                unhealthy_count += 1

            daemons[name] = {
                "criticality": reg.daemon.criticality.value,
                "running": is_running,
                "started_at": reg.started_at.isoformat() if reg.started_at else None,
                "startup_error": reg.startup_error,
                "last_health": reg.last_health.to_dict() if reg.last_health else None,
            }

        return RegistryStatus(
            engine_state=self._engine_state,
            daemons=daemons,
            healthy_count=healthy_count,
            unhealthy_count=unhealthy_count,
            critical_failures=self._critical_failures,
            required_failures=self._required_failures,
        )

    def get_daemon(self, name: str) -> Optional[BaseDaemon]:
        """Get a daemon by name."""
        reg = self._daemons.get(name)
        return reg.daemon if reg else None

    def list_daemons(self) -> list[str]:
        """List all registered daemon names."""
        return list(self._daemons.keys())
