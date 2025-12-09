"""Tiered Self-Healing System for Gaius.

Provides a 3-tier approach to system recovery:
- Tier 0: Procedural restart (code-only, no agents)
- Tier 1: Local agent intervention (using healthy endpoints)
- Tier 2: Remote API escalation (prepared remediation paths)

Usage:
    from gaius.health.self_healing import SelfHealingCoordinator, HealthIssue

    coordinator = SelfHealingCoordinator(orchestrator_service, config)
    result = await coordinator.handle_health_issue(
        HealthIssue(endpoint="reasoning", issue_type="unhealthy", ...)
    )
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional
import asyncio
import logging

if TYPE_CHECKING:
    from gaius.engine.services.orchestrator_service import OrchestratorService
    from gaius.inference.recovery import RecoveryManager

logger = logging.getLogger(__name__)


class HealingTierType(Enum):
    """Healing tier identifiers."""
    PROCEDURAL = 0
    LOCAL_AGENT = 1
    REMOTE_ESCALATION = 2


@dataclass
class HealthIssue:
    """Represents a detected health issue requiring intervention.

    Attributes:
        endpoint: The affected endpoint name
        issue_type: Type of issue (unhealthy, failed, timeout, etc.)
        error_message: Optional error details
        check_name: Name of the health check that detected this
        severity: Issue severity (critical, warning, info)
        detected_at: When the issue was detected
        context: Additional context about the issue
    """
    endpoint: str
    issue_type: str
    error_message: str | None = None
    check_name: str | None = None
    severity: str = "warning"
    detected_at: datetime = field(default_factory=datetime.now)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "endpoint": self.endpoint,
            "issue_type": self.issue_type,
            "error_message": self.error_message,
            "check_name": self.check_name,
            "severity": self.severity,
            "detected_at": self.detected_at.isoformat(),
            "context": self.context,
        }

    @classmethod
    def from_check(cls, check: Any) -> "HealthIssue":
        """Create HealthIssue from a HealthCheck result."""
        return cls(
            endpoint=check.result.details.get("endpoint", "unknown"),
            issue_type=check.result.status.value,
            error_message=check.result.message,
            check_name=check.name,
            severity="critical" if check.result.status.value == "fail" else "warning",
            context=check.result.details,
        )


@dataclass
class EscalationRecord:
    """Record of an escalation event."""
    tier: HealingTierType
    action: str
    timestamp: datetime
    success: bool
    reason: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tier": self.tier.name,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
        }


@dataclass
class HealingState:
    """Tracks healing state for an endpoint.

    Attributes:
        endpoint: The endpoint being healed
        current_tier: Current tier (0, 1, or 2)
        attempts_at_tier: Number of attempts at current tier
        last_attempt: When last healing was attempted
        cooldown_until: Don't retry until this time
        escalation_history: History of escalation attempts
    """
    endpoint: str
    current_tier: int = 0
    attempts_at_tier: int = 0
    last_attempt: datetime | None = None
    cooldown_until: datetime | None = None
    escalation_history: list[EscalationRecord] = field(default_factory=list)

    def record_attempt(
        self,
        tier: HealingTierType,
        action: str,
        success: bool,
        reason: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Record a healing attempt."""
        self.escalation_history.append(EscalationRecord(
            tier=tier,
            action=action,
            timestamp=datetime.now(),
            success=success,
            reason=reason,
            duration_ms=duration_ms,
        ))
        self.last_attempt = datetime.now()


@dataclass
class HealingResult:
    """Result of a healing attempt.

    Attributes:
        success: Whether healing succeeded
        action: Action taken (e.g., "SOFT_RESET", "clear_cuda_cache")
        tier: Which tier handled this
        reason: Explanation of result
        escalate: Whether to escalate to next tier
        deferred: Whether healing was deferred (e.g., cooldown)
        agent_reasoning: Reasoning from local agent (Tier 1)
        remote_assessment: Assessment from remote API (Tier 2)
        remote_confidence: Confidence score from remote API
    """
    success: bool = False
    action: str = ""
    tier: HealingTierType | None = None
    reason: str | None = None
    escalate: bool = False
    deferred: bool = False
    agent_reasoning: str | None = None
    remote_assessment: str | None = None
    remote_confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "action": self.action,
            "tier": self.tier.name if self.tier else None,
            "reason": self.reason,
            "escalate": self.escalate,
            "deferred": self.deferred,
            "agent_reasoning": self.agent_reasoning,
            "remote_assessment": self.remote_assessment,
            "remote_confidence": self.remote_confidence,
        }


class HealingTier(ABC):
    """Abstract base class for healing tiers."""

    @property
    @abstractmethod
    def tier_type(self) -> HealingTierType:
        """Return the tier type."""
        pass

    @abstractmethod
    async def attempt_healing(
        self,
        issue: HealthIssue,
        state: HealingState,
    ) -> HealingResult:
        """Attempt to heal the issue.

        Args:
            issue: The health issue to address
            state: Current healing state for this endpoint

        Returns:
            HealingResult with outcome
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this tier is currently available."""
        pass


class Tier0Procedural(HealingTier):
    """Tier 0: Procedural restart - no agents, just code.

    Uses existing RecoveryManager for restart attempts.
    Enforces circuit breaker pattern to prevent crash loops.

    Note: Works with both OrchestratorService (engine-side) and
    OrchestratorProxy (client-side). The interface methods used are:
    - stop_endpoint(name)
    - start_endpoint(name)
    - get_endpoint_status(name) OR get_status()
    """

    MAX_ATTEMPTS = 3
    COOLDOWN_SECONDS = 60

    def __init__(
        self,
        orchestrator_service: Any,  # OrchestratorService or OrchestratorProxy
        max_attempts: int = 3,
        cooldown_seconds: int = 60,
    ):
        """Initialize Tier 0.

        Args:
            orchestrator_service: Orchestrator for endpoint management
            max_attempts: Max attempts before escalating
            cooldown_seconds: Cooldown between attempts
        """
        self._orchestrator = orchestrator_service
        self.MAX_ATTEMPTS = max_attempts
        self.COOLDOWN_SECONDS = cooldown_seconds

    @property
    def tier_type(self) -> HealingTierType:
        return HealingTierType.PROCEDURAL

    def is_available(self) -> bool:
        """Tier 0 is always available."""
        return True

    async def attempt_healing(
        self,
        issue: HealthIssue,
        state: HealingState,
    ) -> HealingResult:
        """Attempt procedural restart.

        Args:
            issue: The health issue
            state: Current healing state

        Returns:
            HealingResult
        """
        start_time = datetime.now()

        # Check if we've exhausted attempts at this tier
        if state.attempts_at_tier >= self.MAX_ATTEMPTS:
            return HealingResult(
                success=False,
                escalate=True,
                tier=self.tier_type,
                reason=f"Max procedural attempts ({self.MAX_ATTEMPTS}) exceeded",
            )

        state.attempts_at_tier += 1
        attempt_num = state.attempts_at_tier

        logger.info(
            f"Tier 0 procedural healing for {issue.endpoint} "
            f"(attempt {attempt_num}/{self.MAX_ATTEMPTS})"
        )

        try:
            # Determine recovery action based on issue type and attempt count
            if attempt_num == 1:
                # First attempt: soft reset (brief cooldown)
                action = "SOFT_RESET"
                success = await self._soft_reset(issue.endpoint)
            elif attempt_num == 2:
                # Second attempt: warm restart
                action = "WARM_RESTART"
                success = await self._warm_restart(issue.endpoint)
            else:
                # Third attempt: warm restart with longer cooldown
                action = "WARM_RESTART_EXTENDED"
                success = await self._warm_restart(issue.endpoint, cooldown=10)

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Record attempt
            state.record_attempt(
                tier=self.tier_type,
                action=action,
                success=success,
                duration_ms=duration_ms,
            )

            if success:
                logger.info(
                    f"Tier 0 {action} succeeded for {issue.endpoint} "
                    f"in {duration_ms}ms"
                )
                return HealingResult(
                    success=True,
                    action=action,
                    tier=self.tier_type,
                )
            else:
                # Set cooldown before next attempt
                state.cooldown_until = datetime.now() + timedelta(
                    seconds=self.COOLDOWN_SECONDS
                )
                logger.warning(
                    f"Tier 0 {action} failed for {issue.endpoint}, "
                    f"cooldown until {state.cooldown_until}"
                )
                return HealingResult(
                    success=False,
                    action=action,
                    tier=self.tier_type,
                    reason="Recovery action failed",
                    escalate=(state.attempts_at_tier >= self.MAX_ATTEMPTS),
                )

        except Exception as e:
            logger.error(f"Tier 0 healing error for {issue.endpoint}: {e}")
            return HealingResult(
                success=False,
                tier=self.tier_type,
                reason=str(e),
                escalate=True,
            )

    async def _soft_reset(self, endpoint: str) -> bool:
        """Soft reset: brief cooldown and health check.

        Args:
            endpoint: Endpoint to reset

        Returns:
            True if endpoint is healthy after cooldown
        """
        logger.info(f"Soft reset for {endpoint}: 5s cooldown")

        # Brief cooldown
        await asyncio.sleep(5)

        # Check if endpoint recovered - handle both service and proxy interface
        status = await self._get_endpoint_status(endpoint)
        if status is None:
            return False

        # Handle both dict (proxy) and object (service) status
        if isinstance(status, dict):
            return status.get("status") == "healthy"
        else:
            return getattr(status, "status", None) == "healthy"

    async def _get_endpoint_status(self, endpoint: str) -> Any:
        """Get endpoint status, handling both service and proxy interfaces."""
        # Prefer async get_endpoint_status if available
        if hasattr(self._orchestrator, "get_endpoint_status"):
            result = self._orchestrator.get_endpoint_status(endpoint)
            # Handle async method
            if asyncio.iscoroutine(result):
                return await result
            return result
        # Prefer async _get_status_async over sync get_status
        elif hasattr(self._orchestrator, "_get_status_async"):
            status = await self._orchestrator._get_status_async()
            endpoints = status.get("endpoints", [])
            # Handle list format: [{"name": "reasoning", ...}, ...]
            if isinstance(endpoints, list):
                for ep in endpoints:
                    if isinstance(ep, dict) and ep.get("name") == endpoint:
                        return ep
                return None
            # Handle dict format: {"reasoning": {...}, ...}
            return endpoints.get(endpoint)
        return None

    async def _warm_restart(self, endpoint: str, cooldown: int = 2) -> bool:
        """Warm restart: stop and restart endpoint.

        Args:
            endpoint: Endpoint to restart
            cooldown: Seconds to wait between stop and start

        Returns:
            True if restart succeeded
        """
        logger.info(f"Warm restart for {endpoint}: {cooldown}s cooldown")

        # Stop the endpoint
        result = self._orchestrator.stop_endpoint(endpoint)
        if asyncio.iscoroutine(result):
            await result

        # Cooldown
        await asyncio.sleep(cooldown)

        # Restart
        try:
            result = self._orchestrator.start_endpoint(endpoint)
            if asyncio.iscoroutine(result):
                result = await result

            # Handle both dict (proxy returns bool/dict) and object (service returns EndpointStatus)
            if isinstance(result, bool):
                return result
            elif isinstance(result, dict):
                return result.get("status") == "healthy"
            else:
                return getattr(result, "status", None) == "healthy"
        except Exception as e:
            logger.error(f"Warm restart failed for {endpoint}: {e}")
            return False


class Tier1LocalAgent(HealingTier):
    """Tier 1: Local agent intervention using healthy endpoints.

    Runs a constrained observation agent that can suggest actions
    from a pre-approved allowlist.

    Note: Works with both OrchestratorService and OrchestratorProxy.
    """

    ALLOWED_ACTIONS = [
        "clear_cuda_cache",
        "kill_orphan_processes",
        "adjust_batch_size",
        "restart_with_reduced_memory",
        "trigger_reconciliation",
    ]

    def __init__(
        self,
        orchestrator_service: Any,  # OrchestratorService or OrchestratorProxy
        allowed_actions: list[str] | None = None,
        required_healthy_endpoints: int = 1,
    ):
        """Initialize Tier 1.

        Args:
            orchestrator_service: Orchestrator for endpoint management
            allowed_actions: Override default allowed actions
            required_healthy_endpoints: Min healthy endpoints needed
        """
        self._orchestrator = orchestrator_service
        if allowed_actions:
            self.ALLOWED_ACTIONS = allowed_actions
        self._required_healthy = required_healthy_endpoints

    @property
    def tier_type(self) -> HealingTierType:
        return HealingTierType.LOCAL_AGENT

    def is_available(self) -> bool:
        """Check if we have healthy endpoints for local agent."""
        healthy = self._get_healthy_endpoints()
        return len(healthy) >= self._required_healthy

    def _get_healthy_endpoints(self) -> list[str]:
        """Get list of healthy endpoint names (sync, for availability check only)."""
        # For availability check, we try cached status if possible
        # This is called from is_available() which is sync
        # Use a simple sync check that doesn't require async
        try:
            if hasattr(self._orchestrator, "_cached_status"):
                status = self._orchestrator._cached_status
                if status:
                    endpoints = status.get("endpoints", [])
                    # Handle list format: [{"name": "reasoning", "status": "healthy"}, ...]
                    if isinstance(endpoints, list):
                        return [
                            ep.get("name") for ep in endpoints
                            if isinstance(ep, dict) and ep.get("status") == "healthy"
                        ]
                    # Handle dict format: {"reasoning": {...}, ...}
                    return [
                        name for name, ep in endpoints.items()
                        if isinstance(ep, dict) and ep.get("status") == "healthy"
                    ]
        except Exception:
            pass
        # Fallback: assume at least tier is available but may fail at execution
        return ["_unknown_"]

    async def _get_healthy_endpoints_async(self) -> list[str]:
        """Get list of healthy endpoint names (async)."""
        # Handle both service (get_all_endpoint_status) and proxy (_get_status_async) interfaces
        if hasattr(self._orchestrator, "get_all_endpoint_status"):
            all_status = self._orchestrator.get_all_endpoint_status()
            return [
                name for name, status in all_status.items()
                if getattr(status, "status", None) == "healthy"
            ]
        elif hasattr(self._orchestrator, "_get_status_async"):
            status = await self._orchestrator._get_status_async()
            # Cache for sync check
            self._orchestrator._cached_status = status
            endpoints = status.get("endpoints", [])
            # Handle list format: [{"name": "reasoning", "status": "healthy"}, ...]
            if isinstance(endpoints, list):
                return [
                    ep.get("name") for ep in endpoints
                    if isinstance(ep, dict) and ep.get("status") == "healthy"
                ]
            # Handle dict format: {"reasoning": {...}, ...}
            return [
                name for name, ep in endpoints.items()
                if isinstance(ep, dict) and ep.get("status") == "healthy"
            ]
        return []

    async def attempt_healing(
        self,
        issue: HealthIssue,
        state: HealingState,
    ) -> HealingResult:
        """Attempt local agent intervention.

        Args:
            issue: The health issue
            state: Current healing state

        Returns:
            HealingResult
        """
        start_time = datetime.now()

        # Check for healthy endpoints (use async version)
        healthy = await self._get_healthy_endpoints_async()
        if not healthy:
            logger.info(
                "Tier 1 skipped: no healthy endpoints for local agent"
            )
            return HealingResult(
                success=False,
                escalate=True,
                tier=self.tier_type,
                reason="No healthy endpoints for local agent",
            )

        state.attempts_at_tier += 1

        logger.info(
            f"Tier 1 local agent healing for {issue.endpoint} "
            f"using endpoint {healthy[0]}"
        )

        try:
            # Gather diagnostic context
            context = await self._gather_diagnostic_context(issue)

            # Run observation agent
            observation = await self._run_observation_agent(healthy[0], context)

            # Validate suggested action
            if observation.get("suggested_action") not in self.ALLOWED_ACTIONS:
                suggested = observation.get("suggested_action", "none")
                logger.warning(
                    f"Tier 1 agent suggested disallowed action: {suggested}"
                )
                return HealingResult(
                    success=False,
                    escalate=True,
                    tier=self.tier_type,
                    reason=f"Agent suggested disallowed action: {suggested}",
                    agent_reasoning=observation.get("reasoning"),
                )

            # Execute allowed action
            action = observation["suggested_action"]
            success = await self._execute_action(action, issue)

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            state.record_attempt(
                tier=self.tier_type,
                action=action,
                success=success,
                reason=observation.get("reasoning"),
                duration_ms=duration_ms,
            )

            return HealingResult(
                success=success,
                action=action,
                tier=self.tier_type,
                agent_reasoning=observation.get("reasoning"),
                escalate=not success,
            )

        except Exception as e:
            logger.error(f"Tier 1 local agent error: {e}")
            return HealingResult(
                success=False,
                tier=self.tier_type,
                reason=str(e),
                escalate=True,
            )

    async def _gather_diagnostic_context(self, issue: HealthIssue) -> dict:
        """Gather logs, metrics, state for agent analysis."""
        context = {
            "health_issue": issue.to_dict(),
        }

        # Get logs - handle both service and proxy interface
        try:
            if hasattr(self._orchestrator, "get_endpoint_logs"):
                context["recent_logs"] = self._orchestrator.get_endpoint_logs(
                    issue.endpoint, lines=100
                )
            elif hasattr(self._orchestrator, "get_logs"):
                context["recent_logs"] = self._orchestrator.get_logs(
                    issue.endpoint, lines=100
                )
            else:
                context["recent_logs"] = []
        except Exception:
            context["recent_logs"] = []

        # Add GPU health if available
        try:
            if hasattr(self._orchestrator, "get_gpu_utilization"):
                gpu_util = self._orchestrator.get_gpu_utilization()
                context["gpu_utilization"] = gpu_util
        except Exception:
            pass

        # Add actual state discovery if available (service only)
        try:
            if hasattr(self._orchestrator, "discover_actual_state"):
                actual_state = await self._orchestrator.discover_actual_state()
                context["actual_state"] = actual_state
        except Exception:
            pass

        return context

    async def _run_observation_agent(
        self,
        endpoint: str,
        context: dict,
    ) -> dict:
        """Run observation agent to analyze issue and suggest action.

        Args:
            endpoint: Healthy endpoint to use for inference
            context: Diagnostic context

        Returns:
            Dict with 'suggested_action' and 'reasoning'
        """
        # For now, use simple heuristics as placeholder
        # TODO: Integrate with actual LLM inference via backend router
        issue = context.get("health_issue", {})
        logs = context.get("recent_logs", [])

        # Simple heuristic-based action selection
        issue_type = issue.get("issue_type", "")
        error_msg = issue.get("error_message", "") or ""

        # Check for OOM indicators
        if "out of memory" in error_msg.lower() or "OOM" in error_msg:
            return {
                "suggested_action": "restart_with_reduced_memory",
                "reasoning": "Error indicates out-of-memory condition",
            }

        # Check for orphan processes
        actual_state = context.get("actual_state", {})
        if len(actual_state) > len(self._get_healthy_endpoints()):
            return {
                "suggested_action": "kill_orphan_processes",
                "reasoning": "Detected orphan processes consuming resources",
            }

        # Check for CUDA errors in logs
        log_text = " ".join(logs)
        if "cuda" in log_text.lower() and "error" in log_text.lower():
            return {
                "suggested_action": "clear_cuda_cache",
                "reasoning": "CUDA errors detected in logs",
            }

        # Default: trigger reconciliation
        return {
            "suggested_action": "trigger_reconciliation",
            "reasoning": "General health issue, reconciling state",
        }

    async def _execute_action(self, action: str, issue: HealthIssue) -> bool:
        """Execute an allowed action.

        Args:
            action: Action name from ALLOWED_ACTIONS
            issue: The health issue

        Returns:
            True if action succeeded
        """
        logger.info(f"Tier 1 executing action: {action}")

        if action == "clear_cuda_cache":
            return await self._clear_cuda_cache()
        elif action == "kill_orphan_processes":
            # Handle both service and proxy interface
            if hasattr(self._orchestrator, "cleanup_stale_processes"):
                result = await self._orchestrator.cleanup_stale_processes()
                if isinstance(result, dict):
                    return result.get("processes_killed", 0) > 0 or result.get("processes_found", 0) == 0
                return result.processes_killed > 0 or result.processes_found == 0
            return False
        elif action == "adjust_batch_size":
            # TODO: Implement batch size adjustment
            return False
        elif action == "restart_with_reduced_memory":
            # TODO: Implement reduced memory restart
            return await self._restart_reduced_memory(issue.endpoint)
        elif action == "trigger_reconciliation":
            if hasattr(self._orchestrator, "reconcile_state"):
                result = await self._orchestrator.reconcile_state()
                return len(result.get("errors", [])) == 0
            return False
        else:
            logger.warning(f"Unknown action: {action}")
            return False

    async def _clear_cuda_cache(self) -> bool:
        """Clear CUDA cache to free GPU memory."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("Cleared CUDA cache")
                return True
        except ImportError:
            logger.debug("torch not available for CUDA cache clearing")
        return False

    async def _restart_reduced_memory(self, endpoint: str) -> bool:
        """Restart endpoint with reduced memory settings."""
        # Stop endpoint
        result = self._orchestrator.stop_endpoint(endpoint)
        if asyncio.iscoroutine(result):
            await result
        await asyncio.sleep(5)

        # TODO: Modify config to reduce memory, then restart
        # For now, just do regular restart
        try:
            result = self._orchestrator.start_endpoint(endpoint)
            if asyncio.iscoroutine(result):
                result = await result
            # Handle both bool and dict/object response
            if isinstance(result, bool):
                return result
            elif isinstance(result, dict):
                return result.get("status") == "healthy"
            return getattr(result, "status", None) == "healthy"
        except Exception as e:
            logger.error(f"Reduced memory restart failed: {e}")
            return False


class Tier2RemoteEscalation(HealingTier):
    """Tier 2: Remote API escalation with prepared remediation paths.

    Sends structured assessment to remote API (xAI Grok or Anthropic)
    and executes only pre-defined remediation codes - no ad-hoc actions.

    Note: Works with both OrchestratorService and OrchestratorProxy.
    """

    def __init__(
        self,
        orchestrator_service: Any,  # OrchestratorService or OrchestratorProxy
        api_provider: str = "xai",
        budget_limit_daily: int = 50,
        enabled: bool = True,
    ):
        """Initialize Tier 2.

        Args:
            orchestrator_service: Orchestrator for endpoint management
            api_provider: API to use ("xai" or "anthropic")
            budget_limit_daily: Max API calls per day
            enabled: Whether Tier 2 is enabled
        """
        self._orchestrator = orchestrator_service
        self._api_provider = api_provider
        self._budget_limit = budget_limit_daily
        self._enabled = enabled
        self._daily_calls = 0
        self._last_reset_date = datetime.now().date()

        # Pre-defined remediation paths - no ad-hoc code execution
        self.REMEDIATION_PATHS: dict[str, Callable] = {
            "COLD_RESTART": self._cold_restart,
            "FULL_CLEANUP": self._full_cleanup,
            "RECONCILE_STATE": self._reconcile_state,
            "REDUCE_TENSOR_PARALLEL": self._reduce_tensor_parallel,
            "FAILOVER_MANUAL": self._failover_manual,
        }

    @property
    def tier_type(self) -> HealingTierType:
        return HealingTierType.REMOTE_ESCALATION

    def is_available(self) -> bool:
        """Check if Tier 2 is available (enabled and within budget)."""
        self._maybe_reset_daily_counter()
        return self._enabled and self._daily_calls < self._budget_limit

    def _maybe_reset_daily_counter(self) -> None:
        """Reset daily call counter if new day."""
        today = datetime.now().date()
        if today > self._last_reset_date:
            self._daily_calls = 0
            self._last_reset_date = today

    async def attempt_healing(
        self,
        issue: HealthIssue,
        state: HealingState,
    ) -> HealingResult:
        """Attempt remote API escalation.

        Args:
            issue: The health issue
            state: Current healing state

        Returns:
            HealingResult
        """
        start_time = datetime.now()

        if not self.is_available():
            return HealingResult(
                success=False,
                tier=self.tier_type,
                reason="Tier 2 not available (disabled or budget exhausted)",
            )

        state.attempts_at_tier += 1
        self._daily_calls += 1

        logger.info(
            f"Tier 2 remote escalation for {issue.endpoint} "
            f"(daily calls: {self._daily_calls}/{self._budget_limit})"
        )

        try:
            # Build structured assessment request
            request = await self._build_assessment_request(issue, state)

            # Call remote API
            response = await self._call_remote_api(request)

            # Validate response contains known remediation code
            remediation_code = response.get("remediation_code")
            if remediation_code not in self.REMEDIATION_PATHS:
                logger.warning(
                    f"Remote API suggested unknown remediation: {remediation_code}"
                )
                return HealingResult(
                    success=False,
                    tier=self.tier_type,
                    reason=f"Unknown remediation code: {remediation_code}",
                    remote_assessment=response.get("assessment"),
                    remote_confidence=response.get("confidence"),
                )

            # Execute prepared remediation
            action_fn = self.REMEDIATION_PATHS[remediation_code]
            success = await action_fn(issue.endpoint)

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            state.record_attempt(
                tier=self.tier_type,
                action=remediation_code,
                success=success,
                reason=response.get("assessment"),
                duration_ms=duration_ms,
            )

            return HealingResult(
                success=success,
                action=remediation_code,
                tier=self.tier_type,
                remote_assessment=response.get("assessment"),
                remote_confidence=response.get("confidence"),
            )

        except Exception as e:
            logger.error(f"Tier 2 remote escalation error: {e}")
            return HealingResult(
                success=False,
                tier=self.tier_type,
                reason=str(e),
            )

    async def _build_assessment_request(
        self,
        issue: HealthIssue,
        state: HealingState,
    ) -> dict:
        """Build structured request for remote API."""
        # Get endpoints list - handle both service and proxy interface
        all_endpoints = []
        try:
            if hasattr(self._orchestrator, "get_all_endpoint_status"):
                all_endpoints = list(self._orchestrator.get_all_endpoint_status().keys())
            elif hasattr(self._orchestrator, "_get_status_async"):
                # Prefer async method to avoid sync wrapper issues
                status = await self._orchestrator._get_status_async()
                endpoints = status.get("endpoints", [])
                # Handle list format: [{"name": "reasoning", ...}, ...]
                if isinstance(endpoints, list):
                    all_endpoints = [ep.get("name") for ep in endpoints if isinstance(ep, dict)]
                # Handle dict format: {"reasoning": {...}, ...}
                else:
                    all_endpoints = list(endpoints.keys())
        except Exception:
            pass

        return {
            "type": "self_healing_assessment",
            "issue": issue.to_dict(),
            "state": {
                "current_tier": state.current_tier,
                "attempts": state.attempts_at_tier,
                "history": [r.to_dict() for r in state.escalation_history[-10:]],
            },
            "available_remediations": list(self.REMEDIATION_PATHS.keys()),
            "system_context": {
                "all_endpoints": all_endpoints,
            },
        }

    async def _call_remote_api(self, request: dict) -> dict:
        """Call remote API for assessment.

        Args:
            request: Structured assessment request

        Returns:
            Response dict with remediation_code, assessment, confidence
        """
        # TODO: Integrate with actual xAI/Anthropic API
        # For now, use heuristic fallback
        issue = request.get("issue", {})
        history = request.get("state", {}).get("history", [])

        # Simple decision tree based on history
        if len(history) >= 5:
            # Many failed attempts, mark for manual intervention
            return {
                "remediation_code": "FAILOVER_MANUAL",
                "assessment": "Multiple recovery attempts failed, manual review needed",
                "confidence": 0.9,
            }

        error_msg = (issue.get("error_message") or "").lower()

        if "memory" in error_msg or "oom" in error_msg:
            return {
                "remediation_code": "REDUCE_TENSOR_PARALLEL",
                "assessment": "Memory pressure detected, reducing resource usage",
                "confidence": 0.7,
            }

        if "cuda" in error_msg or "gpu" in error_msg:
            return {
                "remediation_code": "COLD_RESTART",
                "assessment": "GPU/CUDA error requires cold restart",
                "confidence": 0.8,
            }

        # Default: full cleanup and reconcile
        return {
            "remediation_code": "FULL_CLEANUP",
            "assessment": "General failure, performing full cleanup",
            "confidence": 0.6,
        }

    # Remediation implementations

    async def _cold_restart(self, endpoint: str) -> bool:
        """Cold restart: full stop with GPU cleanup."""
        logger.info(f"Cold restart for {endpoint}")

        # Force stop
        result = self._orchestrator.stop_endpoint(endpoint)
        if asyncio.iscoroutine(result):
            await result

        # Extended wait for GPU memory release
        await asyncio.sleep(10)

        # Clear CUDA cache if available
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        # Restart
        try:
            result = self._orchestrator.start_endpoint(endpoint)
            if asyncio.iscoroutine(result):
                result = await result
            # Handle both bool and dict/object response
            if isinstance(result, bool):
                return result
            elif isinstance(result, dict):
                return result.get("status") == "healthy"
            return getattr(result, "status", None) == "healthy"
        except Exception as e:
            logger.error(f"Cold restart failed: {e}")
            return False

    async def _full_cleanup(self, endpoint: str) -> bool:
        """Full cleanup: kill stale processes, reconcile state."""
        logger.info(f"Full cleanup for {endpoint}")

        # Try orchestrator cleanup_stale_processes if available
        if hasattr(self._orchestrator, "cleanup_stale_processes"):
            try:
                cleanup = await self._orchestrator.cleanup_stale_processes()
                if isinstance(cleanup, dict):
                    logger.info(
                        f"Cleanup: found {cleanup.get('processes_found', 0)}, "
                        f"killed {cleanup.get('processes_killed', 0)}"
                    )
                else:
                    logger.info(
                        f"Cleanup: found {cleanup.processes_found}, "
                        f"killed {cleanup.processes_killed}"
                    )
            except Exception as e:
                logger.warning(f"Orchestrator cleanup failed, trying direct cleanup: {e}")
                # Fallback to direct process cleanup
                await self._direct_process_cleanup()
        else:
            # No orchestrator cleanup, use direct method
            await self._direct_process_cleanup()

        # Reconcile state if available
        if hasattr(self._orchestrator, "reconcile_state"):
            try:
                reconcile = await self._orchestrator.reconcile_state()
                return len(reconcile.get("errors", [])) == 0
            except Exception as e:
                logger.warning(f"Reconcile state failed: {e}")

        return True  # Cleanup succeeded even if reconcile not available

    async def _direct_process_cleanup(self) -> dict:
        """Directly kill stale vLLM processes using subprocess."""
        import subprocess

        processes_found = 0
        processes_killed = 0

        try:
            # Find vLLM processes
            result = subprocess.run(
                ["pgrep", "-f", "vllm.entrypoints"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pids = [int(p) for p in result.stdout.strip().split("\n") if p]
                processes_found = len(pids)

                # Kill each process
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-9", str(pid)], check=False)
                        processes_killed += 1
                        logger.info(f"Killed stale vLLM process {pid}")
                    except Exception as e:
                        logger.warning(f"Failed to kill process {pid}: {e}")

            logger.info(f"Direct cleanup: found {processes_found}, killed {processes_killed}")
        except Exception as e:
            logger.error(f"Direct process cleanup failed: {e}")

        return {"processes_found": processes_found, "processes_killed": processes_killed}

    async def _reconcile_state(self, endpoint: str) -> bool:
        """Reconcile state only."""
        if hasattr(self._orchestrator, "reconcile_state"):
            try:
                result = await self._orchestrator.reconcile_state()
                return len(result.get("errors", [])) == 0
            except Exception as e:
                logger.warning(f"Reconcile state failed: {e}")
                # Fallback: just do cleanup and restart
                await self._direct_process_cleanup()
                return True
        return True  # No reconcile method, assume success

    async def _reduce_tensor_parallel(self, endpoint: str) -> bool:
        """Reduce tensor parallelism and restart."""
        # TODO: Implement tensor parallel reduction
        # For now, fall back to cold restart
        logger.warning(
            "REDUCE_TENSOR_PARALLEL not fully implemented, using cold restart"
        )
        return await self._cold_restart(endpoint)

    async def _failover_manual(self, endpoint: str) -> bool:
        """Mark endpoint for manual intervention."""
        logger.critical(
            f"FAILOVER: Endpoint {endpoint} marked for manual intervention. "
            f"Self-healing exhausted all options."
        )

        # Stop the endpoint to prevent further issues
        result = self._orchestrator.stop_endpoint(endpoint)
        if asyncio.iscoroutine(result):
            await result

        # The endpoint is now stopped and requires human intervention
        # Return True because the "failover" action itself succeeded
        return True


class SelfHealingCoordinator:
    """Central coordinator for tiered self-healing.

    Orchestrates healing attempts across tiers, manages state,
    and enforces circuit breakers and cooldowns.
    """

    def __init__(
        self,
        orchestrator_service: "OrchestratorService",
        tier0_config: dict | None = None,
        tier1_config: dict | None = None,
        tier2_config: dict | None = None,
    ):
        """Initialize the self-healing coordinator.

        Args:
            orchestrator_service: Orchestrator for endpoint management
            tier0_config: Config for procedural tier
            tier1_config: Config for local agent tier
            tier2_config: Config for remote escalation tier
        """
        self._orchestrator = orchestrator_service

        # Initialize tiers
        tier0_config = tier0_config or {}
        tier1_config = tier1_config or {}
        tier2_config = tier2_config or {}

        self.tiers: list[HealingTier] = [
            Tier0Procedural(
                orchestrator_service,
                max_attempts=tier0_config.get("max_attempts", 3),
                cooldown_seconds=tier0_config.get("cooldown_seconds", 60),
            ),
            Tier1LocalAgent(
                orchestrator_service,
                allowed_actions=tier1_config.get("allowed_actions"),
                required_healthy_endpoints=tier1_config.get(
                    "required_healthy_endpoints", 1
                ),
            ),
            Tier2RemoteEscalation(
                orchestrator_service,
                api_provider=tier2_config.get("api_provider", "xai"),
                budget_limit_daily=tier2_config.get("budget_limit_daily", 50),
                enabled=tier2_config.get("enabled", True),
            ),
        ]

        # Track healing state per endpoint
        self._states: dict[str, HealingState] = {}

        # Global circuit breaker
        self._global_failures = 0
        self._global_failure_threshold = 10
        self._global_cooldown_until: datetime | None = None

        logger.info("SelfHealingCoordinator initialized with 3 tiers")

    def _get_or_create_state(self, endpoint: str) -> HealingState:
        """Get or create healing state for endpoint."""
        if endpoint not in self._states:
            self._states[endpoint] = HealingState(endpoint=endpoint)
        return self._states[endpoint]

    def _reset_state(self, endpoint: str) -> None:
        """Reset healing state after successful recovery."""
        if endpoint in self._states:
            del self._states[endpoint]
        self._global_failures = 0

    async def handle_health_issue(self, issue: HealthIssue) -> HealingResult:
        """Entry point for handling detected health issues.

        Args:
            issue: The health issue to address

        Returns:
            HealingResult with outcome
        """
        # Check global circuit breaker
        if self._global_cooldown_until and datetime.now() < self._global_cooldown_until:
            return HealingResult(
                action="global_cooldown",
                deferred=True,
                reason=f"Global cooldown until {self._global_cooldown_until}",
            )

        state = self._get_or_create_state(issue.endpoint)

        # Check endpoint-specific cooldown
        if state.cooldown_until and datetime.now() < state.cooldown_until:
            return HealingResult(
                action="cooldown",
                deferred=True,
                reason=f"Endpoint cooldown until {state.cooldown_until}",
            )

        logger.info(
            f"Handling health issue for {issue.endpoint}: {issue.issue_type} "
            f"(tier {state.current_tier}, attempt {state.attempts_at_tier})"
        )

        # Try current tier
        tier = self.tiers[state.current_tier]

        # Skip unavailable tiers
        if not tier.is_available():
            if state.current_tier < 2:
                logger.info(
                    f"Tier {state.current_tier} unavailable, escalating"
                )
                state.current_tier += 1
                state.attempts_at_tier = 0
                return await self.handle_health_issue(issue)
            else:
                return HealingResult(
                    success=False,
                    reason="All tiers unavailable",
                )

        # Attempt healing
        result = await tier.attempt_healing(issue, state)

        if result.success:
            logger.info(
                f"Self-healing succeeded for {issue.endpoint} "
                f"at tier {state.current_tier}: {result.action}"
            )
            self._reset_state(issue.endpoint)
            return result

        # Track global failures
        self._global_failures += 1
        if self._global_failures >= self._global_failure_threshold:
            self._global_cooldown_until = datetime.now() + timedelta(minutes=5)
            logger.warning(
                f"Global circuit breaker triggered after {self._global_failures} failures"
            )

        # Escalate if needed
        if result.escalate and state.current_tier < 2:
            state.current_tier += 1
            state.attempts_at_tier = 0
            logger.info(
                f"Escalating {issue.endpoint} from tier {state.current_tier - 1} "
                f"to tier {state.current_tier}"
            )
            return await self.handle_health_issue(issue)

        # All tiers exhausted
        if state.current_tier >= 2:
            logger.critical(
                f"Self-healing exhausted for {issue.endpoint}. "
                f"Manual intervention required."
            )
            return HealingResult(
                success=False,
                action="manual_intervention_required",
                reason="All healing tiers exhausted",
            )

        return result

    def get_status(self) -> dict[str, Any]:
        """Get current self-healing status."""
        return {
            "tiers": [
                {
                    "type": tier.tier_type.name,
                    "available": tier.is_available(),
                }
                for tier in self.tiers
            ],
            "endpoint_states": {
                endpoint: {
                    "current_tier": state.current_tier,
                    "attempts_at_tier": state.attempts_at_tier,
                    "cooldown_until": (
                        state.cooldown_until.isoformat()
                        if state.cooldown_until
                        else None
                    ),
                    "history_count": len(state.escalation_history),
                }
                for endpoint, state in self._states.items()
            },
            "global_failures": self._global_failures,
            "global_cooldown_until": (
                self._global_cooldown_until.isoformat()
                if self._global_cooldown_until
                else None
            ),
        }

    def get_healing_history(
        self,
        endpoint: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get healing attempt history.

        Args:
            endpoint: Filter by endpoint (None for all)
            limit: Max records to return

        Returns:
            List of escalation records
        """
        if endpoint:
            state = self._states.get(endpoint)
            if state:
                return [r.to_dict() for r in state.escalation_history[-limit:]]
            return []

        # All endpoints
        all_history = []
        for state in self._states.values():
            all_history.extend(state.escalation_history)

        # Sort by timestamp and limit
        all_history.sort(key=lambda r: r.timestamp, reverse=True)
        return [r.to_dict() for r in all_history[:limit]]
