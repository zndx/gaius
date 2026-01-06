"""HealthObserverService for autonomous health monitoring in gaius-engine.

Daemon that runs continuous health monitoring, FMEA-based incident detection,
and autonomous self-healing with ACP escalation for complex issues.

This service runs IN THE ENGINE (not client layer) ensuring:
- Health monitoring persists across MCP/TUI sessions
- Self-healing works when only gaius-engine is running via devenv up
- Single source of truth for health state
- Engine can perform autonomous healing even when no clients are connected

Implements BaseDaemon protocol with CRITICAL criticality - engine enters
DEGRADED mode if this daemon fails to start (not exit), allowing ACP-Claude
to investigate accumulated error states.

Architecture:
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      gaius-engine daemon                            │
    │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
    │  │HealthService │  │ Orchestrator │  │ HealthObserverService   │   │
    │  │ (metrics)    │──│ (endpoints)  │──│ (incidents, remediation)│   │
    │  └──────────────┘  └──────────────┘  └──────────┬──────────────┘   │
    │                                                  │                  │
    │                                         ┌────────▼────────┐         │
    │                                         │  ACP Client     │         │
    │                                         │  (Claude Code)  │         │
    │                                         └─────────────────┘         │
    └─────────────────────────────────────────────────────────────────────┘

BDD Alignment:
- Engine starts HealthObserverService during autonomous startup
- Observer polls health continuously (configurable interval)
- Incidents trigger FMEA-based RPN scoring
- Remediation follows tiered escalation (Tier 0 → Tier 1 → Tier 2 → Manual)
- ACP escalation spawns Claude Code for complex diagnosis
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import TYPE_CHECKING, Any, Callable, Awaitable
from uuid import UUID, uuid4

from .base_daemon import (
    BaseDaemon,
    DaemonCriticality,
    DaemonHealth,
    DaemonStartupError,
)
from ...health.healing_events import HealingEventRecorder, HealingEventType
from ...acp.security import get_github_repo_from_remote
from ..metrics import record_exception_caught, record_incident_change

if TYPE_CHECKING:
    from ..config import EngineConfig
    from ..daemon_registry import DaemonRegistry

logger = logging.getLogger(__name__)


def friendly_endpoint_name(name: str) -> str:
    """Convert internal endpoint name to user-friendly display name.

    Strips internal prefixes like 'cap_' that are implementation details.

    Args:
        name: Internal endpoint name (e.g., "cap_reasoning")

    Returns:
        User-friendly name (e.g., "reasoning")
    """
    if name.startswith("cap_"):
        return name[4:]  # Remove "cap_" prefix
    return name


@dataclass
class ObserverConfig:
    """Configuration for HealthObserverService.

    Attributes:
        enabled: Enable/disable daemon
        poll_interval: Seconds between health checks (default 30)
        burst_interval: Faster polling when healing in progress (default 5)
        backoff_interval: Slower polling after errors (default 120)
        escalate_to_acp: Enable ACP escalation for complex issues
        github_repo: Repository for issue tracking (required for full workflow)
        kb_root: Path to knowledge base root
        recovery_verification_time: Seconds of stable health before closing incident
        min_interval_between_restarts: Cadence control - seconds between restart attempts
        max_restarts_per_hour: Cadence control - max restarts per endpoint per hour
    """

    enabled: bool = True

    # Polling intervals
    poll_interval: float = 30.0
    burst_interval: float = 5.0
    backoff_interval: float = 120.0

    # ACP integration
    escalate_to_acp: bool = True
    # No timeout - let Claude Code run until natural completion (issue resolved or GH issue created)

    # GitHub integration - reads from git remote 'internal' by default
    # Supports full URL format for on-prem: github.example.com/org/repo
    github_repo: str = field(default_factory=lambda: get_github_repo_from_remote() or "")

    # KB and FMEA
    kb_root: str = "build/dev"

    # Recovery verification
    recovery_verification_time: float = 300.0  # 5 minutes

    # Cadence controls (prevent runaway remediation)
    min_interval_between_restarts: int = 300  # 5 minutes
    max_restarts_per_hour: int = 3
    max_issues_per_day: int = 3  # Max GitHub issues per 24 hours


@dataclass
class HealthIncident:
    """Tracks an active health incident through its lifecycle.

    Attributes:
        incident_id: Unique identifier
        fingerprint: Deduplication key (failure_mode_id:endpoint)
        endpoint: Affected endpoint
        failure_mode_id: FMEA failure mode
        rpn: Current RPN score
        current_tier: Escalation tier (0, 1, 2, or manual)
        sequence_id: Healing event sequence UUID
        created_at: When incident was detected
        last_check_at: When last health check ran
        attempts: Number of remediation attempts
        github_issue: Linked GitHub issue number
        status: active, healing, recovering, resolved
        rca_classification: RCA classification (operational/architectural)
        rca_highest_order: Highest abstraction order reached in RCA
        rca_issue: GitHub issue opened by RCA phase (if architectural)
    """

    incident_id: UUID
    fingerprint: str
    endpoint: str
    failure_mode_id: str
    rpn_score: int
    rpn_severity: int = 5
    rpn_occurrence: int = 5
    rpn_detection: int = 5
    current_tier: int = 0
    sequence_id: UUID | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_check_at: datetime = field(default_factory=datetime.now)
    attempts: int = 0
    github_issue: int | None = None
    status: str = "active"
    # RCA phase results
    rca_classification: str | None = None
    rca_highest_order: int | None = None
    rca_issue: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "incident_id": str(self.incident_id),
            "fingerprint": self.fingerprint,
            "endpoint": self.endpoint,
            "failure_mode_id": self.failure_mode_id,
            "rpn_score": self.rpn_score,
            "rpn_severity": self.rpn_severity,
            "rpn_occurrence": self.rpn_occurrence,
            "rpn_detection": self.rpn_detection,
            "current_tier": self.current_tier,
            "sequence_id": str(self.sequence_id) if self.sequence_id else None,
            "created_at": self.created_at.isoformat(),
            "last_check_at": self.last_check_at.isoformat(),
            "attempts": self.attempts,
            "github_issue": self.github_issue,
            "status": self.status,
            # RCA results
            "rca_classification": self.rca_classification,
            "rca_highest_order": self.rca_highest_order,
            "rca_issue": self.rca_issue,
            # Nested RPN for backward compatibility
            "rpn": {
                "rpn": self.rpn_score,
                "severity": self.rpn_severity,
                "occurrence": self.rpn_occurrence,
                "detection": self.rpn_detection,
            },
        }


class HealthObserverService(BaseDaemon):
    """Engine service for autonomous health monitoring and remediation.

    Implements BaseDaemon with CRITICAL criticality - if this daemon fails,
    engine enters DEGRADED mode to allow ACP-Claude investigation.

    Runs as part of gaius-engine daemon, ensuring health monitoring
    persists regardless of client connections.

    Features:
    - Continuous health observation via HealthChecker
    - FMEA-based RPN scoring for risk assessment
    - Tiered self-healing with escalation to Claude Code via ACP
    - Event-sourced healing audit trail
    - GitHub issue tracking for persistent incidents
    - Daemon registry integration for lifecycle monitoring

    The observer integrates with Claude Code through ACP, delegating:
    - Complex root cause analysis
    - Remediation planning
    - GitHub issue management
    - Code-level fixes when needed
    """

    # BaseDaemon protocol implementation
    @property
    def name(self) -> str:
        """Unique daemon name."""
        return "health_observer"

    @property
    def criticality(self) -> DaemonCriticality:
        """CRITICAL - engine enters DEGRADED if this fails."""
        return DaemonCriticality.CRITICAL

    def __init__(
        self,
        config: ObserverConfig | None = None,
        orchestrator_service: Any = None,
        health_service: Any = None,
    ):
        """Initialize the HealthObserverService.

        Args:
            config: Observer configuration (uses defaults if None)
            orchestrator_service: Reference to OrchestratorService for remediation
            health_service: Reference to HealthService for metrics
        """
        self.config = config or ObserverConfig()
        self._orchestrator = orchestrator_service
        self._health_service = health_service

        # ACP client for Claude Code escalation
        self._acp_client: Any = None
        self._acp_lock = asyncio.Lock()

        # State
        self._running = False
        self._task: asyncio.Task | None = None
        self._active_incidents: dict[str, HealthIncident] = {}
        self._recovery_start: dict[str, datetime] = {}

        # Metrics
        self._poll_count = 0
        self._incidents_created = 0
        self._incidents_resolved = 0
        self._acp_escalations = 0
        self._last_poll_at: datetime | None = None
        self._last_report: dict[str, Any] | None = None

        # GitHub issue cadence tracking
        self._issues_created_today = 0
        self._last_issue_date: date | None = None

        # Callbacks for external notification
        self._on_incident: list[Callable[[HealthIncident], Awaitable[None]]] = []
        self._on_resolution: list[Callable[[HealthIncident], Awaitable[None]]] = []

        # DaemonRegistry reference (set during engine startup)
        self._daemon_registry: "DaemonRegistry | None" = None

        # Database pool for internal health queries (set via set_db_pool)
        self._db_pool: Any = None

        # Event recorder for healing audit trail (all DB writes go through engine)
        self._event_recorder: HealingEventRecorder | None = None

        logger.info("HealthObserverService initialized")

    def set_services(
        self,
        orchestrator: Any = None,
        health: Any = None,
        db_pool: Any = None,
    ) -> None:
        """Set service references after initialization.

        Called by engine during startup phase.

        Args:
            orchestrator: OrchestratorService instance
            health: HealthService instance
            db_pool: asyncpg connection pool for direct DB queries
        """
        if orchestrator:
            self._orchestrator = orchestrator
        if health:
            self._health_service = health
        if db_pool:
            self._db_pool = db_pool
            # Initialize event recorder with pool for DB writes
            self._event_recorder = HealingEventRecorder(pool=db_pool)
            logger.info("HealingEventRecorder initialized for engine-side DB writes")

    async def _restore_incidents_from_db(self) -> int:
        """Restore active incidents from database on startup.

        Queries healing_events for sequences that started but never completed,
        reconstructing HealthIncident objects to resume monitoring.

        Also restores recovery timer state from RECOVERY_TIMER_STARTED events
        to properly handle incidents that were in "recovering" status at shutdown.

        Returns:
            Number of incidents restored
        """
        if not self._db_pool:
            logger.warning("Cannot restore incidents: no database pool")
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                # Find active sequences (started but not completed) from last 7 days
                # Also include recovery timer state to restore proper status
                rows = await conn.fetch(
                    """
                    WITH started AS (
                        SELECT sequence_id, endpoint, created_at, payload, failure_mode_id
                        FROM healing_events
                        WHERE event_type = 'sequence_started'
                        AND created_at > NOW() - INTERVAL '7 days'
                    ),
                    completed AS (
                        SELECT sequence_id
                        FROM healing_events
                        WHERE event_type = 'sequence_completed'
                    ),
                    latest_tier AS (
                        SELECT DISTINCT ON (sequence_id)
                            sequence_id, tier
                        FROM healing_events
                        WHERE event_type = 'tier_entered'
                        ORDER BY sequence_id, created_at DESC
                    ),
                    attempt_counts AS (
                        SELECT sequence_id, COUNT(*) as attempts
                        FROM healing_events
                        WHERE event_type IN ('attempt_started', 'attempt_failed', 'attempt_succeeded')
                        GROUP BY sequence_id
                    ),
                    -- Find the latest recovery timer state per sequence
                    latest_timer_event AS (
                        SELECT DISTINCT ON (sequence_id)
                            sequence_id, event_type, payload, created_at as timer_event_at
                        FROM healing_events
                        WHERE event_type IN ('recovery_timer_started', 'recovery_timer_cleared')
                        ORDER BY sequence_id, created_at DESC
                    )
                    SELECT
                        s.sequence_id, s.endpoint, s.created_at, s.payload, s.failure_mode_id,
                        COALESCE(lt.tier, 0) as current_tier,
                        COALESCE(ac.attempts, 0) as attempts,
                        lte.event_type as timer_event_type,
                        lte.payload as timer_payload,
                        lte.timer_event_at
                    FROM started s
                    LEFT JOIN completed c ON s.sequence_id = c.sequence_id
                    LEFT JOIN latest_tier lt ON s.sequence_id = lt.sequence_id
                    LEFT JOIN attempt_counts ac ON s.sequence_id = ac.sequence_id
                    LEFT JOIN latest_timer_event lte ON s.sequence_id = lte.sequence_id
                    WHERE c.sequence_id IS NULL
                    ORDER BY s.created_at DESC
                    """
                )

                restored = 0
                for row in rows:
                    try:
                        payload = row["payload"]
                        if isinstance(payload, str):
                            import json
                            payload = json.loads(payload)

                        # Construct fingerprint from failure_mode_id and endpoint
                        failure_mode_id = row["failure_mode_id"] or payload.get("issue_type", "UNKNOWN")
                        # Normalize endpoint name in fingerprint
                        endpoint = friendly_endpoint_name(row["endpoint"])
                        fingerprint = f"{failure_mode_id}:{endpoint}"

                        # Skip if we already have this incident (shouldn't happen on fresh start)
                        if fingerprint in self._active_incidents:
                            continue

                        # Determine status based on recovery timer state
                        status = "active"
                        timer_start = None

                        if row["timer_event_type"] == "recovery_timer_started":
                            # Timer is still active - incident was recovering
                            status = "recovering"
                            # Parse timer start time from payload
                            timer_payload = row["timer_payload"]
                            if isinstance(timer_payload, str):
                                timer_payload = json.loads(timer_payload)
                            timer_start_str = timer_payload.get("started_at")
                            if timer_start_str:
                                try:
                                    timer_start = datetime.fromisoformat(timer_start_str)
                                except (ValueError, TypeError):
                                    # Fall back to event timestamp
                                    timer_start = row["timer_event_at"]
                            else:
                                timer_start = row["timer_event_at"]

                        # Reconstruct the incident
                        incident = HealthIncident(
                            incident_id=uuid4(),  # New ID for this session
                            fingerprint=fingerprint,
                            endpoint=endpoint,
                            failure_mode_id=failure_mode_id,
                            rpn_score=payload.get("rpn_score", 125),
                            current_tier=row["current_tier"],
                            sequence_id=row["sequence_id"],
                            created_at=row["created_at"],
                            last_check_at=datetime.now(),
                            attempts=row["attempts"],
                            status=status,
                        )

                        self._active_incidents[fingerprint] = incident

                        # Restore recovery timer if incident was recovering
                        if timer_start:
                            self._recovery_start[fingerprint] = timer_start

                        # Record restored incident for Observe panel
                        record_incident_change(delta=1, status=status)

                        restored += 1

                        logger.info(
                            f"Restored incident {fingerprint} from DB "
                            f"(status={status}, tier={row['current_tier']}, "
                            f"attempts={row['attempts']}, created={row['created_at'].isoformat()})"
                        )

                    except Exception as e:
                        logger.warning(f"Failed to restore incident from row: {e}")
                        continue

                if restored > 0:
                    logger.info(f"Restored {restored} active incidents from database")
                    self._incidents_created += restored

                return restored

        except Exception as e:
            logger.error(f"Failed to restore incidents from database: {e}")
            return 0

    @property
    def running(self) -> bool:
        """Check if daemon is running."""
        return self._running

    @property
    def poll_count(self) -> int:
        """Total health check polls completed."""
        return self._poll_count

    @property
    def active_incidents(self) -> list[HealthIncident]:
        """List of currently active incidents."""
        return list(self._active_incidents.values())

    async def start(self) -> None:
        """Start the health observer daemon.

        Begins background health monitoring loop. Called by engine
        during autonomous startup. Restores any active incidents from
        the database to resume monitoring across restarts.
        """
        if self._running:
            logger.warning("HealthObserverService already running")
            return

        if not self.config.enabled:
            logger.info("HealthObserverService disabled by config")
            return

        # Restore active incidents from database before starting poll loop
        # This ensures we resume monitoring incidents that survived a restart
        restored = await self._restore_incidents_from_db()

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"HealthObserverService started (poll_interval={self.config.poll_interval}s, "
            f"acp_enabled={self.config.escalate_to_acp}, restored_incidents={restored})"
        )

    async def stop(self) -> None:
        """Stop the health observer daemon gracefully."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Close ACP client if open
        if self._acp_client is not None:
            try:
                await self._acp_client.close()
            except Exception as e:
                logger.warning(f"Error closing ACP client: {e}")
            self._acp_client = None

        logger.info("HealthObserverService stopped")

    async def _run_loop(self) -> None:
        """Main observer loop."""
        while self._running:
            try:
                # Run health check
                report = await self._run_health_check()
                self._last_report = report
                self._poll_count += 1
                self._last_poll_at = datetime.now()

                # Process failures
                await self._process_failures(report)

                # Check for recoveries
                await self._check_recoveries(report)

                # Escalate stale incidents (long-duration without progress)
                await self._escalate_stale_incidents(report)

                # Determine next poll interval
                if self._has_active_healing():
                    interval = self.config.burst_interval
                else:
                    interval = self.config.poll_interval

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health poll error: {e}")
                interval = self.config.backoff_interval

            await asyncio.sleep(interval)

    async def _run_health_check(self) -> dict[str, Any]:
        """Run internal health check using direct service access.

        Engine-side health monitoring that queries internal services directly,
        avoiding circular gRPC dependencies. Checks:
        - GPU health (via HealthService)
        - Endpoint health (via OrchestratorService)
        - Pipeline backlog (via direct DB query)

        The client-side HealthChecker has more checks (NiFi, Qdrant, etc.)
        but those create circular gRPC dependencies. This monitors the core
        issues that require autonomous remediation.

        Returns:
            Health report dict with check results
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "healthy": True,
            "checks": [],
        }

        # Check GPU health
        await self._check_gpu_health(report)

        # Check endpoint health
        await self._check_endpoint_health(report)

        # Check pipeline backlog (new - direct DB query)
        await self._check_pipeline_backlog(report)

        return report

    async def _check_gpu_health(self, report: dict[str, Any]) -> None:
        """Check GPU health via HealthService.

        Args:
            report: Health report to append results to
        """
        if not self._health_service:
            return

        try:
            health_data = self._health_service.get_health()
            report["gpus"] = health_data.get("gpus", [])

            for gpu in health_data.get("gpus", []):
                if not gpu.get("is_healthy", True):
                    report["healthy"] = False
                    report["checks"].append({
                        "name": f"gpu_{gpu['gpu_id']}_health",
                        "status": "FAIL",
                        "message": f"GPU {gpu['gpu_id']} unhealthy",
                        "details": gpu,
                        "heuristic_id": "GPU_001",
                    })
        except Exception as e:
            logger.debug(f"GPU health check failed: {e}")

    async def _check_endpoint_health(self, report: dict[str, Any]) -> None:
        """Check endpoint health via OrchestratorService.

        Args:
            report: Health report to append results to
        """
        if not self._orchestrator:
            return

        try:
            status = self._orchestrator.get_status()
            endpoints = status.get("endpoints", {})
            report["endpoints"] = endpoints

            for alias, ep_info in endpoints.items():
                ep_status = ep_info.get("status", "unknown")
                # Accept both legacy and protobuf enum formats
                unhealthy_statuses = {"unhealthy", "error", "failed", "PROCESS_STATUS_UNHEALTHY", "PROCESS_STATUS_FAILED"}
                if ep_status in unhealthy_statuses:
                    report["healthy"] = False
                    report["checks"].append({
                        "name": f"endpoint_{alias}",
                        "status": "FAIL",
                        "message": f"Endpoint {alias} is {ep_status}",
                        "details": {"endpoint": alias, **ep_info},
                        "heuristic_id": "VLLM_001",
                    })
        except Exception as e:
            logger.debug(f"Endpoint health check failed: {e}")

    async def _check_pipeline_backlog(self, report: dict[str, Any]) -> None:
        """Check pipeline backlog via direct database query.

        Queries v_pipeline_status view to detect critical backlogs that
        indicate stalled LLM triage processing.

        Args:
            report: Health report to append results to
        """
        if not self._db_pool:
            logger.debug("No DB pool available for pipeline check")
            return

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT stage, pending, completed_1h, backlog_warn, backlog_critical
                    FROM v_pipeline_status
                    WHERE pending > backlog_critical
                """)

                for row in rows:
                    stage = row["stage"]
                    pending = row["pending"]
                    critical = row["backlog_critical"]

                    report["healthy"] = False
                    report["checks"].append({
                        "name": f"pipeline_{stage}",
                        "status": "FAIL",
                        "message": f"Pipeline backlog critical: {stage}: {pending} pending (threshold: {critical})",
                        "details": {
                            "stage": stage,
                            "pending": pending,
                            "completed_1h": row["completed_1h"],
                            "backlog_critical": critical,
                            "endpoint": f"pipeline_{stage}",  # For incident fingerprinting
                        },
                        "heuristic_id": "PIPELINE_001",
                        "suggestion": "Run: /health fix pipeline",
                    })

                # Also check for warnings (less severe)
                warn_rows = await conn.fetch("""
                    SELECT stage, pending, backlog_warn, backlog_critical
                    FROM v_pipeline_status
                    WHERE pending > backlog_warn AND pending <= backlog_critical
                """)

                for row in warn_rows:
                    stage = row["stage"]
                    pending = row["pending"]
                    report["checks"].append({
                        "name": f"pipeline_{stage}",
                        "status": "WARN",
                        "message": f"Pipeline backlog warning: {stage}: {pending} pending",
                        "details": {
                            "stage": stage,
                            "pending": pending,
                            "backlog_warn": row["backlog_warn"],
                        },
                        "heuristic_id": "PIPELINE_001",
                    })

        except Exception as e:
            logger.warning(f"Pipeline backlog check failed: {e}")

    async def _process_failures(self, report: dict[str, Any]) -> None:
        """Process failed health checks.

        For each failure:
        1. Calculate fingerprint for deduplication
        2. Check if incident exists
        3. Create or update incident
        4. Calculate RPN
        5. Attempt remediation based on tier

        Args:
            report: Health report with check results
        """
        for check in report.get("checks", []):
            if check.get("status") != "FAIL":
                continue

            # Generate fingerprint for deduplication
            fingerprint = self._generate_fingerprint(check)

            # Check existing incident
            if fingerprint in self._active_incidents:
                incident = self._active_incidents[fingerprint]
                incident.last_check_at = datetime.now()

                # If recovering, reset to active
                if incident.status == "recovering":
                    incident.status = "active"
                    self._recovery_start.pop(fingerprint, None)
                    logger.info(f"Incident {fingerprint} regressed, reset to active")
                    continue

                # Skip if already being healed
                if incident.status == "healing":
                    continue

                # For tier >= 3 (manual), create GitHub issue if not yet created
                if incident.current_tier >= 3 and not incident.github_issue:
                    await self._create_github_issue(incident)
                    incident.status = "manual_required"
                    continue

                # For active incidents at tier 2 with no recent remediation, retry ACP
                # This handles incidents restored from DB that need continued escalation
                if incident.status == "active" and incident.current_tier == 2:
                    # Check if ACP escalation should be retried (at most once per poll)
                    # We use a simple heuristic: if status is active, attempt remediation
                    await self._attempt_remediation(incident)

                continue

            # Create new incident
            incident = await self._create_incident(check)
            if incident:
                self._active_incidents[fingerprint] = incident
                self._incidents_created += 1

                # Record incident for Observe panel
                record_incident_change(delta=1, status="active")

                # Notify callbacks
                for callback in self._on_incident:
                    try:
                        await callback(incident)
                    except Exception as e:
                        logger.warning(f"Incident callback error: {e}")

                # Attempt remediation
                await self._attempt_remediation(incident)

    async def _create_incident(self, check: dict[str, Any]) -> HealthIncident | None:
        """Create a new health incident from a failed check.

        Args:
            check: Failed health check dict

        Returns:
            HealthIncident if created, None on error
        """
        try:
            details = check.get("details", {})
            endpoint = details.get("endpoint", check["name"].lower().replace(" ", "_"))
            failure_mode_id = check.get("heuristic_id") or f"UNKNOWN_{check['name'][:10].upper()}"

            # Calculate RPN using FMEA
            rpn_result = await self._calculate_rpn(failure_mode_id, details)

            fingerprint = f"{failure_mode_id}:{endpoint}"

            # Start healing sequence for event tracking
            sequence_id = None
            if self._event_recorder:
                sequence_id = await self._event_recorder.start_sequence(
                    endpoint=endpoint,
                    issue_type=failure_mode_id,
                    check_name=check.get("name"),
                    severity="critical" if rpn_result.get("tier", 0) >= 2 else "warning",
                    rpn_score=rpn_result.get("rpn", 125),
                    context=details,
                    failure_mode_id=failure_mode_id,
                )

            incident = HealthIncident(
                incident_id=uuid4(),
                fingerprint=fingerprint,
                endpoint=endpoint,
                failure_mode_id=failure_mode_id,
                rpn_score=rpn_result.get("rpn", 125),
                rpn_severity=rpn_result.get("severity", 5),
                rpn_occurrence=rpn_result.get("occurrence", 5),
                rpn_detection=rpn_result.get("detection", 5),
                current_tier=rpn_result.get("tier", 0),
                sequence_id=sequence_id,
            )

            logger.info(
                f"Created incident {incident.incident_id}: {fingerprint} "
                f"(RPN={incident.rpn_score}, tier={incident.current_tier})"
            )
            return incident

        except Exception as e:
            logger.error(f"Failed to create incident from check {check.get('name')}: {e}")
            return None

    async def _calculate_rpn(
        self,
        failure_mode_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate RPN score for a failure.

        Args:
            failure_mode_id: FMEA failure mode identifier
            context: Health check details for context

        Returns:
            Dict with rpn, severity, occurrence, detection, tier
        """
        try:
            from ...health.fmea.engine import FMEAEngine

            engine = FMEAEngine(kb_root=self.config.kb_root)
            rpn = engine.calculate_rpn(
                failure_mode_id=failure_mode_id,
                context=context,
            )
            return {
                "rpn": rpn.rpn,
                "severity": rpn.severity,
                "occurrence": rpn.occurrence,
                "detection": rpn.detection,
                "tier": rpn.tier.value,
            }
        except Exception as e:
            logger.warning(f"FMEA calculation failed, using defaults: {e}")
            return {
                "rpn": 125,
                "severity": 5,
                "occurrence": 5,
                "detection": 5,
                "tier": 0,
            }

    async def _attempt_remediation(self, incident: HealthIncident) -> None:
        """Attempt to remediate an incident based on its tier.

        Tier 0: Auto-remediate immediately (restart endpoint)
        Tier 1: Auto-remediate with local agent validation
        Tier 2: Escalate to Claude Code via ACP for approval
        Manual: Create GitHub issue and notify

        After successful remediation, runs RCA phase to analyze root cause
        and determine if the issue is operational (transient) or architectural
        (requiring code changes).

        Args:
            incident: The incident to remediate
        """
        import time
        start_time = time.monotonic()

        incident.attempts += 1
        incident.status = "healing"

        tier = incident.current_tier
        remediation_result = {"action": None, "outcome": None}

        logger.info(
            f"Attempting remediation for {incident.fingerprint} "
            f"(attempt {incident.attempts}, tier {tier})"
        )

        # Record tier entry if escalating
        if self._event_recorder and incident.sequence_id and incident.attempts > 1:
            await self._event_recorder.record_tier_entered(
                sequence_id=incident.sequence_id,
                endpoint=incident.endpoint,
                to_tier=tier,
                from_tier=tier - 1 if tier > 0 else None,
                reason="escalation" if tier > 0 else "initial",
            )

        try:
            # Record attempt start
            action_map = {0: "restart", 1: "restart_with_validation", 2: "acp_escalation"}
            action = action_map.get(tier, "manual")

            if self._event_recorder and incident.sequence_id:
                await self._event_recorder.record_attempt_started(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    tier=tier,
                    attempt_num=incident.attempts,
                    action=action,
                )

            if tier == 0:
                success = await self._tier0_remediate(incident)
                remediation_result["action"] = "restart"
            elif tier == 1:
                success = await self._tier1_remediate(incident)
                remediation_result["action"] = "restart_with_validation"
            elif tier == 2:
                success = await self._tier2_remediate_acp(incident)
                remediation_result["action"] = "acp_escalation"
            else:  # tier >= 3 = MANUAL
                await self._create_github_issue(incident)
                incident.status = "manual_required"
                return

            duration_ms = int((time.monotonic() - start_time) * 1000)
            remediation_result["outcome"] = "success" if success else "failure"
            remediation_result["duration_ms"] = duration_ms

            if success:
                # Record success
                if self._event_recorder and incident.sequence_id:
                    await self._event_recorder.record_attempt_succeeded(
                        sequence_id=incident.sequence_id,
                        endpoint=incident.endpoint,
                        tier=tier,
                        attempt_num=incident.attempts,
                        action=action,
                        duration_ms=duration_ms,
                    )

                # Run RCA phase after successful remediation
                rca_start = time.monotonic()
                rca_result = await self._run_rca_phase(incident, remediation_result)
                rca_duration_ms = int((time.monotonic() - rca_start) * 1000)

                # Store RCA classification on incident and record to DB
                if rca_result:
                    incident.rca_classification = rca_result.get("classification")
                    incident.rca_highest_order = rca_result.get("highest_order_reached")

                    # Record RCA completion
                    if self._event_recorder and incident.sequence_id:
                        await self._event_recorder.record_rca_completed(
                            sequence_id=incident.sequence_id,
                            endpoint=incident.endpoint,
                            classification=incident.rca_classification or "operational",
                            highest_order=incident.rca_highest_order or 0,
                            observations_count=len(rca_result.get("observations", [])),
                            constraint_violations_count=len(rca_result.get("constraint_violations", [])),
                            github_issue_needed=rca_result.get("github_issue_needed", False),
                            duration_ms=rca_duration_ms,
                        )

                        # Record constraint violations
                        for violation in rca_result.get("constraint_violations", []):
                            await self._event_recorder.record_rca_constraint_violation(
                                sequence_id=incident.sequence_id,
                                endpoint=incident.endpoint,
                                constraint_id=violation.get("constraint_id", "UNKNOWN"),
                                constraint_name=violation.get("name", ""),
                                location=violation.get("location"),
                                evidence=violation.get("evidence"),
                                failure_mode_id=incident.failure_mode_id,
                            )

                    # Open GitHub issue if architectural
                    if rca_result.get("github_issue_needed"):
                        issue_number = await self._create_rca_github_issue(
                            incident, rca_result
                        )
                        incident.rca_issue = issue_number

                incident.status = "recovering"
                self._recovery_start[incident.fingerprint] = datetime.now()
                logger.info(
                    f"Remediation succeeded for {incident.fingerprint} "
                    f"(RCA: {incident.rca_classification})"
                )
            else:
                # Record failure
                if self._event_recorder and incident.sequence_id:
                    await self._event_recorder.record_attempt_failed(
                        sequence_id=incident.sequence_id,
                        endpoint=incident.endpoint,
                        tier=tier,
                        attempt_num=incident.attempts,
                        action=action,
                        duration_ms=duration_ms,
                        reason="remediation_failed",
                    )

                # Escalate to next tier
                incident.current_tier = min(incident.current_tier + 1, 3)
                logger.info(
                    f"Escalating {incident.fingerprint} to tier {incident.current_tier}"
                )
                # Retry with new tier
                await self._attempt_remediation(incident)

        except Exception as e:
            logger.error(f"Remediation error for {incident.fingerprint}: {e}")
            # Record OTel metric for observability
            record_exception_caught(
                component="health",
                operation="remediation",
                exception_type=type(e).__name__,
                failure_mode_id=incident.failure_mode_id,
                guru_code="#HO.00000001.REMFAIL",
            )
            # Record failure
            if self._event_recorder and incident.sequence_id:
                await self._event_recorder.record_attempt_failed(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    tier=tier,
                    attempt_num=incident.attempts,
                    action=action_map.get(tier, "unknown"),
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                    reason=str(e),
                )

    async def _tier0_remediate(self, incident: HealthIncident) -> bool:
        """Tier 0 procedural remediation.

        Attempts simple restart via OrchestratorService.

        Args:
            incident: The incident to remediate

        Returns:
            True if remediation succeeded
        """
        if not self._orchestrator:
            logger.warning("No orchestrator available for tier 0 remediation")
            return False

        try:
            # Check if this is an endpoint issue
            if incident.failure_mode_id.startswith("VLLM"):
                await self._orchestrator.restart_endpoint(incident.endpoint)
                return True
            elif incident.failure_mode_id.startswith("GPU"):
                # For GPU issues, we can't directly remediate
                # but we can try restarting affected endpoints
                status = self._orchestrator.get_status()
                endpoints = status.get("endpoints", {})
                for alias, info in endpoints.items():
                    gpu_ids = info.get("gpu_ids", [])
                    # Extract GPU ID from incident endpoint (e.g., "gpu_0" -> 0)
                    incident_gpu = int(incident.endpoint.split("_")[-1])
                    if incident_gpu in gpu_ids:
                        await self._orchestrator.restart_endpoint(alias)
                return True
            elif incident.failure_mode_id.startswith("PIPELINE"):
                # Pipeline backlogs are capacity issues, not restartable services
                # Tier 0 cannot resolve - escalate to ACP for analysis
                logger.info(
                    f"Pipeline backlog ({incident.endpoint}) requires capacity analysis, "
                    "escalating to ACP"
                )
                return False
            else:
                logger.warning(
                    f"Unknown failure mode {incident.failure_mode_id}, cannot remediate"
                )
                return False

        except Exception as e:
            logger.error(f"Tier 0 remediation failed: {e}")
            return False

    async def _tier1_remediate(self, incident: HealthIncident) -> bool:
        """Tier 1 local agent remediation.

        Uses local LLM for validation before applying fix.
        For now, delegates to tier 0 logic.

        Args:
            incident: The incident to remediate

        Returns:
            True if remediation succeeded
        """
        # Tier 1 uses same logic as tier 0 but could add local LLM validation
        return await self._tier0_remediate(incident)

    async def _tier2_remediate_acp(self, incident: HealthIncident) -> bool:
        """Tier 2 ACP escalation to Claude Code.

        Delegates complex diagnosis and remediation to Claude Code
        via the Agent Client Protocol.

        Args:
            incident: The incident to remediate

        Returns:
            True if remediation succeeded
        """
        if not self.config.escalate_to_acp:
            return False

        try:
            async with self._acp_lock:
                # Lazy-load ACP client
                if self._acp_client is None:
                    from ...acp import GaiusACPClient, ACPConfig

                    self._acp_client = GaiusACPClient(
                        ACPConfig(
                            # No timeout - let Claude Code run until natural completion
                            auto_approve_terminal=True,  # Allow Bash for health investigation
                        )
                    )
                    await self._acp_client.connect()

            self._acp_escalations += 1

            # Build prompt for Claude Code
            prompt = self._build_acp_prompt(incident)

            # Send to Claude Code - no timeout, let it run until natural completion
            response = await self._acp_client.prompt(
                message=prompt,
                context={
                    "incident": incident.to_dict(),
                    "last_report": self._last_report,
                },
            )

            # Parse response for success indicator
            return self._parse_acp_response(response)

        except Exception as e:
            logger.error(f"ACP escalation failed: {e}")
            # Record OTel metric for observability
            record_exception_caught(
                component="acp",
                operation="escalation",
                exception_type=type(e).__name__,
                failure_mode_id=incident.failure_mode_id,
                guru_code="#ACP.00000005.ESCFAIL",
            )
            return False

    def _build_acp_prompt(self, incident: HealthIncident) -> str:
        """Build prompt for Claude Code via ACP.

        Args:
            incident: The incident to diagnose

        Returns:
            Prompt string for Claude Code
        """
        display_endpoint = friendly_endpoint_name(incident.endpoint)
        return f"""## Health Incident Requiring Diagnosis

**Fingerprint**: `{incident.fingerprint}`
**Endpoint**: {display_endpoint}
**Failure Mode**: {incident.failure_mode_id}
**RPN Score**: {incident.rpn_score} (S:{incident.rpn_severity} x O:{incident.rpn_occurrence} x D:{incident.rpn_detection})
**Escalation Tier**: {incident.current_tier}
**Attempts**: {incident.attempts}

### Instructions

1. Use the Gaius MCP tools to investigate this health issue:
   - `health_check` - Run diagnostics
   - `orchestrator_status` - Check GPU/endpoint status
   - `orchestrator_logs {display_endpoint}` - View endpoint logs

2. Diagnose the root cause

3. If safe to remediate:
   - Use `orchestrator_restart {display_endpoint}` for endpoint issues
   - Use appropriate fix commands for other issues

4. Report your findings and whether remediation succeeded

Begin your investigation now."""

    def _parse_acp_response(self, response: str) -> bool:
        """Parse ACP response for success indicator.

        Args:
            response: Claude Code response text

        Returns:
            True if remediation appears successful
        """
        response_lower = response.lower()
        success_indicators = [
            "remediation succeeded",
            "successfully restarted",
            "issue resolved",
            "endpoint is now healthy",
            "fix applied successfully",
        ]
        failure_indicators = [
            "remediation failed",
            "could not fix",
            "manual intervention required",
            "unable to resolve",
        ]

        for indicator in success_indicators:
            if indicator in response_lower:
                return True

        for indicator in failure_indicators:
            if indicator in response_lower:
                return False

        # Default to success if no clear indicators
        return True

    async def _run_rca_phase(
        self,
        incident: HealthIncident,
        remediation_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run Root Cause Analysis phase after successful remediation.

        Uses the abstraction ladder framework to analyze the root cause
        and determine if this is an operational (transient) or architectural
        (systemic) issue requiring code changes.

        Args:
            incident: The incident that was remediated
            remediation_result: Result of the remediation attempt

        Returns:
            RCA result dict with classification, observations, etc.
            None if RCA was skipped or failed
        """
        # Skip RCA for trivial first-occurrence tier-0 incidents
        if incident.current_tier == 0 and incident.attempts == 1:
            logger.debug(
                f"Skipping RCA for trivial incident {incident.fingerprint} "
                "(tier 0, first attempt)"
            )
            return {
                "classification": "operational",
                "observations": [],
                "highest_order_reached": 0,
                "constraint_violations": [],
                "github_issue_needed": False,
            }

        if not self.config.escalate_to_acp:
            logger.debug("ACP escalation disabled, skipping RCA phase")
            return None

        try:
            from ...acp import (
                WorkflowMode,
                build_system_prompt,
                build_rca_prompt,
            )

            async with self._acp_lock:
                # Lazy-load ACP client
                if self._acp_client is None:
                    from ...acp import GaiusACPClient, ACPConfig

                    self._acp_client = GaiusACPClient(
                        ACPConfig(
                            auto_approve_terminal=True,
                        )
                    )
                    await self._acp_client.connect()

            # Get incident history (previous occurrences of same fingerprint)
            incident_history = await self._get_incident_history(incident.fingerprint)

            # Get scheduler context
            scheduler_context = await self._get_scheduler_context()

            # Build RCA prompt
            rca_prompt = build_rca_prompt(
                incident.to_dict(),
                remediation_result,
                scheduler_context,
                incident_history,
            )

            # Build system prompt with RCA mode
            system_prompt = build_system_prompt(
                WorkflowMode.RCA,
                github_repo=self.config.github_repo,
            )

            logger.info(
                f"Running RCA phase for {incident.fingerprint} via ACP"
            )

            # Combine system prompt and RCA prompt into a single message
            # The ACP client's prompt() method doesn't accept system_prompt separately
            full_message = f"{system_prompt}\n\n---\n\n{rca_prompt}"

            # Send to Claude Code
            response = await self._acp_client.prompt(
                message=full_message,
                context={
                    "incident": incident.to_dict(),
                    "remediation_result": remediation_result,
                },
            )

            # Parse RCA response
            return self._parse_rca_response(response)

        except Exception as e:
            logger.error(f"RCA phase failed for {incident.fingerprint}: {e}")
            # Record OTel metric for observability
            record_exception_caught(
                component="health",
                operation="rca_analysis",
                exception_type=type(e).__name__,
                failure_mode_id=incident.failure_mode_id,
                guru_code="#HO.00000002.RCAFAIL",
            )
            return None

    async def _get_incident_history(
        self,
        fingerprint: str,
    ) -> list[dict[str, Any]]:
        """Get history of previous occurrences of this fingerprint.

        Args:
            fingerprint: Incident fingerprint to search for

        Returns:
            List of previous incident dicts
        """
        # For now, return empty - would query healing_events table
        # This could be enhanced to query the database for historical incidents
        return []

    async def _get_scheduler_context(self) -> dict[str, Any] | None:
        """Get current scheduler state for RCA context.

        Returns:
            Scheduler context dict or None
        """
        if not self._orchestrator:
            return None

        try:
            status = self._orchestrator.get_status()
            endpoints = status.get("endpoints", {})

            return {
                "active_endpoints": list(endpoints.keys()),
                "gpu_assignments": {
                    alias: info.get("gpu_ids", [])
                    for alias, info in endpoints.items()
                },
                "queue_depth": status.get("queue_depth", 0),
            }
        except Exception as e:
            logger.debug(f"Failed to get scheduler context: {e}")
            return None

    def _parse_rca_response(self, response: str) -> dict[str, Any] | None:
        """Parse Claude Code's RCA response.

        Extracts the JSON block from the response containing classification,
        observations, constraint violations, and proposed fix.

        Args:
            response: Claude Code response text

        Returns:
            Parsed RCA result dict or None on parse failure
        """
        import json
        import re

        try:
            # Find JSON block in response
            # Look for ```json ... ``` or { ... } pattern
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON object
                json_match = re.search(r"\{[^{}]*\"classification\"[^{}]*\}", response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    logger.warning("No JSON found in RCA response")
                    return None

            result = json.loads(json_str)

            # Validate required fields
            if "classification" not in result:
                logger.warning("RCA response missing classification")
                return None

            # Normalize classification
            classification = result.get("classification", "").lower()
            if classification not in ("operational", "architectural"):
                classification = "operational"  # Default to operational

            return {
                "classification": classification,
                "observations": result.get("observations", []),
                "highest_order_reached": result.get("highest_order_reached", 0),
                "constraint_violations": result.get("constraint_violations", []),
                "github_issue_needed": result.get("github_issue_needed", False),
                "fix_location": result.get("fix_location"),
                "proposed_fix": result.get("proposed_fix"),
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse RCA JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error parsing RCA response: {e}")
            return None

    async def _create_rca_github_issue(
        self,
        incident: HealthIncident,
        rca_result: dict[str, Any],
    ) -> int | None:
        """Create GitHub issue for architectural RCA findings.

        Args:
            incident: The incident that was analyzed
            rca_result: RCA result with observations and proposed fix

        Returns:
            Issue number if created, None otherwise
        """
        import asyncio
        import subprocess

        if not self.config.github_repo:
            logger.info("GitHub integration not configured, skipping RCA issue creation")
            return None

        if not self._can_create_issue():
            logger.warning(
                f"Cadence limit reached, skipping RCA issue for {incident.fingerprint}"
            )
            return None

        try:
            from ...acp import (
                format_rca_observations,
                format_rca_constraint_violations,
                RCA_ISSUE_BODY_TEMPLATE,
            )
            from ...acp.security import (
                sanitize_issue_content,
                validate_issue_title,
                load_security_config,
            )

            # Validate repo is allowed
            security_config = load_security_config()
            if self.config.github_repo not in security_config.allowed_repos:
                logger.error(
                    f"Repository {self.config.github_repo} not in ACP allowlist"
                )
                return None

            # Build issue title
            highest_order = rca_result.get("highest_order_reached", 0)
            order_names = ["SYMPTOM", "IMMEDIATE", "STRUCTURAL", "INVARIANT", "DESIGN"]
            order_name = order_names[highest_order] if highest_order < len(order_names) else f"ORDER_{highest_order}"

            display_endpoint = friendly_endpoint_name(incident.endpoint)
            title = f"[RCA] {incident.failure_mode_id}: {order_name} analysis for {display_endpoint}"
            title = validate_issue_title(title)

            # Format observations and violations
            observations_text = format_rca_observations(
                rca_result.get("observations", [])
            )
            violations_text = format_rca_constraint_violations(
                rca_result.get("constraint_violations", [])
            )

            # Build issue body
            body = RCA_ISSUE_BODY_TEMPLATE.format(
                fingerprint=incident.fingerprint,
                highest_order=highest_order,
                highest_order_name=order_name,
                confidence=rca_result.get("avg_confidence", 0.5),
                observations_by_order=observations_text,
                constraint_violations=violations_text,
                fix_location=rca_result.get("fix_location") or "_Not identified_",
                proposed_fix=rca_result.get("proposed_fix") or "_No specific fix proposed_",
                failure_mode_id=incident.failure_mode_id,
            )
            body = sanitize_issue_content(body)

            # Create issue via gh CLI
            cmd = [
                "gh", "issue", "create",
                "--repo", self.config.github_repo,
                "--title", title,
                "--body", body,
                "--label", "rca,architectural,health-fix",
            ]

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )

            if result.returncode == 0:
                issue_url = result.stdout.strip()
                issue_number = int(issue_url.split("/")[-1]) if "/" in issue_url else None
                self._issues_created_today += 1

                # Record GitHub issue creation to DB
                if self._event_recorder and incident.sequence_id and issue_number:
                    await self._event_recorder.record_rca_github_issue_created(
                        sequence_id=incident.sequence_id,
                        endpoint=incident.endpoint,
                        issue_number=issue_number,
                        issue_url=issue_url,
                        classification="architectural",
                        fix_location=rca_result.get("fix_location"),
                    )

                logger.info(
                    f"Created RCA GitHub issue #{issue_number} for {incident.fingerprint}: {issue_url}"
                )
                return issue_number
            else:
                logger.error(f"Failed to create RCA issue: {result.stderr}")
                return None

        except ImportError:
            logger.warning("ACP module not available for RCA issue creation")
            return None
        except Exception as e:
            logger.error(f"Error creating RCA GitHub issue: {e}")
            return None

    async def _create_github_issue(self, incident: HealthIncident) -> None:
        """Create GitHub issue for manual incidents using gh CLI.

        ACP-Claude can then pick up these issues and investigate using
        the full power of Claude Code with MCP tools.

        Args:
            incident: The incident requiring manual intervention
        """
        import asyncio
        import subprocess

        if not self.config.github_repo:
            logger.info(
                f"GitHub integration not configured, skipping issue creation "
                f"for {incident.fingerprint}"
            )
            return

        # Check cadence - max 3 issues per day
        if not self._can_create_issue():
            logger.warning(
                f"Cadence limit reached, skipping issue creation for {incident.fingerprint}\n"
                "  Guru: #ACP.00000015.CADENCEBLOCKED"
            )
            return

        # Check for existing open issue (update recurrence count instead)
        existing_issue = await self._find_existing_issue(incident.fingerprint)
        if existing_issue:
            await self._update_issue_recurrence(existing_issue, incident)
            return

        try:
            from ...acp.security import (
                sanitize_issue_content,
                validate_issue_title,
                load_security_config,
                is_repo_in_allowlist,
            )

            # Validate repo is allowed
            security_config = load_security_config()
            if not is_repo_in_allowlist(self.config.github_repo, security_config.allowed_repos):
                logger.error(
                    f"Repository {self.config.github_repo} not in ACP allowlist.\n"
                    "  Guru: #ACP.SEC.00000002.NOTALLOWED\n"
                    "  Add to ~/.config/gaius/acp.conf: acp.github.allowed_repos"
                )
                # Record OTel metric for observability
                record_exception_caught(
                    component="acp",
                    operation="security_check",
                    exception_type="RepositoryNotAllowedError",
                    failure_mode_id=incident.failure_mode_id,
                    guru_code="#ACP.SEC.00000002.NOTALLOWED",
                )
                return

            # Build issue title
            display_endpoint = friendly_endpoint_name(incident.endpoint)
            title = f"[HEALTH-FIX] {incident.failure_mode_id}: {display_endpoint}"
            title = validate_issue_title(title)

            # Build issue body with sanitized content
            body = self._build_issue_body(incident)
            body = sanitize_issue_content(body)

            # Create issue via gh CLI
            cmd = [
                "gh", "issue", "create",
                "--repo", self.config.github_repo,
                "--title", title,
                "--body", body,
                "--label", "health-fix,automated",
            ]

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )

            if result.returncode == 0:
                # Parse issue number from output (e.g., "https://github.com/owner/repo/issues/123")
                issue_url = result.stdout.strip()
                issue_number = int(issue_url.split("/")[-1]) if "/" in issue_url else None

                incident.github_issue = issue_number
                self._issues_created_today += 1

                logger.info(
                    f"Created GitHub issue #{issue_number} for {incident.fingerprint}: {issue_url}"
                )
            else:
                logger.error(
                    f"Failed to create GitHub issue: {result.stderr}\n"
                    "  Guru: #ACP.00000014.GHISSUEFAIL"
                )
                # Record OTel metric for observability
                record_exception_caught(
                    component="acp",
                    operation="issue_create",
                    exception_type="GHIssueCreateFailed",
                    failure_mode_id=incident.failure_mode_id,
                    guru_code="#ACP.00000014.GHISSUEFAIL",
                )

        except ImportError:
            logger.warning(
                "ACP security module not available, skipping issue creation.\n"
                "  Install with: uv sync --extra acp"
            )
        except Exception as e:
            logger.error(
                f"Error creating GitHub issue: {e}\n"
                "  Guru: #ACP.00000014.GHISSUEFAIL"
            )
            # Record OTel metric for observability
            record_exception_caught(
                component="acp",
                operation="issue_create",
                exception_type=type(e).__name__,
                failure_mode_id=incident.failure_mode_id,
                guru_code="#ACP.00000014.GHISSUEFAIL",
            )

    def _build_issue_body(self, incident: HealthIncident) -> str:
        """Build GitHub issue body with incident details.

        Args:
            incident: The incident to document

        Returns:
            Markdown-formatted issue body
        """
        # Build heuristic path (convert VLLM_001 to vllm/001.md)
        failure_parts = incident.failure_mode_id.lower().split("_")
        heuristic_path = "/".join(failure_parts) + ".md" if len(failure_parts) >= 2 else incident.failure_mode_id

        # Use friendly name for user-facing display
        display_endpoint = friendly_endpoint_name(incident.endpoint)

        return f"""## Incident Details

**Fingerprint:** `{incident.fingerprint}`
**Endpoint:** `{display_endpoint}`
**Failure Mode:** `{incident.failure_mode_id}`
**RPN Score:** {incident.rpn_score} (S={incident.rpn_severity}, O={incident.rpn_occurrence}, D={incident.rpn_detection})

## Timeline

- **Created:** {incident.created_at.isoformat()}
- **Last Check:** {incident.last_check_at.isoformat()}
- **Remediation Attempts:** {incident.attempts}
- **Current Tier:** {incident.current_tier} (escalated to manual)

## Recommended Investigation

1. Check endpoint logs: `journalctl -u gaius-engine --since "1 hour ago" | grep {display_endpoint}`
2. Check GPU health: `/health gpu`
3. Review heuristic: `build/dev/current/heuristics/gaius/{heuristic_path}`

## Actions

- [ ] Investigate root cause
- [ ] Implement fix or enhancement to `/health fix`
- [ ] Verify fix resolves the issue
- [ ] Update KB heuristic if needed

---
*Auto-generated by HealthObserver daemon*
*Guru: #{incident.failure_mode_id}*
"""

    def _can_create_issue(self) -> bool:
        """Check if cadence policy allows creating an issue.

        Returns:
            True if within daily limit
        """
        # Reset counter if new day
        if hasattr(self, "_last_issue_date"):
            from datetime import date
            if date.today() != self._last_issue_date:
                self._issues_created_today = 0
                self._last_issue_date = date.today()
        else:
            from datetime import date
            self._last_issue_date = date.today()
            self._issues_created_today = 0

        return self._issues_created_today < self.config.max_issues_per_day

    async def _find_existing_issue(self, fingerprint: str) -> int | None:
        """Find existing open issue for this incident fingerprint.

        Args:
            fingerprint: Incident fingerprint to search for

        Returns:
            Issue number if found, None otherwise
        """
        import asyncio
        import subprocess

        if not self.config.github_repo:
            return None

        try:
            # Search for open issues with this fingerprint
            cmd = [
                "gh", "issue", "list",
                "--repo", self.config.github_repo,
                "--state", "open",
                "--search", f"in:body {fingerprint}",
                "--json", "number",
                "--limit", "1",
            ]

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            )

            if result.returncode == 0 and result.stdout.strip():
                import json
                issues = json.loads(result.stdout)
                if issues:
                    return issues[0]["number"]

        except Exception as e:
            logger.debug(f"Error searching for existing issue: {e}")

        return None

    async def _is_github_issue_closed(self, issue_number: int) -> bool:
        """Check if a GitHub issue is closed.

        Used to resolve MANUAL_REQUIRED incidents when their linked
        GitHub issue is closed.

        Args:
            issue_number: GitHub issue number

        Returns:
            True if issue is closed, False otherwise (or on error)
        """
        import asyncio
        import subprocess

        if not self.config.github_repo:
            return False

        try:
            cmd = [
                "gh", "issue", "view",
                str(issue_number),
                "--repo", self.config.github_repo,
                "--json", "state",
            ]

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            )

            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout)
                return data.get("state") == "CLOSED"

        except Exception as e:
            logger.debug(f"Error checking GitHub issue #{issue_number}: {e}")

        return False

    async def _update_issue_recurrence(self, issue_number: int, incident: HealthIncident) -> None:
        """Add recurrence comment to existing issue.

        Args:
            issue_number: GitHub issue number
            incident: Current incident occurrence
        """
        import asyncio
        import subprocess

        try:
            from ...acp.security import sanitize_issue_content

            comment = f"""## Recurrence Detected

**Time:** {incident.last_check_at.isoformat()}
**RPN Score:** {incident.rpn_score}
**Attempts:** {incident.attempts}

This incident has recurred. Previous remediation may not have addressed root cause.

---
*Auto-comment by HealthObserver*
"""
            comment = sanitize_issue_content(comment)

            cmd = [
                "gh", "issue", "comment",
                str(issue_number),
                "--repo", self.config.github_repo,
                "--body", comment,
            ]

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            )

            if result.returncode == 0:
                logger.info(f"Updated issue #{issue_number} with recurrence info")
            else:
                logger.warning(f"Failed to update issue #{issue_number}: {result.stderr}")

        except Exception as e:
            logger.warning(f"Error updating issue #{issue_number}: {e}")

    async def _check_recoveries(self, report: dict[str, Any]) -> None:
        """Check if recovering incidents have stabilized.

        Incidents in "recovering" status are checked for sustained health.
        If healthy for recovery_verification_time, they are resolved.

        Also handles "active" incidents that may have recovered while the
        engine was down (restored from DB) - transitions them to "recovering".

        Args:
            report: Current health report
        """
        resolved = []

        for fingerprint, incident in self._active_incidents.items():
            # Check if the associated check is now passing
            check_passed = self._check_passed_for_incident(report, incident)

            # If check status is indeterminate, skip this incident
            # (don't assume passed or failed when we can't find matching check)
            if check_passed is None:
                continue

            # Handle "active" incidents that are now healthy
            # This catches incidents restored from DB that recovered during downtime
            if incident.status == "active" and check_passed:
                incident.status = "recovering"
                timer_start = datetime.now()
                self._recovery_start[fingerprint] = timer_start

                # Persist recovery timer start to DB for restart resilience
                if self._event_recorder and incident.sequence_id:
                    await self._event_recorder.record_recovery_timer_started(
                        sequence_id=incident.sequence_id,
                        endpoint=incident.endpoint,
                        fingerprint=fingerprint,
                        started_at=timer_start,
                    )

                logger.info(
                    f"Incident {fingerprint} now healthy, starting recovery verification"
                )
                continue

            # Handle MANUAL_REQUIRED incidents with closed GitHub issues
            if incident.status == "manual_required" and incident.github_issue:
                if await self._is_github_issue_closed(incident.github_issue):
                    logger.info(
                        f"GitHub issue #{incident.github_issue} closed for {fingerprint}, "
                        "resolving incident"
                    )
                    resolved.append(fingerprint)
                continue

            if incident.status != "recovering":
                continue

            # Defensive check: if incident is recovering but timer is missing,
            # start the timer now. This can happen if timer was lost (e.g., old
            # incidents that predate timer persistence, or corruption).
            if fingerprint not in self._recovery_start:
                logger.warning(
                    f"Recovery timer missing for {fingerprint}, starting now"
                )
                timer_start = datetime.now()
                self._recovery_start[fingerprint] = timer_start

                # Persist the timer start for future restarts
                if self._event_recorder and incident.sequence_id:
                    await self._event_recorder.record_recovery_timer_started(
                        sequence_id=incident.sequence_id,
                        endpoint=incident.endpoint,
                        fingerprint=fingerprint,
                        started_at=timer_start,
                    )

            if check_passed:
                recovery_start = self._recovery_start.get(fingerprint)
                if recovery_start:
                    # Handle timezone-aware recovery_start (from DB restore)
                    now = datetime.now(timezone.utc)
                    if recovery_start.tzinfo is None:
                        recovery_start = recovery_start.replace(tzinfo=timezone.utc)
                    elapsed = (now - recovery_start).total_seconds()
                    if elapsed >= self.config.recovery_verification_time:
                        resolved.append(fingerprint)
            else:
                # Recovery failed - transition back to active
                incident.status = "active"
                self._recovery_start.pop(fingerprint, None)

                # Record timer cleared due to regression
                if self._event_recorder and incident.sequence_id:
                    await self._event_recorder.record_recovery_timer_cleared(
                        sequence_id=incident.sequence_id,
                        endpoint=incident.endpoint,
                        fingerprint=fingerprint,
                        reason="recovery_failed",
                    )

        # Resolve completed recoveries
        for fingerprint in resolved:
            incident = self._active_incidents.pop(fingerprint)
            self._recovery_start.pop(fingerprint, None)
            self._incidents_resolved += 1

            # Record incident resolution for Observe panel
            record_incident_change(delta=-1, status="resolved")

            # Record timer cleared due to successful resolution
            if self._event_recorder and incident.sequence_id:
                await self._event_recorder.record_recovery_timer_cleared(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    fingerprint=fingerprint,
                    reason="resolved",
                )

                # Handle timezone-aware created_at
                now = datetime.now(timezone.utc)
                created_at = incident.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                total_duration_ms = int(
                    (now - created_at).total_seconds() * 1000
                )
                await self._event_recorder.complete_sequence(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    outcome="success",
                    total_attempts=incident.attempts,
                    final_tier=incident.current_tier,
                    total_duration_ms=total_duration_ms,
                )

            logger.info(f"Incident resolved: {fingerprint}")

            for callback in self._on_resolution:
                try:
                    await callback(incident)
                except Exception as e:
                    logger.warning(f"Resolution callback error: {e}")

    async def _escalate_stale_incidents(self, report: dict[str, Any]) -> None:
        """Escalate long-duration incidents that haven't progressed.

        This is the key mechanism for ensuring ACP escalation happens for
        incidents that are stuck - whether due to false positives, recovery
        detection bugs, or genuine issues that need Claude Code investigation.

        Stale incident criteria:
        - Status is "active" (not healing, recovering, or manual_required)
        - Age exceeds stale threshold (default 1 hour)
        - Current tier < 3 (not yet at manual level)

        For stale incidents:
        - Tier 0-1: Escalate to tier 2 (ACP)
        - Tier 2: Retry ACP escalation, then escalate to tier 3 (GitHub issue)

        Args:
            report: Current health report (for context in escalation)
        """
        # Stale threshold: 1 hour without resolution or tier progression
        stale_threshold_seconds = 3600  # 1 hour

        now = datetime.now()

        for fingerprint, incident in self._active_incidents.items():
            # Only escalate "active" incidents (not healing/recovering/manual)
            if incident.status != "active":
                continue

            # Calculate incident age
            # Use created_at if timezone-aware, else use last_check_at
            try:
                if incident.created_at.tzinfo:
                    # Timezone-aware: convert to naive for comparison
                    created_naive = incident.created_at.replace(tzinfo=None)
                else:
                    created_naive = incident.created_at
                age_seconds = (now - created_naive).total_seconds()
            except Exception:
                # Fallback to last_check_at
                age_seconds = (now - incident.last_check_at).total_seconds()

            # Check if incident is stale
            if age_seconds < stale_threshold_seconds:
                continue

            # Incident is stale - needs escalation
            logger.warning(
                f"Stale incident detected: {fingerprint} "
                f"(age={age_seconds/3600:.1f}h, tier={incident.current_tier}, "
                f"attempts={incident.attempts}, status={incident.status})"
            )

            # Escalation logic based on current tier
            if incident.current_tier < 2:
                # Tier 0-1: Escalate directly to tier 2 (ACP)
                logger.info(
                    f"Escalating stale incident {fingerprint} from tier "
                    f"{incident.current_tier} to tier 2 (ACP)"
                )
                incident.current_tier = 2
                await self._attempt_remediation(incident)

            elif incident.current_tier == 2:
                # Tier 2: Try ACP one more time, then escalate to tier 3
                # Check if we've already attempted ACP recently
                if incident.attempts < 3:
                    logger.info(
                        f"Retrying ACP escalation for stale incident {fingerprint} "
                        f"(attempt {incident.attempts + 1})"
                    )
                    await self._attempt_remediation(incident)
                else:
                    # Too many ACP attempts - escalate to tier 3 (GitHub issue)
                    logger.info(
                        f"Escalating stale incident {fingerprint} to tier 3 "
                        f"(GitHub issue) after {incident.attempts} ACP attempts"
                    )
                    incident.current_tier = 3
                    await self._create_github_issue(incident)
                    incident.status = "manual_required"

            # Tier 3+ already has GitHub issue - no further escalation needed

    def _check_passed_for_incident(
        self,
        report: dict[str, Any],
        incident: HealthIncident,
    ) -> bool | None:
        """Check if the health check for an incident is now passing.

        Args:
            report: Current health report
            incident: The incident to check

        Returns:
            True if associated check is passing, False if failing,
            None if no matching check found (status indeterminate)
        """
        # Normalize incident endpoint for matching
        normalized_endpoint = friendly_endpoint_name(incident.endpoint)

        # For VLLM incidents, first check the endpoints dict directly
        # The internal health report stores all endpoint statuses here,
        # but only creates "checks" entries for FAILED endpoints.
        # So when an endpoint recovers, we need to look here.
        if incident.failure_mode_id.startswith("VLLM"):
            endpoints_dict = report.get("endpoints", {})
            for alias, ep_info in endpoints_dict.items():
                if friendly_endpoint_name(alias) == normalized_endpoint:
                    ep_status = ep_info.get("status", "unknown")
                    healthy_statuses = {
                        "healthy", "running", "ready",
                        "PROCESS_STATUS_HEALTHY",
                    }
                    if ep_status in healthy_statuses:
                        logger.debug(
                            f"Incident {incident.fingerprint}: endpoint {alias} "
                            f"is healthy ({ep_status})"
                        )
                        return True
                    else:
                        logger.debug(
                            f"Incident {incident.fingerprint}: endpoint {alias} "
                            f"is still unhealthy ({ep_status})"
                        )
                        return False

        # Fall back to checking individual check entries
        for check in report.get("checks", []):
            # Normalize check endpoint for comparison
            check_endpoint = friendly_endpoint_name(
                check.get("endpoint", check.get("name", "")).lower()
            )
            if normalized_endpoint == check_endpoint or normalized_endpoint in check_endpoint:
                return check.get("status") != "FAIL"
            if check.get("heuristic_id") == incident.failure_mode_id:
                return check.get("status") != "FAIL"

            # For VLLM incidents, check if endpoint is in the healthy endpoints list
            # The "Engine Endpoints" check contains a list of healthy endpoints
            if incident.failure_mode_id.startswith("VLLM"):
                details = check.get("details", {})
                endpoints_list = details.get("endpoints", [])
                if normalized_endpoint in endpoints_list:
                    # Endpoint is in the healthy list, check passed
                    return check.get("status") != "FAIL"

        # If no matching check found, return None (don't assume passed or failed)
        return None

    def _generate_fingerprint(self, check: dict[str, Any]) -> str:
        """Generate deduplication fingerprint for a check result.

        Args:
            check: Health check dict

        Returns:
            Fingerprint string (failure_mode_id:endpoint)
        """
        failure_mode = check.get("heuristic_id") or f"UNKNOWN_{check['name'][:10].upper()}"
        details = check.get("details", {})
        endpoint = details.get("endpoint", check["name"].lower().replace(" ", "_"))
        # Normalize endpoint name to strip internal prefixes (e.g., cap_reasoning -> reasoning)
        endpoint = friendly_endpoint_name(endpoint)
        return f"{failure_mode}:{endpoint}"

    def _has_active_healing(self) -> bool:
        """Check if any incidents are actively being healed.

        Returns:
            True if any incidents are in healing status
        """
        return any(
            inc.status in ("healing", "recovering")
            for inc in self._active_incidents.values()
        )

    def on_incident(
        self,
        callback: Callable[[HealthIncident], Awaitable[None]],
    ) -> None:
        """Register callback for new incidents.

        Args:
            callback: Async function called when incident is created
        """
        self._on_incident.append(callback)

    def on_resolution(
        self,
        callback: Callable[[HealthIncident], Awaitable[None]],
    ) -> None:
        """Register callback for resolved incidents.

        Args:
            callback: Async function called when incident is resolved
        """
        self._on_resolution.append(callback)

    async def force_check(self) -> dict[str, Any]:
        """Force an immediate health check.

        Bypasses the poll interval for on-demand checking.
        Also triggers stale incident escalation.

        Returns:
            Health report dict with current status
        """
        report = await self._run_health_check()
        self._last_report = report
        self._poll_count += 1
        self._last_poll_at = datetime.now()

        await self._process_failures(report)
        await self._check_recoveries(report)
        await self._escalate_stale_incidents(report)

        return report

    def get_incident(self, fingerprint: str) -> HealthIncident | None:
        """Get incident by fingerprint.

        Args:
            fingerprint: Incident fingerprint (failure_mode_id:endpoint)

        Returns:
            HealthIncident if found, None otherwise
        """
        return self._active_incidents.get(fingerprint)

    async def get_incident_detail(self, fingerprint: str) -> dict[str, Any] | None:
        """Get detailed incident info including healing event history.

        Args:
            fingerprint: Incident fingerprint (failure_mode_id:endpoint)

        Returns:
            Detailed incident dict with healing history, or None if not found
        """
        incident = self._active_incidents.get(fingerprint)
        if not incident:
            return None

        result = incident.to_dict()

        # Add healing event history from database if we have event recorder
        if self._event_recorder and incident.sequence_id:
            try:
                events = await self._event_recorder.get_sequence_events(incident.sequence_id)
                result["healing_events"] = events

                # Extract ACP-specific events for easy access
                acp_events = [
                    e for e in events
                    if e.get("event_type", "").startswith("acp_")
                ]
                result["acp_history"] = acp_events
            except Exception as e:
                logger.warning(f"Could not fetch healing events for {fingerprint}: {e}")
                result["healing_events"] = []
                result["acp_history"] = []

        return result

    def get_status(self) -> dict[str, Any]:
        """Get daemon status for monitoring.

        Returns:
            Status dict with running state, metrics, incidents, etc.
        """
        return {
            "running": self._running,
            "enabled": self.config.enabled,
            "poll_count": self._poll_count,
            "last_poll_at": (
                self._last_poll_at.isoformat() if self._last_poll_at else None
            ),
            "active_incidents": len(self._active_incidents),
            "incidents": [inc.to_dict() for inc in self._active_incidents.values()],
            "metrics": {
                "incidents_created": self._incidents_created,
                "incidents_resolved": self._incidents_resolved,
                "acp_escalations": self._acp_escalations,
            },
            "last_report": self._last_report,
            "config": {
                "poll_interval": self.config.poll_interval,
                "escalate_to_acp": self.config.escalate_to_acp,
                "github_repo": self.config.github_repo,
            },
        }

    @property
    def is_running(self) -> bool:
        """Whether service is running (BaseDaemon protocol)."""
        return self._running

    async def health_check(self) -> DaemonHealth:
        """Check daemon health (BaseDaemon protocol).

        Returns:
            DaemonHealth with status and diagnostics
        """
        if not self._running:
            return DaemonHealth(
                healthy=False,
                message="HealthObserver daemon not running",
                guru_code="#HO.00000001.NOTRUNNING",
                details={
                    "running": False,
                    "poll_count": self._poll_count,
                    "enabled": self.config.enabled,
                },
            )

        # Check if polling is stalled (no poll in 5x poll interval)
        if self._last_poll_at:
            stall_threshold = self.config.poll_interval * 5
            # Handle timezone consistency
            now = datetime.now()
            last_poll = self._last_poll_at
            if last_poll.tzinfo and now.tzinfo is None:
                now = datetime.now(timezone.utc)
                last_poll = last_poll if last_poll.tzinfo else last_poll.replace(tzinfo=timezone.utc)
            elif last_poll.tzinfo is None and now.tzinfo:
                last_poll = last_poll.replace(tzinfo=timezone.utc)
            since_last_poll = (now - last_poll).total_seconds()
            if since_last_poll > stall_threshold:
                return DaemonHealth(
                    healthy=False,
                    message=f"Health polling stalled ({since_last_poll:.0f}s since last poll)",
                    guru_code="#HO.00000003.STALLED",
                    details={
                        "running": True,
                        "seconds_since_last_poll": since_last_poll,
                        "poll_count": self._poll_count,
                    },
                )

        return DaemonHealth(
            healthy=True,
            message=f"HealthObserver running, {self._poll_count} polls completed",
            details={
                "running": True,
                "poll_count": self._poll_count,
                "active_incidents": len(self._active_incidents),
                "acp_escalations": self._acp_escalations,
            },
        )

    def set_daemon_registry(self, registry: "DaemonRegistry") -> None:
        """Set reference to daemon registry for cross-daemon monitoring.

        Args:
            registry: The DaemonRegistry instance
        """
        self._daemon_registry = registry
        logger.debug("DaemonRegistry reference set in HealthObserverService")
