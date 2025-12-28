"""HealthObserverService for autonomous health monitoring in gaius-engine.

Daemon that runs continuous health monitoring, FMEA-based incident detection,
and autonomous self-healing with ACP escalation for complex issues.

This service runs IN THE ENGINE (not client layer) ensuring:
- Health monitoring persists across MCP/TUI sessions
- Self-healing works when only gaius-engine is running via devenv up
- Single source of truth for health state
- Engine can perform autonomous healing even when no clients are connected

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
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Awaitable
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from ..config import EngineConfig

logger = logging.getLogger(__name__)


@dataclass
class ObserverConfig:
    """Configuration for HealthObserverService.

    Attributes:
        enabled: Enable/disable daemon
        poll_interval: Seconds between health checks (default 30)
        burst_interval: Faster polling when healing in progress (default 5)
        backoff_interval: Slower polling after errors (default 120)
        escalate_to_acp: Enable ACP escalation for complex issues
        acp_timeout: Timeout for ACP prompts in seconds
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
    acp_timeout: float = 300.0  # 5 minutes

    # GitHub integration - internal repo for health tracking
    github_repo: str = "zndx/gaius-internal"

    # KB and FMEA
    kb_root: str = "build/dev"

    # Recovery verification
    recovery_verification_time: float = 300.0  # 5 minutes

    # Cadence controls (prevent runaway remediation)
    min_interval_between_restarts: int = 300  # 5 minutes
    max_restarts_per_hour: int = 3


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
        }


class HealthObserverService:
    """Engine service for autonomous health monitoring and remediation.

    Runs as part of gaius-engine daemon, ensuring health monitoring
    persists regardless of client connections.

    Features:
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

        # Callbacks for external notification
        self._on_incident: list[Callable[[HealthIncident], Awaitable[None]]] = []
        self._on_resolution: list[Callable[[HealthIncident], Awaitable[None]]] = []

        logger.info("HealthObserverService initialized")

    def set_services(
        self,
        orchestrator: Any = None,
        health: Any = None,
    ) -> None:
        """Set service references after initialization.

        Called by engine during startup phase.

        Args:
            orchestrator: OrchestratorService instance
            health: HealthService instance
        """
        if orchestrator:
            self._orchestrator = orchestrator
        if health:
            self._health_service = health

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
        during autonomous startup.
        """
        if self._running:
            logger.warning("HealthObserverService already running")
            return

        if not self.config.enabled:
            logger.info("HealthObserverService disabled by config")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"HealthObserverService started (poll_interval={self.config.poll_interval}s, "
            f"acp_enabled={self.config.escalate_to_acp})"
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
        """Run comprehensive health check.

        Uses HealthService metrics and OrchestratorService status.

        Returns:
            Health report dict with all check results
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "healthy": True,
            "checks": [],
        }

        # Get GPU health from HealthService
        if self._health_service:
            try:
                health_data = self._health_service.get_health()
                report["gpus"] = health_data.get("gpus", [])

                # Check for GPU issues
                for gpu in health_data.get("gpus", []):
                    if not gpu.get("is_healthy", True):
                        report["healthy"] = False
                        report["checks"].append({
                            "name": f"gpu_{gpu['gpu_id']}_health",
                            "status": "FAIL",
                            "details": gpu,
                            "heuristic_id": "GPU_001",
                        })
            except Exception as e:
                logger.debug(f"Health service query failed: {e}")

        # Get endpoint health from OrchestratorService
        if self._orchestrator:
            try:
                status = self._orchestrator.get_status()
                endpoints = status.get("endpoints", {})
                report["endpoints"] = endpoints

                # Check for endpoint issues
                for alias, ep_info in endpoints.items():
                    ep_status = ep_info.get("status", "unknown")
                    if ep_status in ("unhealthy", "error", "failed"):
                        report["healthy"] = False
                        report["checks"].append({
                            "name": f"endpoint_{alias}",
                            "status": "FAIL",
                            "details": {
                                "endpoint": alias,
                                **ep_info,
                            },
                            "heuristic_id": "VLLM_001",
                        })
                    elif ep_status == "starting":
                        # Starting is warning, not failure
                        report["checks"].append({
                            "name": f"endpoint_{alias}",
                            "status": "WARN",
                            "details": {
                                "endpoint": alias,
                                **ep_info,
                            },
                            "heuristic_id": None,
                        })
            except Exception as e:
                logger.debug(f"Orchestrator status query failed: {e}")

        return report

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

        Args:
            incident: The incident to remediate
        """
        incident.attempts += 1
        incident.status = "healing"

        tier = incident.current_tier

        logger.info(
            f"Attempting remediation for {incident.fingerprint} "
            f"(attempt {incident.attempts}, tier {tier})"
        )

        try:
            if tier == 0:
                success = await self._tier0_remediate(incident)
            elif tier == 1:
                success = await self._tier1_remediate(incident)
            elif tier == 2:
                success = await self._tier2_remediate_acp(incident)
            else:  # tier >= 3 = MANUAL
                await self._create_github_issue(incident)
                incident.status = "manual_required"
                return

            if success:
                incident.status = "recovering"
                self._recovery_start[incident.fingerprint] = datetime.now()
                logger.info(f"Remediation succeeded for {incident.fingerprint}")
            else:
                # Escalate to next tier
                incident.current_tier = min(incident.current_tier + 1, 3)
                logger.info(
                    f"Escalating {incident.fingerprint} to tier {incident.current_tier}"
                )
                # Retry with new tier
                await self._attempt_remediation(incident)

        except Exception as e:
            logger.error(f"Remediation error for {incident.fingerprint}: {e}")

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
                            prompt_timeout=self.config.acp_timeout,
                            auto_approve_terminal=False,
                        )
                    )
                    await self._acp_client.connect()

            self._acp_escalations += 1

            # Build prompt for Claude Code
            prompt = self._build_acp_prompt(incident)

            # Send to Claude Code
            response = await self._acp_client.prompt(
                message=prompt,
                context={
                    "incident": incident.to_dict(),
                    "last_report": self._last_report,
                },
                timeout=self.config.acp_timeout,
            )

            # Parse response for success indicator
            return self._parse_acp_response(response)

        except Exception as e:
            logger.error(f"ACP escalation failed: {e}")
            return False

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
**RPN Score**: {incident.rpn_score} (S:{incident.rpn_severity} x O:{incident.rpn_occurrence} x D:{incident.rpn_detection})
**Escalation Tier**: {incident.current_tier}
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

        # TODO: Implement GitHub issue creation via gh CLI
        logger.info(
            f"Would create GitHub issue for {incident.fingerprint} "
            f"in {self.config.github_repo}"
        )

    async def _check_recoveries(self, report: dict[str, Any]) -> None:
        """Check if recovering incidents have stabilized.

        Incidents in "recovering" status are checked for sustained health.
        If healthy for recovery_verification_time, they are resolved.

        Args:
            report: Current health report
        """
        resolved = []

        for fingerprint, incident in self._active_incidents.items():
            if incident.status != "recovering":
                continue

            # Check if the associated check is now passing
            check_passed = self._check_passed_for_incident(report, incident)

            if check_passed:
                recovery_start = self._recovery_start.get(fingerprint)
                if recovery_start:
                    elapsed = (datetime.now() - recovery_start).total_seconds()
                    if elapsed >= self.config.recovery_verification_time:
                        resolved.append(fingerprint)
            else:
                incident.status = "active"
                self._recovery_start.pop(fingerprint, None)

        # Resolve completed recoveries
        for fingerprint in resolved:
            incident = self._active_incidents.pop(fingerprint)
            self._recovery_start.pop(fingerprint, None)
            self._incidents_resolved += 1

            logger.info(f"Incident resolved: {fingerprint}")

            for callback in self._on_resolution:
                try:
                    await callback(incident)
                except Exception as e:
                    logger.warning(f"Resolution callback error: {e}")

    def _check_passed_for_incident(
        self,
        report: dict[str, Any],
        incident: HealthIncident,
    ) -> bool:
        """Check if the health check for an incident is now passing.

        Args:
            report: Current health report
            incident: The incident to check

        Returns:
            True if associated check is passing
        """
        for check in report.get("checks", []):
            if incident.endpoint in check.get("name", "").lower():
                return check.get("status") != "FAIL"
            if check.get("heuristic_id") == incident.failure_mode_id:
                return check.get("status") != "FAIL"

        # If no matching check found, assume passed
        return True

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

        Returns:
            Health report dict with current status
        """
        report = await self._run_health_check()
        self._last_report = report
        self._poll_count += 1
        self._last_poll_at = datetime.now()

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
        """Whether service is running."""
        return self._running
