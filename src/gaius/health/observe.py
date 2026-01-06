"""HealthObserver daemon for autonomous health monitoring and remediation.

Implements continuous observability following the EvolutionDaemon pattern.
Integrates with ACP (Agent Client Protocol) to delegate complex diagnosis
and remediation to Claude Code.

Aligned with OTel terminology:
- Observer: Watches system health metrics
- Spans: Healing sequences tracked as traces
- Events: Health check results as trace events

Usage:
    daemon = get_health_observer()
    await daemon.start()

    # Runs in background, polling health every poll_interval seconds
    # On failure: calculate RPN, attempt self-healing, escalate to Claude Code

    await daemon.stop()  # Graceful shutdown
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Awaitable, ClassVar
from uuid import UUID, uuid4
import time

from .checker import HealthChecker, HealthReport, CheckResult, CheckStatus
from .self_healing import SelfHealingCoordinator, HealthIssue, HealingResult
from .healing_events import HealingEventRecorder, HealingEventType
from .fmea.models import RPNScore, EscalationTier
from ..acp.security import get_github_repo_from_remote

if TYPE_CHECKING:
    from asyncpg import Pool
    from ..acp import GaiusACPClient
    from ..acp.prompts import WorkflowMode, CadencePolicy

logger = logging.getLogger(__name__)


@dataclass
class ObserverConfig:
    """Configuration for HealthObserver daemon.

    Attributes:
        enabled: Enable/disable daemon
        poll_interval: Seconds between health checks (default 30)
        burst_interval: Faster polling when healing in progress (default 5)
        backoff_interval: Slower polling after errors (default 120)
        escalate_to_acp: Enable ACP escalation for complex issues
        acp_timeout: Timeout for ACP prompts in seconds
        github_repo: Repository for issue tracking (required for full workflow)
        github_token_env: Environment variable with GitHub token
        kb_root: Path to knowledge base root
        recovery_verification_time: Seconds of stable health before closing incident
        min_interval_between_restarts: Cadence control - seconds between restart attempts
        max_restarts_per_hour: Cadence control - max restarts per endpoint per hour
        observation_window: Seconds to observe before recommending intervention
        cooldown_after_failure: Seconds to wait after failed remediation
    """
    enabled: bool = True

    # Polling intervals
    poll_interval: float = 30.0
    burst_interval: float = 5.0
    backoff_interval: float = 120.0

    # ACP integration
    escalate_to_acp: bool = True
    acp_timeout: float = 300.0  # 5 minutes

    # GitHub integration - reads from git remote 'internal' by default
    # Supports full URL format for on-prem: github.example.com/org/repo
    github_repo: str = field(default_factory=lambda: get_github_repo_from_remote() or "")
    github_token_env: str = "GITHUB_TOKEN"

    # KB and FMEA
    kb_root: str = "build/dev"

    # Recovery verification
    recovery_verification_time: float = 300.0  # 5 minutes

    # Cadence controls (prevent runaway remediation)
    min_interval_between_restarts: int = 300  # 5 minutes
    max_restarts_per_hour: int = 3
    observation_window: int = 180  # 3 minutes
    cooldown_after_failure: int = 900  # 15 minutes


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
    """
    incident_id: UUID
    fingerprint: str
    endpoint: str
    failure_mode_id: str
    rpn: RPNScore
    current_tier: int = 0
    sequence_id: UUID | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_check_at: datetime = field(default_factory=datetime.now)
    attempts: int = 0
    github_issue: int | None = None
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "incident_id": str(self.incident_id),
            "fingerprint": self.fingerprint,
            "endpoint": self.endpoint,
            "failure_mode_id": self.failure_mode_id,
            "rpn": self.rpn.to_dict(),
            "current_tier": self.current_tier,
            "sequence_id": str(self.sequence_id) if self.sequence_id else None,
            "created_at": self.created_at.isoformat(),
            "last_check_at": self.last_check_at.isoformat(),
            "attempts": self.attempts,
            "github_issue": self.github_issue,
            "status": self.status,
        }


class HealthObserver:
    """Long-lived daemon for autonomous health monitoring and remediation.

    Implements the Observer pattern with OTel-aligned terminology:
    - Continuous health observation via HealthChecker
    - FMEA-based RPN scoring for risk assessment
    - Tiered self-healing with escalation to Claude Code via ACP
    - Event-sourced healing audit trail
    - GitHub issue tracking for persistent incidents

    The observer integrates with Claude Code through ACP, delegating:
    - Complex root cause analysis
    - Remediation planning
    - GitHub issue management
    - Code-level fixes when needed
    """

    _instance: ClassVar["HealthObserver | None"] = None

    def __init__(self, config: ObserverConfig | None = None):
        """Initialize the HealthObserver.

        Args:
            config: Observer configuration (uses defaults if None)
        """
        self.config = config or ObserverConfig()

        # Core components
        self._checker = HealthChecker(kb_root=Path(self.config.kb_root))
        self._coordinator: SelfHealingCoordinator | None = None
        self._event_recorder: HealingEventRecorder | None = None
        self._acp_client: "GaiusACPClient | None" = None
        self._agenda_tracker: "AgendaTracker | None" = None

        # State
        self._running = False
        self._task: asyncio.Task | None = None
        self._active_incidents: dict[str, HealthIncident] = {}  # fingerprint -> incident
        self._recovery_start: dict[str, datetime] = {}  # fingerprint -> when recovery started

        # Metrics
        self._poll_count = 0
        self._incidents_created = 0
        self._incidents_resolved = 0
        self._acp_escalations = 0
        self._last_poll_at: datetime | None = None
        self._last_report: HealthReport | None = None

        # Callbacks
        self._on_incident: list[Callable[[HealthIncident], Awaitable[None]]] = []
        self._on_resolution: list[Callable[[HealthIncident], Awaitable[None]]] = []

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

    @property
    def last_report(self) -> HealthReport | None:
        """Most recent health report."""
        return self._last_report

    async def start(self) -> None:
        """Start the health observer daemon.

        Begins background health monitoring loop.
        """
        if self._running:
            logger.warning("HealthObserver already running")
            return

        if not self.config.enabled:
            logger.info("HealthObserver disabled by config")
            return

        # Initialize components
        await self._init_components()

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"HealthObserver started (poll_interval={self.config.poll_interval}s, "
            f"acp_enabled={self.config.escalate_to_acp})"
        )

    async def _init_components(self) -> None:
        """Initialize daemon components."""
        # Event recorder
        self._event_recorder = HealingEventRecorder()

        # Self-healing coordinator (lazy-loaded when needed)
        # Will be initialized on first healing attempt

        # ACP client (lazy-loaded when needed)
        # Will be initialized on first ACP escalation

        # Load persisted state from database
        await self._load_state_from_db()

    async def _get_pool(self) -> "Pool | None":
        """Get database pool."""
        try:
            from ..storage.database import get_pool
            return await get_pool()
        except Exception as e:
            logger.warning(f"Cannot get database pool: {e}")
            return None

    async def _load_state_from_db(self) -> None:
        """Load persisted state from health_observer_state table.

        Restores counters and active incidents from previous run.
        """
        pool = await self._get_pool()
        if not pool:
            logger.info("No database pool, starting with fresh state")
            return

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT poll_count, active_incidents, acp_prompts_sent,
                           acp_prompts_succeeded, last_poll_at
                    FROM health_observer_state
                    WHERE id = 1
                    """
                )

                if row:
                    self._poll_count = row["poll_count"] or 0
                    self._acp_escalations = row["acp_prompts_sent"] or 0
                    if row["last_poll_at"]:
                        self._last_poll_at = row["last_poll_at"]

                    # Restore active incidents from JSON
                    active_incidents_json = row["active_incidents"]
                    if active_incidents_json:
                        for fingerprint, data in active_incidents_json.items():
                            try:
                                incident = HealthIncident(
                                    incident_id=UUID(data["incident_id"]),
                                    fingerprint=fingerprint,
                                    endpoint=data["endpoint"],
                                    failure_mode_id=data["failure_mode_id"],
                                    rpn=RPNScore(
                                        severity=data["rpn"]["severity"],
                                        occurrence=data["rpn"]["occurrence"],
                                        detection=data["rpn"]["detection"],
                                        rpn=data["rpn"]["rpn"],
                                        failure_mode_id=data["rpn"].get("failure_mode_id", ""),
                                    ),
                                    current_tier=data.get("current_tier", 0),
                                    sequence_id=UUID(data["sequence_id"]) if data.get("sequence_id") else None,
                                    created_at=datetime.fromisoformat(data["created_at"]),
                                    last_check_at=datetime.fromisoformat(data.get("last_check_at", data["created_at"])),
                                    attempts=data.get("attempts", 0),
                                    github_issue=data.get("github_issue"),
                                    status=data.get("status", "active"),
                                )
                                self._active_incidents[fingerprint] = incident
                            except Exception as e:
                                logger.warning(f"Could not restore incident {fingerprint}: {e}")

                    logger.info(
                        f"Loaded state from DB: poll_count={self._poll_count}, "
                        f"active_incidents={len(self._active_incidents)}, "
                        f"acp_escalations={self._acp_escalations}"
                    )

                # Also count ACP escalations from healing_events as fallback
                acp_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM healing_events
                    WHERE event_type = 'acp_escalation_started'
                    """
                )
                if acp_count and acp_count > self._acp_escalations:
                    self._acp_escalations = acp_count
                    logger.debug(f"Updated acp_escalations from healing_events: {acp_count}")

        except Exception as e:
            logger.error(f"Failed to load state from DB: {e}")

    async def _save_state_to_db(self) -> None:
        """Save current state to health_observer_state table.

        Called after each poll cycle to persist state.
        """
        pool = await self._get_pool()
        if not pool:
            return

        try:
            # Convert active incidents to JSON
            active_incidents_json = {
                fp: inc.to_dict() for fp, inc in self._active_incidents.items()
            }

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE health_observer_state SET
                        started_at = COALESCE(started_at, $1),
                        last_poll_at = $2,
                        poll_count = $3,
                        active_incidents = $4,
                        acp_prompts_sent = $5,
                        config = $6
                    WHERE id = 1
                    """,
                    datetime.now() if self._running else None,
                    self._last_poll_at,
                    self._poll_count,
                    json.dumps(active_incidents_json),
                    self._acp_escalations,
                    json.dumps({
                        "poll_interval": self.config.poll_interval,
                        "escalate_to_acp": self.config.escalate_to_acp,
                        "github_repo": self.config.github_repo,
                    }),
                )

            logger.debug(f"Saved state to DB: poll_count={self._poll_count}")

        except Exception as e:
            logger.warning(f"Failed to save state to DB: {e}")

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

        logger.info("HealthObserver stopped")

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

                # Persist state to database
                await self._save_state_to_db()

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

    async def _run_health_check(self) -> HealthReport:
        """Run comprehensive health check.

        Returns:
            HealthReport with all check results
        """
        return await self._checker.run_all()

    async def _process_failures(self, report: HealthReport) -> None:
        """Process failed health checks.

        For each failure:
        1. Check if endpoint is in scheduled transition (not a real failure)
        2. Calculate fingerprint for deduplication
        3. Check if incident exists
        4. Create or update incident
        5. Calculate RPN
        6. Attempt remediation based on tier

        Args:
            report: Health report with check results
        """
        # Lazy-load AgendaTracker if available
        if self._agenda_tracker is None:
            try:
                from ..engine.services.agenda_tracker import get_agenda_tracker
                self._agenda_tracker = get_agenda_tracker()
            except Exception:
                pass  # AgendaTracker not available, proceed without it

        for check in report.checks:
            if check.status != CheckStatus.FAIL:
                continue

            # Extract endpoint from check details
            endpoint = check.details.get("endpoint", check.name.lower().replace(" ", "_"))

            # Skip if endpoint is in a scheduled transition (not a real failure)
            if self._agenda_tracker is not None:
                if self._agenda_tracker.is_endpoint_in_scheduled_transition(endpoint):
                    expected_state = self._agenda_tracker.get_scheduled_endpoint_state(endpoint)
                    logger.debug(
                        f"Skipping incident for {endpoint}: scheduled transition to {expected_state}"
                    )
                    continue

            # Generate fingerprint for deduplication
            fingerprint = self._generate_fingerprint(check)

            # Check existing incident
            if fingerprint in self._active_incidents:
                incident = self._active_incidents[fingerprint]
                incident.last_check_at = datetime.now()
                incident.status = "active"  # Reset from recovering
                self._recovery_start.pop(fingerprint, None)
                continue

            # Create new incident
            incident = await self._create_incident(check)
            if incident:
                self._active_incidents[fingerprint] = incident
                self._incidents_created += 1

                # Notify callbacks
                for callback in self._on_incident:
                    try:
                        await callback(incident)
                    except Exception as e:
                        logger.warning(f"Incident callback error: {e}")

                # Attempt remediation
                await self._attempt_remediation(incident)

    async def _create_incident(self, check: CheckResult) -> HealthIncident | None:
        """Create a new health incident from a failed check.

        Args:
            check: Failed health check result

        Returns:
            HealthIncident if created, None on error
        """
        try:
            # Extract endpoint from check details
            endpoint = check.details.get("endpoint", check.name.lower().replace(" ", "_"))

            # Get failure mode ID from heuristic
            failure_mode_id = check.heuristic_id or f"UNKNOWN_{check.name[:10].upper()}"

            # Calculate RPN
            rpn = await self._calculate_rpn(failure_mode_id, check)

            # Generate fingerprint
            fingerprint = f"{failure_mode_id}:{endpoint}"

            # Create incident
            incident = HealthIncident(
                incident_id=uuid4(),
                fingerprint=fingerprint,
                endpoint=endpoint,
                failure_mode_id=failure_mode_id,
                rpn=rpn,
                current_tier=rpn.tier.value,
            )

            # Start event sequence
            if self._event_recorder:
                sequence_id = await self._event_recorder.start_sequence(
                    endpoint=endpoint,
                    issue_type=check.status.value,
                    check_name=check.name,
                    severity="critical" if rpn.tier == EscalationTier.MANUAL else "warning",
                    rpn_score=rpn.rpn,
                    context=check.details,
                    failure_mode_id=failure_mode_id,
                )
                incident.sequence_id = sequence_id

            logger.info(
                f"Created incident {incident.incident_id}: {fingerprint} "
                f"(RPN={rpn.rpn}, tier={rpn.tier.name})"
            )
            return incident

        except Exception as e:
            logger.error(f"Failed to create incident from check {check.name}: {e}")
            return None

    async def _calculate_rpn(
        self,
        failure_mode_id: str,
        check: CheckResult,
    ) -> RPNScore:
        """Calculate RPN score for a failure.

        Uses FMEA engine with context adjustments.

        Args:
            failure_mode_id: FMEA failure mode identifier
            check: Health check result for context

        Returns:
            Calculated RPNScore
        """
        try:
            from .fmea.engine import FMEAEngine

            engine = FMEAEngine(kb_root=self.config.kb_root)
            return await engine.calculate_rpn(
                failure_mode_id=failure_mode_id,
                context=check.details,
            )
        except Exception as e:
            logger.warning(f"FMEA calculation failed, using defaults: {e}")
            # Return default mid-tier RPN
            return RPNScore(
                severity=5,
                occurrence=5,
                detection=5,
                rpn=125,
                failure_mode_id=failure_mode_id,
            )

    async def _attempt_remediation(self, incident: HealthIncident) -> None:
        """Attempt to remediate an incident based on its tier.

        Tier 0: Auto-remediate immediately via SelfHealingCoordinator
        Tier 1: Auto-remediate with local agent validation
        Tier 2: Escalate to Claude Code via ACP for approval
        Manual: Create GitHub issue and notify

        Args:
            incident: The incident to remediate
        """
        incident.attempts += 1
        incident.status = "healing"

        rpn = incident.rpn
        tier = EscalationTier(incident.current_tier)

        logger.info(
            f"Attempting remediation for {incident.fingerprint} "
            f"(attempt {incident.attempts}, tier {tier.name})"
        )

        try:
            if tier == EscalationTier.TIER_0:
                # Auto-remediate via SelfHealingCoordinator
                result = await self._tier0_remediate(incident)

            elif tier == EscalationTier.TIER_1:
                # Local agent validation
                result = await self._tier1_remediate(incident)

            elif tier == EscalationTier.TIER_2:
                # Escalate to Claude Code
                result = await self._tier2_remediate_acp(incident)

            else:  # MANUAL
                # Create GitHub issue and stop
                await self._create_github_issue(incident)
                incident.status = "manual_required"
                return

            # Handle result
            if result.success:
                incident.status = "recovering"
                self._recovery_start[incident.fingerprint] = datetime.now()
                logger.info(f"Remediation succeeded for {incident.fingerprint}")
            elif result.escalate:
                # Escalate to next tier
                incident.current_tier = min(incident.current_tier + 1, 3)
                logger.info(
                    f"Escalating {incident.fingerprint} to tier {incident.current_tier}"
                )
                # Retry with new tier
                await self._attempt_remediation(incident)
            else:
                logger.warning(
                    f"Remediation failed for {incident.fingerprint}: {result.reason}"
                )

        except Exception as e:
            logger.error(f"Remediation error for {incident.fingerprint}: {e}")

    async def _tier0_remediate(self, incident: HealthIncident) -> HealingResult:
        """Tier 0 procedural remediation.

        Uses SelfHealingCoordinator for code-only recovery.

        Args:
            incident: The incident to remediate

        Returns:
            HealingResult with outcome
        """
        if self._coordinator is None:
            # Lazy-load coordinator
            try:
                from ..engine.services.orchestrator_service import get_orchestrator_service

                orch = get_orchestrator_service()
                self._coordinator = SelfHealingCoordinator(orch)
            except Exception as e:
                logger.warning(f"Cannot initialize SelfHealingCoordinator: {e}")
                return HealingResult(
                    success=False,
                    escalate=True,
                    reason=f"Coordinator unavailable: {e}",
                )

        issue = HealthIssue(
            endpoint=incident.endpoint,
            issue_type=incident.failure_mode_id,
            error_message=f"RPN={incident.rpn.rpn}",
            check_name=incident.fingerprint,
            severity="critical" if incident.rpn.rpn > 200 else "warning",
            context=incident.rpn.context_adjustments,
        )

        result = await self._coordinator.handle_health_issue(issue)
        return result

    async def _tier1_remediate(self, incident: HealthIncident) -> HealingResult:
        """Tier 1 local agent remediation.

        Uses local LLM for validation before applying fix.

        Args:
            incident: The incident to remediate

        Returns:
            HealingResult with outcome
        """
        # Tier 1 delegates to coordinator with agent validation
        # For now, use same path as Tier 0 but record the tier difference
        result = await self._tier0_remediate(incident)

        # Record tier 1 attempt in events
        if self._event_recorder and incident.sequence_id:
            await self._event_recorder.record_tier_entered(
                sequence_id=incident.sequence_id,
                endpoint=incident.endpoint,
                to_tier=1,
                from_tier=0,
                reason="escalation from tier 0",
            )

        return result

    async def _tier2_remediate_acp(self, incident: HealthIncident) -> HealingResult:
        """Tier 2 ACP escalation to Claude Code.

        Delegates complex diagnosis and remediation to Claude Code
        via the Agent Client Protocol.

        Args:
            incident: The incident to remediate

        Returns:
            HealingResult with outcome
        """
        if not self.config.escalate_to_acp:
            return HealingResult(
                success=False,
                escalate=True,
                reason="ACP escalation disabled",
            )

        start_time = time.time()

        # Build prompt and context for Claude Code
        prompt = self._build_acp_prompt(incident)
        context_summary = self._build_context_summary(incident)

        # Calculate incident age
        incident_age_seconds = int((datetime.now() - incident.created_at).total_seconds())

        # Build escalation reason
        escalation_reason = self._build_escalation_reason(incident)

        # Record escalation start with full context
        if self._event_recorder and incident.sequence_id:
            await self._event_recorder.record_acp_escalation_started(
                sequence_id=incident.sequence_id,
                endpoint=incident.endpoint,
                incident_fingerprint=incident.fingerprint,
                rpn_score=incident.rpn.rpn,
                failure_mode_id=incident.failure_mode_id,
                prior_attempts=incident.attempts,
                prior_tiers=list(range(incident.current_tier)),
                escalation_reason=escalation_reason,
                incident_age_seconds=incident_age_seconds,
                prompt_sent=prompt,
                context_summary=context_summary,
            )

        try:
            # Lazy-load ACP client
            if self._acp_client is None:
                from ..acp import GaiusACPClient, ACPConfig

                self._acp_client = GaiusACPClient(
                    ACPConfig(
                        prompt_timeout=self.config.acp_timeout,
                        auto_approve_terminal=False,  # Claude Code needs approval for shell
                    )
                )
                await self._acp_client.connect()

            self._acp_escalations += 1

            # Send to Claude Code
            response = await self._acp_client.prompt(
                message=prompt,
                context={
                    "incident": incident.to_dict(),
                    "last_report": self._last_report.summary() if self._last_report else None,
                },
                timeout=self.config.acp_timeout,
            )

            # Parse response for success indicator and extract details
            success = self._parse_acp_response(response)
            duration_ms = int((time.time() - start_time) * 1000)

            # Extract actions and diagnosis from response
            diagnosis, remediation = self._extract_response_details(response)

            # Record escalation completion with full details
            if self._event_recorder and incident.sequence_id:
                session_id = getattr(self._acp_client, 'session_id', 'unknown')
                await self._event_recorder.record_acp_escalation_completed(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    session_id=str(session_id),
                    result_summary=response[:200] if response else None,
                    duration_ms=duration_ms,
                    success=success,
                    full_response=response,
                    diagnosis=diagnosis,
                    remediation_applied=remediation,
                )

            return HealingResult(
                success=success,
                action="acp_remediation",
                tier=EscalationTier.TIER_2,
                reason=response[:200] if not success else None,
                remote_assessment=response,
            )

        except Exception as e:
            logger.error(f"ACP escalation failed: {e}")
            duration_ms = int((time.time() - start_time) * 1000)

            # Determine failure stage
            failure_stage = "connection"
            if self._acp_client is not None:
                failure_stage = "prompt" if "timeout" not in str(e).lower() else "timeout"

            # Record escalation failure with full context
            if self._event_recorder and incident.sequence_id:
                await self._event_recorder.record_acp_escalation_failed(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    error=str(e),
                    error_code=getattr(e, 'code', None),
                    duration_ms=duration_ms,
                    failure_stage=failure_stage,
                    connection_state="connected" if self._acp_client else "disconnected",
                    retry_recommended=incident.attempts < 5,
                    escalation_path="Manual intervention via /health fix or GitHub issue",
                )

            return HealingResult(
                success=False,
                escalate=True,
                reason=f"ACP escalation failed: {e}",
            )

    def _build_context_summary(self, incident: HealthIncident) -> str:
        """Build a summary of the health context for the incident."""
        parts = [
            f"Incident: {incident.fingerprint}",
            f"Endpoint: {incident.endpoint}",
            f"RPN: {incident.rpn.rpn} (S:{incident.rpn.severity} O:{incident.rpn.occurrence} D:{incident.rpn.detection})",
            f"Tier: {incident.current_tier}",
            f"Attempts: {incident.attempts}",
            f"Status: {incident.status}",
        ]
        if self._last_report:
            parts.append(f"Last health: {self._last_report.summary()}")
        return " | ".join(parts)

    def _build_escalation_reason(self, incident: HealthIncident) -> str:
        """Build a human-readable explanation for why escalation occurred."""
        reasons = []
        if incident.rpn.rpn >= 200:
            reasons.append(f"High RPN score ({incident.rpn.rpn})")
        if incident.attempts >= 3:
            reasons.append(f"Multiple failed attempts ({incident.attempts})")
        if incident.current_tier >= 2:
            reasons.append("Reached tier 2 escalation threshold")

        age_hours = (datetime.now() - incident.created_at).total_seconds() / 3600
        if age_hours > 1:
            reasons.append(f"Incident persisting for {age_hours:.1f}h")

        return "; ".join(reasons) if reasons else "Escalation triggered by tier progression"

    def _extract_response_details(self, response: str) -> tuple[str | None, str | None]:
        """Extract diagnosis and remediation from Claude Code response.

        Args:
            response: Full response from Claude Code

        Returns:
            Tuple of (diagnosis, remediation_applied)
        """
        diagnosis = None
        remediation = None

        response_lower = response.lower()

        # Look for diagnosis patterns
        diagnosis_markers = ["diagnosis:", "root cause:", "issue:", "problem:"]
        for marker in diagnosis_markers:
            if marker in response_lower:
                idx = response_lower.find(marker)
                # Extract until next section or 500 chars
                end_idx = min(idx + 500, len(response))
                for end_marker in ["\n\n", "##", "remediation:", "fix:", "action:"]:
                    next_section = response_lower.find(end_marker, idx + len(marker))
                    if next_section > 0:
                        end_idx = min(end_idx, next_section)
                diagnosis = response[idx:end_idx].strip()
                break

        # Look for remediation patterns
        remediation_markers = ["remediation:", "fix:", "action:", "restarted", "applied"]
        for marker in remediation_markers:
            if marker in response_lower:
                idx = response_lower.find(marker)
                end_idx = min(idx + 300, len(response))
                for end_marker in ["\n\n", "##"]:
                    next_section = response_lower.find(end_marker, idx + len(marker))
                    if next_section > 0:
                        end_idx = min(end_idx, next_section)
                remediation = response[idx:end_idx].strip()
                break

        return diagnosis, remediation

    def _build_acp_prompt(self, incident: HealthIncident) -> str:
        """Build prompt for Claude Code via ACP.

        Args:
            incident: The incident to diagnose

        Returns:
            Prompt string for Claude Code
        """
        return f"""## Health Incident Requiring Diagnosis

**Fingerprint**: `{incident.fingerprint}`
**Endpoint**: {incident.endpoint}
**Failure Mode**: {incident.failure_mode_id}
**RPN Score**: {incident.rpn.rpn} (S:{incident.rpn.severity} × O:{incident.rpn.occurrence} × D:{incident.rpn.detection})
**Escalation Tier**: {EscalationTier(incident.current_tier).name}
**Attempts**: {incident.attempts}

### Instructions

1. Use the Gaius MCP tools to investigate this health issue:
   - `health_check` - Run diagnostics
   - `orchestrator_status` - Check GPU/endpoint status
   - `orchestrator_logs <endpoint>` - View endpoint logs

2. Diagnose the root cause

3. If safe to remediate:
   - Use `orchestrator_restart <endpoint>` for endpoint issues
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

    async def _create_github_issue(self, incident: HealthIncident) -> None:
        """Create GitHub issue for manual incidents.

        Args:
            incident: The incident requiring manual intervention
        """
        if not self.config.github_repo:
            logger.info(
                f"GitHub integration not configured, skipping issue creation "
                f"for {incident.fingerprint}"
            )
            return

        # TODO: Implement GitHub issue creation via PyGitHub or gh CLI
        # For now, just log the intent
        logger.info(
            f"Would create GitHub issue for {incident.fingerprint} "
            f"in {self.config.github_repo}"
        )

    async def _check_recoveries(self, report: HealthReport) -> None:
        """Check if recovering incidents have stabilized.

        Incidents in "recovering" status are checked for sustained health.
        If healthy for recovery_verification_time, they are resolved.

        Also checks "active" incidents for spontaneous recovery (e.g., due to
        ambient workload changes or manual intervention outside the healing loop).

        Args:
            report: Current health report
        """
        resolved = []

        for fingerprint, incident in self._active_incidents.items():
            # Check if the associated check is now passing
            check_passed = self._check_passed_for_incident(report, incident)

            # Handle active incidents that have spontaneously recovered
            if incident.status == "active" and check_passed:
                # Move to recovering status and start verification timer
                incident.status = "recovering"
                self._recovery_start[fingerprint] = datetime.now()
                logger.info(
                    f"Incident {fingerprint} spontaneously recovered, "
                    f"starting verification period"
                )
                continue

            if incident.status != "recovering":
                continue

            if check_passed:
                # Check if recovery period elapsed
                recovery_start = self._recovery_start.get(fingerprint)
                if recovery_start:
                    elapsed = (datetime.now() - recovery_start).total_seconds()
                    if elapsed >= self.config.recovery_verification_time:
                        resolved.append(fingerprint)
            else:
                # Health degraded again
                incident.status = "active"
                self._recovery_start.pop(fingerprint, None)

        # Resolve completed recoveries
        for fingerprint in resolved:
            incident = self._active_incidents.pop(fingerprint)
            self._recovery_start.pop(fingerprint, None)
            self._incidents_resolved += 1

            # Complete event sequence
            if self._event_recorder and incident.sequence_id:
                await self._event_recorder.complete_sequence(
                    sequence_id=incident.sequence_id,
                    endpoint=incident.endpoint,
                    outcome="success",
                    total_attempts=incident.attempts,
                    final_tier=incident.current_tier,
                )

            logger.info(f"Incident resolved: {fingerprint}")

            # Notify callbacks
            for callback in self._on_resolution:
                try:
                    await callback(incident)
                except Exception as e:
                    logger.warning(f"Resolution callback error: {e}")

    def _check_passed_for_incident(
        self,
        report: HealthReport,
        incident: HealthIncident,
    ) -> bool:
        """Check if the health check for an incident is now passing.

        Args:
            report: Current health report
            incident: The incident to check

        Returns:
            True if associated check is passing
        """
        for check in report.checks:
            # Match by endpoint or fingerprint components
            if incident.endpoint in check.name.lower().replace(" ", "_"):
                return check.status == CheckStatus.PASS
            if check.heuristic_id == incident.failure_mode_id:
                return check.status == CheckStatus.PASS

        # If no matching check found, assume passed
        return True

    def _generate_fingerprint(self, check: CheckResult) -> str:
        """Generate deduplication fingerprint for a check result.

        Args:
            check: Health check result

        Returns:
            Fingerprint string (failure_mode_id:endpoint)
        """
        failure_mode = check.heuristic_id or f"UNKNOWN_{check.name[:10].upper()}"
        endpoint = check.details.get("endpoint", check.name.lower().replace(" ", "_"))
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
            "last_report": (
                {
                    "healthy": self._last_report.healthy,
                    "summary": self._last_report.summary(),
                    "passed": self._last_report.passed,
                    "warnings": self._last_report.warnings,
                    "failures": self._last_report.failures,
                }
                if self._last_report else None
            ),
            "config": {
                "poll_interval": self.config.poll_interval,
                "escalate_to_acp": self.config.escalate_to_acp,
                "github_repo": self.config.github_repo,
            },
        }

    async def get_incident_detail(self, fingerprint: str) -> dict[str, Any] | None:
        """Get detailed incident info including ACP history.

        Args:
            fingerprint: Incident fingerprint (failure_mode_id:endpoint)

        Returns:
            Detailed incident dict with healing history, or None if not found
        """
        incident = self._active_incidents.get(fingerprint)
        if not incident:
            return None

        result = incident.to_dict()

        # Add healing event history from database
        if self._event_recorder and incident.sequence_id:
            events = await self._event_recorder.get_sequence_events(incident.sequence_id)
            result["healing_events"] = events

            # Extract ACP-specific events for easy access
            acp_events = [
                e for e in events
                if e["event_type"].startswith("acp_")
            ]
            result["acp_history"] = acp_events

            # Generate human-readable narrative from events
            result["narrative"] = self._generate_incident_narrative(incident, events)

        # Add GitHub issue from database if linked
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    issue_row = await conn.fetchrow(
                        """
                        SELECT issue_number, repo, issue_url, status,
                               created_at, closed_at, recurrence_count
                        FROM github_issues
                        WHERE fingerprint = $1
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        fingerprint,
                    )
                    if issue_row:
                        result["github_issue_detail"] = {
                            "issue_number": issue_row["issue_number"],
                            "repo": issue_row["repo"],
                            "issue_url": issue_row["issue_url"],
                            "status": issue_row["status"],
                            "created_at": issue_row["created_at"].isoformat(),
                            "closed_at": issue_row["closed_at"].isoformat() if issue_row["closed_at"] else None,
                            "recurrence_count": issue_row["recurrence_count"],
                        }
            except Exception as e:
                logger.warning(f"Could not fetch GitHub issue for {fingerprint}: {e}")

        return result

    def _generate_incident_narrative(
        self,
        incident: HealthIncident,
        events: list[dict[str, Any]],
    ) -> str:
        """Generate a human-readable narrative from incident events.

        Args:
            incident: The incident
            events: List of healing events

        Returns:
            Markdown narrative suitable for /health reports
        """
        lines = []
        lines.append(f"### Incident Timeline: {incident.fingerprint}")
        lines.append("")

        # Calculate incident age
        age = datetime.now() - incident.created_at
        age_str = self._format_age(age.total_seconds())
        lines.append(f"**Duration**: {age_str} | **Attempts**: {incident.attempts} | **Current Tier**: {incident.current_tier}")
        lines.append("")

        if not events:
            lines.append("*No healing events recorded yet.*")
            return "\n".join(lines)

        lines.append("**Event Log:**")
        lines.append("")

        for event in events:
            event_type = event.get("event_type", "unknown")
            created_at = event.get("created_at", "")
            payload = event.get("payload", {})

            # Format timestamp
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    ts = dt.strftime("%H:%M:%S")
                except Exception:
                    ts = created_at[:19]
            else:
                ts = "??:??:??"

            # Get narrative from payload or generate one
            narrative = payload.get("narrative", "")
            if not narrative:
                narrative = self._event_to_narrative(event_type, payload)

            # Format based on event type
            if event_type == "sequence_started":
                lines.append(f"- **{ts}** 🚨 Incident detected: {payload.get('issue_type', 'unknown issue')}")
            elif event_type == "tier_entered":
                to_tier = payload.get("to_tier", "?")
                reason = payload.get("reason", "escalation")
                lines.append(f"- **{ts}** ⬆️ Entered tier {to_tier} ({reason})")
            elif event_type == "attempt_started":
                action = payload.get("action", "unknown")
                lines.append(f"- **{ts}** 🔧 Started: {action}")
            elif event_type == "attempt_succeeded":
                action = payload.get("action", "unknown")
                duration = payload.get("duration_ms", 0)
                lines.append(f"- **{ts}** ✅ Succeeded: {action} ({duration}ms)")
            elif event_type == "attempt_failed":
                action = payload.get("action", "unknown")
                reason = payload.get("reason", "")[:50]
                lines.append(f"- **{ts}** ❌ Failed: {action} - {reason}")
            elif event_type == "acp_escalation_started":
                rpn = payload.get("rpn_score", "?")
                prior = payload.get("prior_attempts", 0)
                reason = payload.get("escalation_reason", "")[:80]
                lines.append(f"- **{ts}** 🤖 ACP escalation started (RPN:{rpn}, {prior} prior attempts)")
                if reason:
                    lines.append(f"  - Reason: {reason}")
            elif event_type == "acp_escalation_completed":
                success = "✅" if payload.get("success") else "⚠️"
                duration = payload.get("duration_human", "?")
                lines.append(f"- **{ts}** {success} ACP completed ({duration})")
                if payload.get("diagnosis"):
                    lines.append(f"  - Diagnosis: {payload['diagnosis'][:100]}...")
                if payload.get("remediation_applied"):
                    lines.append(f"  - Remediation: {payload['remediation_applied'][:100]}...")
            elif event_type == "acp_escalation_failed":
                stage = payload.get("failure_stage", "unknown")
                error = payload.get("error", "")[:60]
                lines.append(f"- **{ts}** 💥 ACP failed at {stage}: {error}")
                if payload.get("escalation_path"):
                    lines.append(f"  - Next: {payload['escalation_path']}")
            elif event_type == "sequence_completed":
                outcome = payload.get("outcome", "unknown")
                total = payload.get("total_attempts", 0)
                lines.append(f"- **{ts}** 🏁 Sequence completed: {outcome} after {total} attempts")
            else:
                # Generic format for other events
                lines.append(f"- **{ts}** {event_type}: {narrative or 'no details'}")

        return "\n".join(lines)

    def _event_to_narrative(self, event_type: str, payload: dict[str, Any]) -> str:
        """Convert event to a narrative string when not provided in payload."""
        if event_type == "cooldown_started":
            secs = payload.get("cooldown_seconds", "?")
            return f"Cooldown started for {secs}s"
        elif event_type == "cooldown_cleared":
            return "Cooldown cleared"
        elif event_type == "circuit_breaker_tripped":
            return f"Circuit breaker tripped after {payload.get('failure_count', '?')} failures"
        elif event_type == "recovery_timer_started":
            return "Recovery timer started"
        else:
            return ""

    def _format_age(self, seconds: float) -> str:
        """Format age in human-readable form."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}d {hours}h"

    async def get_acp_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent ACP escalation history from database.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of ACP escalation events
        """
        if not self._event_recorder:
            return []

        pool = await self._get_pool()
        if not pool:
            return []

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT event_id, event_type, endpoint, sequence_id,
                           payload, created_at, failure_mode_id
                    FROM healing_events
                    WHERE event_type LIKE 'acp_%'
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )

                return [
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "endpoint": row["endpoint"],
                        "sequence_id": str(row["sequence_id"]),
                        "payload": row["payload"],
                        "created_at": row["created_at"].isoformat(),
                        "failure_mode_id": row["failure_mode_id"],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get ACP history: {e}")
            return []

    async def force_check(self) -> HealthReport:
        """Force an immediate health check.

        Bypasses the poll interval for on-demand checking.

        Returns:
            HealthReport with current status
        """
        report = await self._run_health_check()
        self._last_report = report
        self._poll_count += 1
        self._last_poll_at = datetime.now()

        # Process but don't start healing loop
        await self._process_failures(report)
        await self._check_recoveries(report)

        return report

    def get_incident(self, fingerprint: str) -> HealthIncident | None:
        """Get incident by fingerprint.

        Args:
            fingerprint: Incident fingerprint (failure_mode_id:endpoint)

        Returns:
            HealthIncident if found, None otherwise
        """
        return self._active_incidents.get(fingerprint)


# Module-level singleton
_health_observer: HealthObserver | None = None


def get_health_observer(config: ObserverConfig | None = None) -> HealthObserver:
    """Get or create HealthObserver singleton.

    Args:
        config: Optional config (only used on first call)

    Returns:
        HealthObserver instance
    """
    global _health_observer
    if _health_observer is None:
        _health_observer = HealthObserver(config)
    return _health_observer
