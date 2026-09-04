"""Health checker that applies heuristics to diagnose system state.

Provides comprehensive health diagnostics including:
- Engine connectivity and status
- Inference endpoint health
- Database connectivity
- Cognition daemon status
- Resource utilization

The CheckStatus enum is the local Python representation used throughout
the health checker. It maps to proto enums defined in gaius_service.proto
for wire format compatibility.
"""

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from .heuristics import Heuristic, HeuristicLoader

# Import proto enum type for type-safe conversion
from ..engine.generated import (
    CheckStatus as ProtoCheckStatus,
    CHECK_STATUS_FAIL,
    CHECK_STATUS_PASS,
    CHECK_STATUS_SKIP,
    CHECK_STATUS_WARN,
    CHECK_STATUS_UNSPECIFIED,
)

if TYPE_CHECKING:
    from .self_healing import SelfHealingCoordinator

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a health check.

    This is the internal Python representation. Maps to proto CheckStatus enum:
    - PASS -> CHECK_STATUS_PASS (1)
    - WARN -> CHECK_STATUS_WARN (2)
    - FAIL -> CHECK_STATUS_FAIL (3)
    - SKIP -> CHECK_STATUS_SKIP (4)

    Use to_proto() and from_proto() for type-safe conversion.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    def to_proto(self) -> "ProtoCheckStatus":
        """Convert to proto enum value (type-safe).

        Returns the proto CheckStatus enum value (CHECK_STATUS_PASS, etc.).
        """
        return _STATUS_TO_PROTO.get(self, CHECK_STATUS_UNSPECIFIED)

    @classmethod
    def from_proto(cls, proto_value: "ProtoCheckStatus") -> "CheckStatus":
        """Convert from proto enum value (type-safe).

        Args:
            proto_value: Proto CheckStatus enum value (e.g., CHECK_STATUS_PASS)

        Returns:
            Corresponding local CheckStatus enum member
        """
        return _PROTO_TO_STATUS.get(proto_value, cls.SKIP)


# Mapping between local enum and proto enum values
# Uses proto enum constants for type safety
_STATUS_TO_PROTO: dict["CheckStatus", "ProtoCheckStatus"] = {
    CheckStatus.PASS: CHECK_STATUS_PASS,
    CheckStatus.WARN: CHECK_STATUS_WARN,
    CheckStatus.FAIL: CHECK_STATUS_FAIL,
    CheckStatus.SKIP: CHECK_STATUS_SKIP,
}

_PROTO_TO_STATUS: dict["ProtoCheckStatus", "CheckStatus"] = {v: k for k, v in _STATUS_TO_PROTO.items()}

# Expected cadences for periodic tasks: task_type -> (interval, label, catch-up hint)
_PERIODIC_TASK_CADENCES: dict[str, tuple[timedelta, str, str]] = {
    # Engine cognition cycle — core thinking loop
    # Expected = the REAL cron cadence (ratio thresholds add the slack).
    # The old 15min/1h values predated the current schedules and flagged
    # healthy mid-cycle tasks as "critically overdue" (2026-08-31).
    "cognition_cycle":       (timedelta(hours=4),    "Cognition cycle",       "Engine must be running: devenv processes up"),
    "llm_triage":            (timedelta(hours=4),    "LLM triage",            "Engine must be running: devenv processes up"),
    "content_processing":    (timedelta(hours=2),    "Content processing",    "Engine must be running: devenv processes up"),
    "article_curation":      (timedelta(hours=6),    "Article curation",      "Engine must be running: devenv processes up"),
    "card_publishing":       (timedelta(hours=6),    "Card publishing",       "Engine must be running: devenv processes up"),
    "evolution_cycle":       (timedelta(hours=12),   "Evolution cycle",       "Engine must be running: devenv processes up"),
    "card_upkeep":           (timedelta(hours=12),   "Card upkeep",           "Engine must be running: devenv processes up"),
    # pg_cron SQL-only jobs (run even without engine)
    "heuristic-triage":      (timedelta(hours=1),    "Heuristic triage",      "Check pg_cron: SELECT * FROM cron.job WHERE jobname LIKE '%heuristic%'"),
    "engine-audit":          (timedelta(hours=1),    "Engine audit",          "Check pg_cron: SELECT * FROM cron.job WHERE jobname LIKE '%audit%'"),
    "meta-consolidation":    (timedelta(hours=6),    "Meta consolidation",    "Check pg_cron: SELECT * FROM cron.job"),
    "prospect-refresh":      (timedelta(hours=12),   "Prospect refresh",      "Check pg_cron: SELECT * FROM cron.job WHERE jobname LIKE '%prospect%'"),
    "calibration":           (timedelta(days=1),     "Calibration",           "Check pg_cron: SELECT * FROM cron.job WHERE jobname LIKE '%calibrat%'"),
    # (2026-09-04) The engine's private model timers, now flows on pg_cron.
    "fmp_roll":              (timedelta(minutes=30), "FMP market roll",       "Check pg_cron job 'fmp-roll' and /objective verify market_buffer"),
    "ambient_synthesis":     (timedelta(minutes=20), "Ambient synthesis",     "Check pg_cron job 'ambient-synthesis' and /ambient status"),
}


def _format_timedelta(td: timedelta) -> str:
    """Format timedelta as human-readable string (e.g., '2h 30m', '3d 4h')."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    heuristic_id: Optional[str] = None
    fix_service: Optional[str] = None  # Key in SERVICE_STRATEGIES for auto-remediation
    duration_ms: int = 0
    suggestion: Optional[str] = None


@dataclass
class HealthCheck:
    """Definition of a health check."""

    id: str
    name: str
    category: str
    description: str
    check_fn: str  # Name of method to call
    heuristic_id: Optional[str] = None
    fix_service: Optional[str] = None  # Key in SERVICE_STRATEGIES for auto-remediation
    critical: bool = False  # If True, failure stops further checks
    slow: bool = False  # If True, skipped by run_quick and default run_all


@dataclass
class RCANotice:
    """Root Cause Analysis notice when multiple failures share a common cause."""

    root_cause: str
    affected_checks: set[str]
    message: str
    escalation: str  # "ACP investigation" or "manual RCA"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "root_cause": self.root_cause,
            "affected_checks": sorted(self.affected_checks),
            "message": self.message,
            "escalation": self.escalation,
        }


# Dependency map for root cause correlation.
# When multiple checks that depend on the same infrastructure fail,
# we surface a single RCA notice instead of individual fix suggestions.
# Maps root infrastructure to (sentinel_check_id, dependent_check_ids).
# The sentinel is the check that directly tests the root infrastructure.
# If the sentinel passes, the group is NOT the root cause — skip it.
_DEPENDENCY_MAP: dict[str, tuple[str, list[str]]] = {
    # Infrastructure layer — K8s being down breaks the entire Metaflow pipeline
    "k8s": ("metaflow_stack", ["metaflow_stack", "metaflow_service"]),
    # Database layer — postgres down breaks everything that queries it
    "postgres": ("database_connection", [
        "database_connection", "task_queue", "landing_page_pipeline",
        "metaflow_stack", "content_freshness",
    ]),
    # Engine runtime — engine/daemons stopped means nothing processes
    "engine": ("grpc_connection", [
        "grpc_connection", "engine_endpoints", "cognition_daemon",
        "evolution_daemon", "periodic_task_freshness", "metaflow_stack",
    ]),
    # Curation pipeline — broken Metaflow means no new content flows through
    "curation_pipeline": ("metaflow_stack", [
        "metaflow_stack", "landing_page_pipeline", "content_freshness",
    ]),
}


@dataclass
class HealthReport:
    """Comprehensive health report."""

    timestamp: datetime
    duration_ms: int
    checks: list[CheckResult]

    # Summary counts
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    skipped: int = 0

    # Collected metrics
    metrics: dict[str, Any] = field(default_factory=dict)

    # Suggested interventions
    interventions: list[str] = field(default_factory=list)

    # Root cause analysis notices
    rca_notices: list[RCANotice] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Overall health status."""
        return self.failures == 0

    @property
    def status_indicator(self) -> str:
        """Status indicator character."""
        if self.failures > 0:
            return "[FAIL]"
        if self.warnings > 0:
            return "[WARN]"
        return "[OK]"

    def summary(self) -> str:
        """Generate summary string."""
        total = len(self.checks)
        parts = [
            f"{self.status_indicator} Health: {self.passed}/{total} passed, "
            f"{self.warnings} warnings, {self.failures} failures"
        ]
        if self.rca_notices:
            roots = ", ".join(n.root_cause for n in self.rca_notices)
            parts.append(f"  Root Cause Analysis: {len(self.rca_notices)} correlation(s) detected ({roots})")
        return "\n".join(parts)


class HealthChecker:
    """Applies heuristics to check system health."""

    def __init__(
        self,
        kb_root: Optional[Path] = None,
        healing_coordinator: Optional["SelfHealingCoordinator"] = None,
    ):
        """Initialize health checker.

        Args:
            kb_root: Path to KB root (defaults to build/dev)
            healing_coordinator: Optional self-healing coordinator to emit issues to
        """
        self.kb_root = kb_root or Path("build/dev")
        self.heuristics_path = self.kb_root / "current/heuristics/gaius"
        self.loader = HeuristicLoader(self.heuristics_path)
        self._healing_coordinator: Optional["SelfHealingCoordinator"] = healing_coordinator

        # Define health checks
        self._checks = [
            # Engine checks (gRPC - primary orchestration path)
            HealthCheck(
                id="grpc_connection",
                name="gRPC Engine",
                category="engine",
                description="Primary: gRPC client to engine (orchestration, cognition, evolution)",
                check_fn="_check_grpc_connection",
                heuristic_id="engine/grpc_connection_stale",
                fix_service="engine",
                critical=False,  # Not critical - inference has fallback paths
            ),
            HealthCheck(
                id="engine_endpoints",
                name="Engine Endpoints",
                category="engine",
                description="vLLM endpoints managed by engine",
                check_fn="_check_endpoints",
                heuristic_id="inference/endpoint_unhealthy",
                fix_service="endpoints",
            ),
            HealthCheck(
                id="engine_serving",
                name="Engine Serving",
                category="engine",
                description="Out-of-band :50051 liveness — surfaces a watchdog-tripped serving desync (#EN.00000017)",
                check_fn="_check_engine_serving",
                heuristic_id="engine/serving_desync",
                fix_service="engine",
            ),
            # Inference service checks (direct HTTP paths)
            HealthCheck(
                id="optillm_service",
                name="optillm Service",
                category="inference",
                description="DEV FALLBACK: Direct HTTP inference (no auth - use gRPC for production)",
                check_fn="_check_optillm",
            ),
            HealthCheck(
                id="vllm_service",
                name="vLLM Service",
                category="inference",
                description="DEV FALLBACK: Direct vLLM (no auth - use gRPC for production)",
                check_fn="_check_vllm_direct",
            ),
            # Data service checks
            HealthCheck(
                id="database_connection",
                name="PostgreSQL",
                category="data",
                description="Primary: Activity logs, evolution state, agent versions",
                check_fn="_check_database",
                heuristic_id="data/database_connection_failed",
                fix_service="postgres",
                critical=True,
            ),
            HealthCheck(
                id="qdrant_service",
                name="Qdrant",
                category="data",
                description="Primary: Vector embeddings, semantic search, latent memory",
                check_fn="_check_qdrant",
                fix_service="qdrant",
            ),
            HealthCheck(
                id="s3_minio_service",
                name="S3/MinIO",
                category="data",
                description="Primary: Object storage for artifacts, large documents",
                check_fn="_check_s3_minio",
                fix_service="minio",
            ),
            # Cognition checks
            HealthCheck(
                id="cognition_daemon",
                name="Cognition Daemon",
                category="cognition",
                description="Check cognition daemon is running",
                check_fn="_check_cognition_daemon",
                heuristic_id="cognition/daemon_not_running",
            ),
            HealthCheck(
                id="recent_thoughts",
                name="Recent Thoughts",
                category="cognition",
                description="Check thoughts are being generated",
                check_fn="_check_recent_thoughts",
            ),
            # Resource checks
            HealthCheck(
                id="gpu_memory",
                name="GPU Memory",
                category="inference",
                description="Check GPU memory utilization",
                check_fn="_check_gpu_memory",
                heuristic_id="inference/gpu_memory_exhausted",
            ),
            HealthCheck(
                id="disk_space",
                name="Disk Space",
                category="data",
                description="Check available disk space",
                check_fn="_check_disk_space",
            ),
            # Evolution checks
            HealthCheck(
                id="evolution_daemon",
                name="Evolution Daemon",
                category="evolution",
                description="Check evolution daemon status and cycle frequency",
                check_fn="_check_evolution_daemon_status",
            ),
            # Additional inference checks
            HealthCheck(
                id="gpu_temperature",
                name="GPU Temperature",
                category="inference",
                description="Check GPU temperature levels",
                check_fn="_check_gpu_temperature",
            ),
            HealthCheck(
                id="scheduler_queue",
                name="Scheduler Queue",
                category="inference",
                description="Check scheduler queue depth and wait times",
                check_fn="_check_scheduler_queue",
            ),
            HealthCheck(
                id="xai_budget",
                name="XAI Budget",
                category="inference",
                description="Check XAI API budget usage",
                check_fn="_check_xai_budget",
            ),
            HealthCheck(
                id="stale_processes",
                name="Stale Processes",
                category="engine",
                description="Check for orphan vLLM processes not managed by engine",
                check_fn="_check_stale_processes",
                heuristic_id="inference/stale_vllm_processes",
            ),
            HealthCheck(
                id="endpoint_stuck",
                name="Stuck Endpoints",
                category="engine",
                description="Check for endpoints stuck in starting/stopping state",
                check_fn="_check_endpoint_stuck",
                heuristic_id="inference/endpoint_stuck",
            ),
            HealthCheck(
                id="routing_quality",
                name="Model Routing",
                category="inference",
                description="Check capability-based routing quality",
                check_fn="_check_routing_quality",
            ),
            # RASE intrinsic verification checks
            HealthCheck(
                id="rase_objectives",
                name="RASE Objectives",
                category="rase",
                description="Check KB objectives and intrinsic verification components",
                check_fn="_check_rase_objectives",
            ),
            # Configuration audit checks
            HealthCheck(
                id="config_audit",
                name="Config Audit",
                category="config",
                description="Audit port/URL mismatches between env vars and running services",
                check_fn="_check_config_audit",
                heuristic_id="inference/optillm_port_mismatch",
            ),
            # Content pipeline checks
            HealthCheck(
                id="pipeline_status",
                name="Pipeline Status",
                category="pipeline",
                description="Check content pipeline stage health (fetch → triage → KB)",
                check_fn="_check_pipeline_status",
                heuristic_id="pipeline/stage_backlog",
            ),
            HealthCheck(
                id="task_queue",
                name="Task Queue",
                category="pipeline",
                description="Check for stalled or stuck scheduled tasks",
                check_fn="_check_task_queue",
                heuristic_id="cognition/task_queue_stalled",
            ),
            # Landing page pipeline checks (site category — public-facing)
            HealthCheck(
                id="landing_page_pipeline",
                name="Landing Page",
                category="site",
                description="Check article curation and card publishing pipeline health",
                check_fn="_check_landing_page_pipeline",
                heuristic_id="site/landing_page_stale",
            ),
            # Periodic task freshness
            HealthCheck(
                id="periodic_task_freshness",
                name="Periodic Tasks",
                category="periodic",
                description="Check periodic task completion cadence (cognition, triage, curation, evolution)",
                check_fn="_check_periodic_task_freshness",
            ),
            # Site content completeness checks (DB-side)
            HealthCheck(
                id="site_card_images",
                name="Card Images",
                category="site",
                description="Check all published cards have LuxCore visualization images",
                check_fn="_check_site_card_images",
                heuristic_id="site/card_images_missing",
            ),
            HealthCheck(
                id="site_card_summaries",
                name="Card Summaries",
                category="site",
                description="Check all published cards have frontier, open_weights, and cerebras summaries",
                check_fn="_check_site_card_summaries",
                heuristic_id="site/card_summaries_incomplete",
            ),
            HealthCheck(
                id="site_card_briefs",
                name="Card Briefs",
                category="site",
                description="Check all published cards have unique, substantive brief text",
                check_fn="_check_site_card_briefs",
                heuristic_id="site/card_briefs_degraded",
            ),
            HealthCheck(
                id="site_collection_completeness",
                name="Collection Completeness",
                category="site",
                description="Check featured cards have LuxCore images and local open-weights summaries",
                check_fn="_check_site_collection_completeness",
                heuristic_id="site/collection_incomplete",
            ),
            # Live site verification (HTTP + KV)
            HealthCheck(
                id="site_live_verification",
                name="Live Site",
                category="site",
                description="Verify live site renders content correctly (sample card page, image, KV data)",
                check_fn="_check_site_live_verification",
                heuristic_id="site/live_site_stale",
            ),
            # Content freshness — is the pipeline producing new cards?
            HealthCheck(
                id="site_content_freshness",
                name="Content Freshness",
                category="site",
                description="Check that the site is receiving new published cards at expected cadence",
                check_fn="_check_site_content_freshness",
                heuristic_id="site/content_stale",
            ),
            # Metaflow deep stack validation (slow — K8s + HTTP checks)
            HealthCheck(
                id="metaflow_stack",
                name="Metaflow Stack",
                category="pipeline",
                description="Metaflow service, K8s cluster, flow success rate",
                check_fn="_check_metaflow_stack",
                heuristic_id="infrastructure/metaflow_stack_down",
                fix_service="metaflow",
            ),
        ]

    async def run_all(
        self,
        progress_callback: Optional[Callable[["CheckResult", int, int], Awaitable[None]]] = None,
        include_slow: bool = False,
    ) -> HealthReport:
        """Run all health checks with optional progress reporting.

        Args:
            progress_callback: Called after each check with (result, completed, total)
            include_slow: If True, also run checks marked as slow (default False)

        Returns:
            Comprehensive health report
        """
        start_time = time.time()
        results = []
        metrics = {}

        # Filter out slow checks unless explicitly requested
        checks_to_run = [
            c for c in self._checks if include_slow or not c.slow
        ]
        total_checks = len(checks_to_run)

        for i, check in enumerate(checks_to_run):
            result = await self._run_check(check)
            results.append(result)

            # Report progress if callback provided
            if progress_callback:
                await progress_callback(result, i + 1, total_checks)

            # Stop on critical failure
            if check.critical and result.status == CheckStatus.FAIL:
                logger.warning(f"Critical check failed: {check.name}")
                # Mark remaining as skipped
                for remaining in checks_to_run[i + 1 :]:
                    results.append(
                        CheckResult(
                            name=remaining.name,
                            status=CheckStatus.SKIP,
                            message="Skipped due to critical failure",
                        )
                    )
                break

        duration_ms = int((time.time() - start_time) * 1000)

        # Calculate summary
        passed = sum(1 for r in results if r.status == CheckStatus.PASS)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARN)
        failures = sum(1 for r in results if r.status == CheckStatus.FAIL)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)

        # Collect interventions
        interventions = []
        for result in results:
            if result.suggestion and result.status in (CheckStatus.WARN, CheckStatus.FAIL):
                interventions.append(result.suggestion)

        # Detect root cause correlations
        rca_notices = self._detect_root_cause(results, checks_to_run)

        report = HealthReport(
            timestamp=datetime.now(),
            duration_ms=duration_ms,
            checks=results,
            passed=passed,
            warnings=warnings,
            failures=failures,
            skipped=skipped,
            metrics=metrics,
            interventions=interventions,
            rca_notices=rca_notices,
        )

        # Emit failures to self-healing coordinator if configured
        if self._healing_coordinator:
            await self._emit_issues_to_coordinator(results)

        return report

    async def run_category(
        self,
        category: str,
        progress_callback: Optional[Callable[["CheckResult", int, int], Awaitable[None]]] = None,
    ) -> HealthReport:
        """Run health checks for a specific category with optional progress reporting.

        Args:
            category: Category name (engine, data, cognition, inference)
            progress_callback: Called after each check with (result, completed, total)

        Returns:
            Health report for that category
        """
        start_time = time.time()
        results = []

        # Filter checks for this category
        category_checks = [c for c in self._checks if c.category == category]
        total_checks = len(category_checks)

        for i, check in enumerate(category_checks):
            result = await self._run_check(check)
            results.append(result)

            # Report progress if callback provided
            if progress_callback:
                await progress_callback(result, i + 1, total_checks)

        duration_ms = int((time.time() - start_time) * 1000)

        passed = sum(1 for r in results if r.status == CheckStatus.PASS)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARN)
        failures = sum(1 for r in results if r.status == CheckStatus.FAIL)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)

        interventions = [r.suggestion for r in results if r.suggestion and r.status != CheckStatus.PASS]

        return HealthReport(
            timestamp=datetime.now(),
            duration_ms=duration_ms,
            checks=results,
            passed=passed,
            warnings=warnings,
            failures=failures,
            skipped=skipped,
            interventions=interventions,
        )

    async def run_quick(
        self,
        progress_callback: Optional[Callable[["CheckResult", int, int], Awaitable[None]]] = None,
    ) -> HealthReport:
        """Run essential service connectivity checks with optional progress reporting.

        Shows all primary services and their roles:
        - gRPC Engine: Orchestration, cognition, evolution (primary)
        - optillm: Inference with optimization techniques (primary)
        - vLLM: Direct inference fallback
        - PostgreSQL: Activity logs, state (critical)
        - Qdrant: Vector embeddings, semantic search (primary)
        - S3/MinIO: Object storage (primary)

        Args:
            progress_callback: Called after each check with (result, completed, total)

        Returns:
            Health report with service connectivity status
        """
        start_time = time.time()
        results = []

        # Essential service checks for quick view
        essential_ids = [
            "grpc_connection",         # gRPC to engine
            "optillm_service",         # Primary inference
            "vllm_service",            # Fallback inference
            "database_connection",     # PostgreSQL (critical)
            "qdrant_service",          # Vector DB
            "s3_minio_service",        # Object storage
            "landing_page_pipeline",   # Article curation / card publishing
        ]

        # Filter checks for quick view
        quick_checks = [c for c in self._checks if c.id in essential_ids]
        total_checks = len(quick_checks)

        for i, check in enumerate(quick_checks):
            result = await self._run_check(check)
            results.append(result)

            # Report progress if callback provided
            if progress_callback:
                await progress_callback(result, i + 1, total_checks)

        duration_ms = int((time.time() - start_time) * 1000)

        passed = sum(1 for r in results if r.status == CheckStatus.PASS)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARN)
        failures = sum(1 for r in results if r.status == CheckStatus.FAIL)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)

        # Collect interventions
        interventions = []
        for result in results:
            if result.suggestion and result.status in (CheckStatus.WARN, CheckStatus.FAIL):
                interventions.append(result.suggestion)

        return HealthReport(
            timestamp=datetime.now(),
            duration_ms=duration_ms,
            checks=results,
            passed=passed,
            warnings=warnings,
            failures=failures,
            skipped=skipped,
            interventions=interventions,
        )

    def _detect_root_cause(
        self,
        results: list[CheckResult],
        checks_run: list["HealthCheck"],
    ) -> list[RCANotice]:
        """Detect when multiple failures share a common root cause.

        Scans the dependency map for infrastructure roots where >= 2
        dependent checks failed simultaneously. Returns RCA notices that
        allow the observer to skip individual tier-0 remediation and
        escalate directly.

        Args:
            results: Completed check results
            checks_run: The HealthCheck definitions that were executed

        Returns:
            List of RCA notices (empty if no correlations found)
        """
        # Build a set of check IDs that actually failed
        check_id_by_name: dict[str, str] = {c.name: c.id for c in checks_run}
        failed_ids: set[str] = set()
        for r in results:
            if r.status == CheckStatus.FAIL:
                cid = check_id_by_name.get(r.name)
                if cid:
                    failed_ids.add(cid)

        notices: list[RCANotice] = []
        for root, (sentinel, dependents) in _DEPENDENCY_MAP.items():
            affected = failed_ids & set(dependents)
            if len(affected) < 2:
                continue
            # If the sentinel check passed, this root is NOT the cause —
            # the failures are downstream/coincidental
            if sentinel not in failed_ids:
                continue
            notices.append(RCANotice(
                root_cause=root,
                affected_checks=affected,
                message=(
                    f"Multiple failures trace to {root}. "
                    f"Root cause analysis recommended before individual fixes."
                ),
                escalation="ACP investigation",
            ))

        return notices

    async def _run_check(self, check: HealthCheck) -> CheckResult:
        """Run a single health check.

        Args:
            check: Health check definition

        Returns:
            Check result
        """
        start_time = time.time()

        try:
            check_method = getattr(self, check.check_fn, None)
            if not check_method:
                return CheckResult(
                    name=check.name,
                    status=CheckStatus.SKIP,
                    message=f"Check method not found: {check.check_fn}",
                )

            result = await check_method()
            result.heuristic_id = check.heuristic_id
            result.fix_service = check.fix_service
            result.duration_ms = int((time.time() - start_time) * 1000)

            # Add suggestion from heuristic if check failed
            if result.status in (CheckStatus.WARN, CheckStatus.FAIL) and check.heuristic_id:
                heuristic = self.loader.get(check.heuristic_id)
                if heuristic and heuristic.solution:
                    # Extract first paragraph of solution as suggestion
                    solution_lines = heuristic.solution.split("\n\n")
                    for line in solution_lines:
                        if line.startswith("**Remediation:**"):
                            continue
                        if line.strip() and not line.startswith("```"):
                            result.suggestion = line.strip()[:200]
                            break

            return result

        except Exception as e:
            logger.error(f"Check {check.name} failed with exception: {e}")
            return CheckResult(
                name=check.name,
                status=CheckStatus.FAIL,
                message=f"Exception: {str(e)[:100]}",
                duration_ms=int((time.time() - start_time) * 1000),
            )

    # =========================================================================
    # Check Implementations
    # =========================================================================

    async def _check_grpc_connection(self) -> CheckResult:
        """Check gRPC connection to engine."""
        try:
            from ..client.engine_proxy import use_engine_proxy
            from ..client.grpc_client import get_grpc_client

            if not use_engine_proxy():
                return CheckResult(
                    name="gRPC Connection",
                    status=CheckStatus.FAIL,
                    message="Engine not reachable on port 50051",
                    suggestion="Start the engine with: gaius-engine",
                )

            client = await get_grpc_client()
            if not client.is_connected:
                return CheckResult(
                    name="gRPC Connection",
                    status=CheckStatus.WARN,
                    message="gRPC client exists but not connected",
                    suggestion="Connection will retry on next call",
                )

            return CheckResult(
                name="gRPC Connection",
                status=CheckStatus.PASS,
                message="Connected to engine via gRPC",
                details={"host": client.config.host, "port": client.config.port},
            )

        except Exception as e:
            return CheckResult(
                name="gRPC Connection",
                status=CheckStatus.FAIL,
                message=f"Connection failed: {str(e)[:80]}",
            )

    async def _check_engine_serving(self) -> CheckResult:
        """Surface an engine serving-desync flagged by the out-of-band watchdog.

        The `gaius-engine-ready` watchdog (scripts/engine-ready.sh) is the L0
        detector for a dead/wedged :50051 that process-compose still reports
        "ready" — a class an in-engine observer cannot see (it dies with the
        engine). When the watchdog's deterministic recycle budget is exhausted it
        drops a breaker marker; we surface that here as an actionable incident,
        rather than let a silently-unrecovered engine masquerade as healthy.
        #EN.00000017.SERVEDESYNC
        """
        from .engine_liveness import GURU_SERVEDESYNC, read_engine_breaker

        breaker = read_engine_breaker()
        if breaker is None:
            return CheckResult(
                name="Engine Serving",
                status=CheckStatus.PASS,
                message="No engine serving-desync breaker tripped",
            )
        n = breaker.get("recycles_in_window")
        return CheckResult(
            name="Engine Serving",
            status=CheckStatus.FAIL,
            message=(
                f"{GURU_SERVEDESYNC} engine :50051 desync — out-of-band watchdog "
                f"exhausted its recycle budget ({n} recycles); deterministic "
                f"recovery did not hold"
            ),
            details={"endpoint": "engine", "breaker": breaker},
            suggestion="Complete-recycle + root-cause: /health fix engine (auto-escalates to ACP)",
        )

    async def _endpoint_serving(self, port: int) -> bool:
        """True iff the endpoint's HTTP frontend actually answers /health.

        A vLLM endpoint can report status=healthy (process up, sentinel pod
        Running) while its frontend is wedged — e.g. the accept queue jammed by a
        connection storm, the 2026-08-28 outage. status is a liveness PROXY, not
        proof of service, so probe the real thing. Two quick attempts so a single
        dropped packet does not read as a failure; a genuine jam fails both.
        """
        import httpx

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=3.0) as c:
                    r = await c.get(f"http://127.0.0.1:{port}/health")
                    if r.status_code == 200:
                        return True
            except Exception:
                pass
            if attempt == 0:
                await asyncio.sleep(0.5)
        return False

    async def _check_endpoints(self) -> CheckResult:
        """Check inference endpoint health."""
        try:
            from ..client.engine_proxy import get_health_proxy

            health = await get_health_proxy()
            status = await health.check()

            endpoints = status.get("endpoints", {})
            total = len(endpoints)
            # Accept both legacy "healthy" and gRPC protobuf enum "PROCESS_STATUS_HEALTHY"
            healthy_statuses = {"healthy", "PROCESS_STATUS_HEALTHY"}
            healthy = sum(1 for e in endpoints.values() if isinstance(e, dict) and e.get("status") in healthy_statuses)

            if total == 0:
                return CheckResult(
                    name="Engine Endpoints",
                    status=CheckStatus.WARN,
                    message="No endpoints configured",
                    details={"total": 0, "healthy": 0},
                )

            if healthy == 0:
                return CheckResult(
                    name="Engine Endpoints",
                    status=CheckStatus.FAIL,
                    message=f"No healthy endpoints (0/{total})",
                    details={"total": total, "healthy": 0, "endpoints": list(endpoints.keys())},
                    suggestion="Check endpoint logs with: /engine logs <name>",
                )

            if healthy < total:
                unhealthy = [name for name, e in endpoints.items() if isinstance(e, dict) and e.get("status") not in healthy_statuses]
                return CheckResult(
                    name="Engine Endpoints",
                    status=CheckStatus.WARN,
                    message=f"{healthy}/{total} endpoints healthy",
                    details={"total": total, "healthy": healthy, "unhealthy": unhealthy},
                    suggestion=f"Restart unhealthy: /engine restart {unhealthy[0]}",
                )

            # Liveness proxy passed (all report healthy). Now verify they actually
            # SERVE — a wedged frontend reports healthy but answers nothing. This
            # closes the observation blind spot behind the 2026-08-28 multi-hour
            # outage: thinking was "healthy" while its frontend was jammed, so the
            # observer never saw a failure and never recycled. FAIL here flows to
            # the endpoints fix strategy (recycle) and surfaces an incident, so the
            # failure is acted on AND left as an actionable signal, not hidden.
            not_serving = []
            for name, e in endpoints.items():
                if not isinstance(e, dict) or e.get("status") not in healthy_statuses:
                    continue
                port = e.get("port")
                if not port:
                    continue
                if not await self._endpoint_serving(int(port)):
                    not_serving.append(name)
            if not_serving:
                return CheckResult(
                    name="Engine Endpoints",
                    status=CheckStatus.FAIL,
                    message=(
                        f"#HL.00004.NOTSERVING {', '.join(not_serving)} report healthy "
                        f"but do not answer /health (frontend wedged)"
                    ),
                    details={
                        "total": total, "healthy": healthy, "not_serving": not_serving,
                    },
                    suggestion="Complete-recycle the unit: /health fix engine",
                    # engine (unit recycle), NOT endpoints: a wedged frontend still
                    # reports status=healthy, so the endpoints strategy (restarts
                    # UNHEALTHY ones) would no-op. The unit recycle is the proven
                    # 2026-08-28 recovery and also clears rogue forks / socket
                    # squatters an endpoint restart cannot.
                    fix_service="engine",
                )

            return CheckResult(
                name="Engine Endpoints",
                status=CheckStatus.PASS,
                message=f"All {total} endpoints serving",
                details={"total": total, "healthy": healthy, "endpoints": list(endpoints.keys())},
            )

        except Exception as e:
            return CheckResult(
                name="Engine Endpoints",
                status=CheckStatus.FAIL,
                message=f"Failed to check: {str(e)[:80]}",
            )

    async def _check_database(self) -> CheckResult:
        """Check database connectivity."""
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()

            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)
            # Basic connectivity test - just run a simple query
            result = await conn.fetchval("SELECT 1")

            # Get table count for additional info
            table_count = await conn.fetchval(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
            await conn.close()

            return CheckResult(
                name="Database Connection",
                status=CheckStatus.PASS,
                message=f"Connected, {table_count} tables in schema",
                details={"table_count": table_count},
            )

        except asyncio.TimeoutError:
            return CheckResult(
                name="Database Connection",
                status=CheckStatus.FAIL,
                message="Connection timeout",
                suggestion="Check PostgreSQL is running: pg_isready -p 5444",
            )
        except Exception as e:
            return CheckResult(
                name="Database Connection",
                status=CheckStatus.FAIL,
                message=f"Connection failed: {str(e)[:80]}",
                suggestion="Start database with: devenv up postgres",
            )

    async def _check_cognition_daemon(self) -> CheckResult:
        """Check cognition daemon status."""
        try:
            from ..client.engine_proxy import get_cognition_proxy

            cog = await get_cognition_proxy()
            status = await cog.get_status()

            if status.get("running"):
                cycles = status.get("cycles_completed", 0)
                return CheckResult(
                    name="Cognition Daemon",
                    status=CheckStatus.PASS,
                    message=f"Running, {cycles} cycles completed",
                    details=status,
                )
            else:
                return CheckResult(
                    name="Cognition Daemon",
                    status=CheckStatus.WARN,
                    message="Daemon not running",
                    details=status,
                    suggestion="Thoughts can still be generated via /thoughts",
                )

        except Exception as e:
            return CheckResult(
                name="Cognition Daemon",
                status=CheckStatus.WARN,
                message=f"Status check failed: {str(e)[:80]}",
                suggestion="Restart engine to enable cognition daemon",
            )

    async def _check_recent_thoughts(self) -> CheckResult:
        """Check if thoughts are being generated."""
        try:
            from ..client.engine_proxy import get_cognition_proxy

            cog = await get_cognition_proxy()
            thoughts = await cog.get_recent_thoughts(limit=10)

            if not thoughts:
                return CheckResult(
                    name="Recent Thoughts",
                    status=CheckStatus.WARN,
                    message="No thoughts found",
                    suggestion="Generate thoughts with: /thoughts",
                )

            # Check age of most recent thought
            most_recent = thoughts[0]
            timestamp_str = most_recent.get("timestamp")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    age = datetime.now(timestamp.tzinfo) - timestamp if timestamp.tzinfo else datetime.now() - timestamp
                    age_hours = age.total_seconds() / 3600

                    if age_hours > 24:
                        return CheckResult(
                            name="Recent Thoughts",
                            status=CheckStatus.WARN,
                            message=f"{len(thoughts)} thoughts, newest is {age_hours:.1f}h old",
                            details={"count": len(thoughts), "age_hours": age_hours},
                            suggestion="Generate fresh thoughts with: /thoughts",
                        )
                except (ValueError, TypeError):
                    pass

            return CheckResult(
                name="Recent Thoughts",
                status=CheckStatus.PASS,
                message=f"{len(thoughts)} recent thoughts available",
                details={"count": len(thoughts)},
            )

        except Exception as e:
            return CheckResult(
                name="Recent Thoughts",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_gpu_memory(self) -> CheckResult:
        """Check GPU memory utilization."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return CheckResult(
                    name="GPU Memory",
                    status=CheckStatus.SKIP,
                    message="nvidia-smi not available",
                )

            gpus = []
            warnings = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    idx, used, total, util = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    mem_pct = (used / total) * 100 if total > 0 else 0
                    gpus.append({"id": idx, "memory_used_mb": used, "memory_total_mb": total, "memory_pct": mem_pct, "utilization": util})

                    if mem_pct > 98:
                        warnings.append(f"GPU {idx} memory at {mem_pct:.0f}%")

            if warnings:
                return CheckResult(
                    name="GPU Memory",
                    status=CheckStatus.WARN,
                    message="; ".join(warnings),
                    details={"gpus": gpus},
                    suggestion="Free GPU memory by stopping unused endpoints",
                )

            return CheckResult(
                name="GPU Memory",
                status=CheckStatus.PASS,
                message=f"{len(gpus)} GPUs, memory OK",
                details={"gpus": gpus},
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                name="GPU Memory",
                status=CheckStatus.WARN,
                message="nvidia-smi timed out",
            )
        except FileNotFoundError:
            return CheckResult(
                name="GPU Memory",
                status=CheckStatus.SKIP,
                message="nvidia-smi not found (no GPU?)",
            )
        except Exception as e:
            return CheckResult(
                name="GPU Memory",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_disk_space(self) -> CheckResult:
        """Check available disk space."""
        try:
            import shutil

            # Check KB directory
            kb_path = self.kb_root
            if kb_path.exists():
                usage = shutil.disk_usage(kb_path)
                free_gb = usage.free / (1024**3)
                total_gb = usage.total / (1024**3)
                used_pct = (usage.used / usage.total) * 100

                if used_pct > 95:
                    return CheckResult(
                        name="Disk Space",
                        status=CheckStatus.FAIL,
                        message=f"Critical: {free_gb:.1f}GB free ({used_pct:.0f}% used)",
                        details={"free_gb": free_gb, "total_gb": total_gb, "used_pct": used_pct},
                        suggestion="Free disk space immediately",
                    )

                if used_pct > 85:
                    return CheckResult(
                        name="Disk Space",
                        status=CheckStatus.WARN,
                        message=f"Low: {free_gb:.1f}GB free ({used_pct:.0f}% used)",
                        details={"free_gb": free_gb, "total_gb": total_gb, "used_pct": used_pct},
                        suggestion="Consider cleaning old logs or archives",
                    )

                return CheckResult(
                    name="Disk Space",
                    status=CheckStatus.PASS,
                    message=f"{free_gb:.1f}GB free ({used_pct:.0f}% used)",
                    details={"free_gb": free_gb, "total_gb": total_gb, "used_pct": used_pct},
                )

            return CheckResult(
                name="Disk Space",
                status=CheckStatus.SKIP,
                message="KB path not found",
            )

        except Exception as e:
            return CheckResult(
                name="Disk Space",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_optillm(self) -> CheckResult:
        """Check optillm inference proxy connectivity.

        optillm is the PRIMARY inference path when using optimization
        techniques (COT, MOA, etc.). It proxies to vLLM with added
        reasoning enhancements.

        Note: In distributed deployments, this requires direct HTTP access
        to optillm (firewall/mTLS considerations).
        """
        import os

        try:
            import httpx

            url = os.getenv("GAIUS_OPTILLM_URL", "http://localhost:8000/v1")
            base_url = url.rstrip("/v1").rstrip("/")

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check /health or /v1/models endpoint
                try:
                    response = await client.get(f"{base_url}/health")
                    if response.status_code == 200:
                        return CheckResult(
                            name="optillm Service",
                            status=CheckStatus.PASS,
                            message=f"Connected at {base_url}",
                            details={
                                "url": base_url,
                                "role": "fallback",
                                "security": "NO_AUTH",
                                "note": "Direct HTTP bypasses auth - use gRPC engine for production",
                            },
                        )
                except httpx.HTTPError:
                    pass

                # Try /v1/models as fallback health check
                try:
                    response = await client.get(f"{url}/models")
                    if response.status_code == 200:
                        data = response.json()
                        models = data.get("data", [])
                        model_names = [m.get("id", "unknown") for m in models[:3]]
                        return CheckResult(
                            name="optillm Service",
                            status=CheckStatus.PASS,
                            message=f"Connected, {len(models)} model(s)",
                            details={
                                "url": base_url,
                                "role": "fallback",
                                "security": "NO_AUTH",
                                "models": model_names,
                                "note": "Direct HTTP bypasses auth - use gRPC engine for production",
                            },
                        )
                except httpx.HTTPError:
                    pass

                return CheckResult(
                    name="optillm Service",
                    status=CheckStatus.WARN,
                    message=f"Not responding at {base_url}",
                    details={"url": base_url, "role": "primary"},
                    suggestion="optillm is engine-managed. Try: /health fix engine",
                )

        except ImportError:
            return CheckResult(
                name="optillm Service",
                status=CheckStatus.SKIP,
                message="httpx not available",
            )
        except Exception as e:
            return CheckResult(
                name="optillm Service",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_vllm_direct(self) -> CheckResult:
        """Check direct vLLM endpoint connectivity.

        vLLM direct is the FALLBACK inference path when optillm is
        unavailable. Swarm analysis uses this path, bypassing gRPC.

        Note: In distributed deployments, this requires direct HTTP access
        to vLLM endpoints (firewall/mTLS considerations).
        """
        import os

        try:
            import httpx

            # Check multiple potential vLLM endpoints
            endpoints = [
                ("thinking", os.getenv("GAIUS_VLLM_THINKING_URL", "http://localhost:8081/v1")),
                ("reasoning", os.getenv("GAIUS_VLLM_REASONING_URL", "http://localhost:8083/v1")),
            ]

            available = []
            unavailable = []

            async with httpx.AsyncClient(timeout=3.0) as client:
                for name, url in endpoints:
                    try:
                        response = await client.get(f"{url}/models")
                        if response.status_code == 200:
                            data = response.json()
                            models = data.get("data", [])
                            model_id = models[0].get("id", "unknown") if models else "unknown"
                            available.append({"name": name, "url": url, "model": model_id})
                        else:
                            unavailable.append(name)
                    except Exception:
                        unavailable.append(name)

            if not available:
                return CheckResult(
                    name="vLLM Service",
                    status=CheckStatus.WARN,
                    message="No vLLM endpoints responding",
                    details={
                        "role": "fallback",
                        "security": "NO_AUTH",
                        "checked": [e[0] for e in endpoints],
                        "note": "Direct HTTP bypasses auth - use gRPC engine for production",
                    },
                    suggestion="Start vLLM: devenv up vllm",
                )

            if unavailable:
                return CheckResult(
                    name="vLLM Service",
                    status=CheckStatus.PASS,
                    message=f"{len(available)}/{len(endpoints)} endpoints available",
                    details={
                        "role": "fallback",
                        "security": "NO_AUTH",
                        "available": available,
                        "unavailable": unavailable,
                        "note": "Direct HTTP bypasses auth - use gRPC engine for production",
                    },
                )

            return CheckResult(
                name="vLLM Service",
                status=CheckStatus.PASS,
                message=f"All {len(available)} endpoints available",
                details={
                    "role": "fallback",
                    "security": "NO_AUTH",
                    "available": available,
                    "note": "Direct HTTP bypasses auth - use gRPC engine for production",
                },
            )

        except ImportError:
            return CheckResult(
                name="vLLM Service",
                status=CheckStatus.SKIP,
                message="httpx not available",
            )
        except Exception as e:
            return CheckResult(
                name="vLLM Service",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_qdrant(self) -> CheckResult:
        """Check Qdrant vector database connectivity.

        Qdrant is PRIMARY for:
        - Vector embeddings storage
        - Semantic search
        - Latent swarm working memory
        """
        import os

        try:
            import httpx

            url = os.getenv("QDRANT_URL", "http://localhost:6339")

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check health endpoint
                response = await client.get(f"{url}/healthz")
                if response.status_code != 200:
                    return CheckResult(
                        name="Qdrant",
                        status=CheckStatus.WARN,
                        message=f"Unhealthy response: {response.status_code}",
                        details={"url": url, "role": "primary"},
                        suggestion="Start Qdrant: devenv up qdrant",
                    )

                # Get collections info
                collections_resp = await client.get(f"{url}/collections")
                if collections_resp.status_code == 200:
                    data = collections_resp.json()
                    collections = data.get("result", {}).get("collections", [])
                    collection_names = [c.get("name") for c in collections]

                    return CheckResult(
                        name="Qdrant",
                        status=CheckStatus.PASS,
                        message=f"Connected, {len(collections)} collection(s)",
                        details={
                            "url": url,
                            "role": "primary",
                            "collections": collection_names,
                            "purpose": "Vector embeddings, semantic search, latent memory",
                        },
                    )

                return CheckResult(
                    name="Qdrant",
                    status=CheckStatus.PASS,
                    message="Connected",
                    details={"url": url, "role": "primary"},
                )

        except ImportError:
            return CheckResult(
                name="Qdrant",
                status=CheckStatus.SKIP,
                message="httpx not available",
            )
        except Exception as e:
            error_msg = str(e)
            if "Connection refused" in error_msg or "ConnectError" in error_msg:
                return CheckResult(
                    name="Qdrant",
                    status=CheckStatus.WARN,
                    message="Not reachable at localhost:6339",
                    details={"role": "primary"},
                    suggestion="Start Qdrant: devenv up qdrant",
                )
            return CheckResult(
                name="Qdrant",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_s3_minio(self) -> CheckResult:
        """Check S3/MinIO object storage connectivity.

        MinIO is PRIMARY for:
        - Artifact storage
        - Large document storage
        - Model weights caching
        """
        import os

        try:
            import httpx

            # MinIO API endpoint (not console)
            url = os.getenv("MINIO_ENDPOINT", "http://localhost:9010")

            async with httpx.AsyncClient(timeout=5.0) as client:
                # MinIO health check endpoint
                try:
                    response = await client.get(f"{url}/minio/health/live")
                    if response.status_code == 200:
                        # Try to get bucket list (may require auth)
                        return CheckResult(
                            name="S3/MinIO",
                            status=CheckStatus.PASS,
                            message=f"Connected at {url}",
                            details={
                                "url": url,
                                "role": "primary",
                                "purpose": "Object storage for artifacts, documents",
                            },
                        )
                except httpx.HTTPError:
                    pass

                # Try cluster health endpoint
                try:
                    response = await client.get(f"{url}/minio/health/cluster")
                    if response.status_code == 200:
                        return CheckResult(
                            name="S3/MinIO",
                            status=CheckStatus.PASS,
                            message=f"Cluster healthy at {url}",
                            details={
                                "url": url,
                                "role": "primary",
                                "purpose": "Object storage for artifacts, documents",
                            },
                        )
                except httpx.HTTPError:
                    pass

                # Check if port is open but service not responding properly
                try:
                    response = await client.get(url)
                    # MinIO returns various responses at root
                    if response.status_code in (200, 403, 400):
                        return CheckResult(
                            name="S3/MinIO",
                            status=CheckStatus.PASS,
                            message=f"Service responding at {url}",
                            details={
                                "url": url,
                                "role": "primary",
                                "purpose": "Object storage for artifacts, documents",
                            },
                        )
                except httpx.HTTPError:
                    pass

                return CheckResult(
                    name="S3/MinIO",
                    status=CheckStatus.WARN,
                    message=f"Not responding at {url}",
                    details={"url": url, "role": "primary"},
                    suggestion="Start MinIO: devenv up minio",
                )

        except ImportError:
            return CheckResult(
                name="S3/MinIO",
                status=CheckStatus.SKIP,
                message="httpx not available",
            )
        except Exception as e:
            error_msg = str(e)
            if "Connection refused" in error_msg or "ConnectError" in error_msg:
                return CheckResult(
                    name="S3/MinIO",
                    status=CheckStatus.WARN,
                    message="Not reachable at localhost:9010",
                    details={"role": "primary"},
                    suggestion="Start MinIO: devenv up minio",
                )
            return CheckResult(
                name="S3/MinIO",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    # =========================================================================
    # Additional Health Checks
    # =========================================================================

    async def _check_evolution_daemon_status(self) -> CheckResult:
        """Check evolution daemon status and cycle frequency."""
        try:
            from ..client.engine_proxy import get_evolution_proxy, use_engine_proxy

            if not use_engine_proxy():
                return CheckResult(
                    name="Evolution Daemon",
                    status=CheckStatus.WARN,
                    message="Engine not available",
                    suggestion="Run: /health fix engine",
                    heuristic_id="evolution/daemon_not_running",
                )

            evo = await get_evolution_proxy()
            status = await evo._get_status_async()

            is_running = status.get("running", False)
            cycles_completed = status.get("cycles_completed", 0)
            next_agent = status.get("next_agent", "unknown")

            if not is_running:
                return CheckResult(
                    name="Evolution Daemon",
                    status=CheckStatus.WARN,
                    message="Daemon not running",
                    details={
                        "running": False,
                        "cycles_completed": cycles_completed,
                    },
                    suggestion="Run: /health fix evolution",
                    heuristic_id="evolution/daemon_not_running",
                )

            return CheckResult(
                name="Evolution Daemon",
                status=CheckStatus.PASS,
                message=f"Running, {cycles_completed} cycles, next: {next_agent}",
                details={
                    "running": True,
                    "cycles_completed": cycles_completed,
                    "next_agent": next_agent,
                    "mode": status.get("mode", "unknown"),
                },
            )

        except Exception as e:
            return CheckResult(
                name="Evolution Daemon",
                status=CheckStatus.WARN,
                message=f"Status check failed: {str(e)[:80]}",
                suggestion="Run: /health fix evolution",
                heuristic_id="evolution/daemon_not_running",
            )

    async def _check_gpu_temperature(self) -> CheckResult:
        """Check GPU temperature levels."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return CheckResult(
                    name="GPU Temperature",
                    status=CheckStatus.SKIP,
                    message="nvidia-smi not available",
                )

            gpus = []
            warnings = []
            critical = []

            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    idx, temp = int(parts[0]), int(parts[1])
                    gpus.append({"id": idx, "temperature_c": temp})

                    if temp >= 85:
                        critical.append(f"GPU {idx}: {temp}°C")
                    elif temp >= 75:
                        warnings.append(f"GPU {idx}: {temp}°C")

            if critical:
                return CheckResult(
                    name="GPU Temperature",
                    status=CheckStatus.FAIL,
                    message=f"Critical: {', '.join(critical)}",
                    details={"gpus": gpus},
                    suggestion="Reduce GPU load or improve cooling",
                )

            if warnings:
                return CheckResult(
                    name="GPU Temperature",
                    status=CheckStatus.WARN,
                    message=f"Elevated: {', '.join(warnings)}",
                    details={"gpus": gpus},
                )

            max_temp = max((g["temperature_c"] for g in gpus), default=0)
            return CheckResult(
                name="GPU Temperature",
                status=CheckStatus.PASS,
                message=f"{len(gpus)} GPUs, max {max_temp}°C",
                details={"gpus": gpus},
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                name="GPU Temperature",
                status=CheckStatus.WARN,
                message="nvidia-smi timed out",
            )
        except FileNotFoundError:
            return CheckResult(
                name="GPU Temperature",
                status=CheckStatus.SKIP,
                message="nvidia-smi not found",
            )
        except Exception as e:
            return CheckResult(
                name="GPU Temperature",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_scheduler_queue(self) -> CheckResult:
        """Check scheduler queue depth and wait times."""
        try:
            from ..client.engine_proxy import get_scheduler_proxy, use_engine_proxy

            if not use_engine_proxy():
                return CheckResult(
                    name="Scheduler Queue",
                    status=CheckStatus.SKIP,
                    message="Engine not available",
                )

            scheduler = await get_scheduler_proxy()
            status = await scheduler._get_status_async()

            queue_depth = status.get("queue_depth", 0)
            pending_jobs = status.get("pending_jobs", 0)

            if queue_depth > 20:
                return CheckResult(
                    name="Scheduler Queue",
                    status=CheckStatus.WARN,
                    message=f"High queue depth: {queue_depth} jobs",
                    details={"queue_depth": queue_depth, "pending_jobs": pending_jobs},
                    suggestion="Consider scaling up endpoints or reducing load",
                )

            if queue_depth > 10:
                return CheckResult(
                    name="Scheduler Queue",
                    status=CheckStatus.WARN,
                    message=f"Elevated queue: {queue_depth} jobs",
                    details={"queue_depth": queue_depth, "pending_jobs": pending_jobs},
                )

            return CheckResult(
                name="Scheduler Queue",
                status=CheckStatus.PASS,
                message=f"Queue depth: {queue_depth}",
                details={"queue_depth": queue_depth, "pending_jobs": pending_jobs},
            )

        except Exception as e:
            return CheckResult(
                name="Scheduler Queue",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_xai_budget(self) -> CheckResult:
        """Check XAI API budget usage."""
        try:
            from ..client.engine_proxy import get_scheduler_proxy, use_engine_proxy

            if not use_engine_proxy():
                return CheckResult(
                    name="XAI Budget",
                    status=CheckStatus.SKIP,
                    message="Engine not available",
                )

            scheduler = await get_scheduler_proxy()
            budget = await scheduler._get_budget_async()

            daily_used = budget.get("daily_used", 0)
            daily_limit = budget.get("daily_limit", 50)
            weekly_used = budget.get("weekly_used", 0)
            weekly_limit = budget.get("weekly_limit", 200)

            daily_pct = (daily_used / daily_limit * 100) if daily_limit > 0 else 0
            weekly_pct = (weekly_used / weekly_limit * 100) if weekly_limit > 0 else 0

            details = {
                "daily_used": daily_used,
                "daily_limit": daily_limit,
                "daily_pct": f"{daily_pct:.0f}%",
                "weekly_used": weekly_used,
                "weekly_limit": weekly_limit,
                "weekly_pct": f"{weekly_pct:.0f}%",
            }

            if weekly_pct >= 90:
                return CheckResult(
                    name="XAI Budget",
                    status=CheckStatus.FAIL,
                    message=f"Weekly budget critical: {weekly_pct:.0f}%",
                    details=details,
                    suggestion="Evolution quality may degrade; consider resetting or waiting",
                )

            if daily_pct >= 80:
                return CheckResult(
                    name="XAI Budget",
                    status=CheckStatus.WARN,
                    message=f"Daily budget high: {daily_pct:.0f}%",
                    details=details,
                )

            return CheckResult(
                name="XAI Budget",
                status=CheckStatus.PASS,
                message=f"Daily: {daily_pct:.0f}%, Weekly: {weekly_pct:.0f}%",
                details=details,
            )

        except Exception as e:
            return CheckResult(
                name="XAI Budget",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_stale_processes(self) -> CheckResult:
        """Check for orphan vLLM processes not managed by engine."""
        try:
            # Get all vLLM processes
            result = subprocess.run(
                ["pgrep", "-f", "vllm.entrypoints"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            vllm_pids = set()
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        vllm_pids.add(int(line.strip()))

            if not vllm_pids:
                return CheckResult(
                    name="Stale Processes",
                    status=CheckStatus.PASS,
                    message="No vLLM processes running",
                    details={"vllm_process_count": 0},
                )

            # Get engine-managed processes
            try:
                from ..client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

                if use_engine_proxy():
                    orch = await get_orchestrator_proxy()
                    status = orch.get_status()  # synchronous method
                    managed_pids = set()

                    for ep_name, ep_info in status.get("endpoints", {}).items():
                        if isinstance(ep_info, dict) and ep_info.get("pid"):
                            managed_pids.add(ep_info["pid"])

                    orphan_pids = vllm_pids - managed_pids

                    if orphan_pids:
                        return CheckResult(
                            name="Stale Processes",
                            status=CheckStatus.WARN,
                            message=f"{len(orphan_pids)} orphan vLLM process(es)",
                            details={
                                "orphan_pids": list(orphan_pids),
                                "managed_pids": list(managed_pids),
                                "total_vllm": len(vllm_pids),
                            },
                            suggestion=f"Kill orphans: kill {' '.join(map(str, orphan_pids))}",
                        )

                    return CheckResult(
                        name="Stale Processes",
                        status=CheckStatus.PASS,
                        message=f"{len(vllm_pids)} vLLM processes, all managed",
                        details={
                            "vllm_process_count": len(vllm_pids),
                            "managed_pids": list(managed_pids),
                        },
                    )
            except Exception:
                pass

            # Can't verify against engine - just report count
            return CheckResult(
                name="Stale Processes",
                status=CheckStatus.PASS,
                message=f"{len(vllm_pids)} vLLM processes (engine status unavailable)",
                details={"vllm_process_count": len(vllm_pids), "pids": list(vllm_pids)},
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                name="Stale Processes",
                status=CheckStatus.WARN,
                message="pgrep timed out",
            )
        except FileNotFoundError:
            return CheckResult(
                name="Stale Processes",
                status=CheckStatus.SKIP,
                message="pgrep not available",
            )
        except Exception as e:
            return CheckResult(
                name="Stale Processes",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_endpoint_stuck(self) -> CheckResult:
        """Check for endpoints stuck in starting/stopping state.

        Timeouts (from orchestrator_service.py):
        - STARTING: 5 minutes (300s) - models need time to load
        - STOPPING: 2 minutes (120s) - shutdown should be quick
        """
        try:
            from ..client.engine_proxy import get_health_proxy, use_engine_proxy

            if not use_engine_proxy():
                return CheckResult(
                    name="Stuck Endpoints",
                    status=CheckStatus.SKIP,
                    message="Engine proxy not enabled",
                )

            # Use HealthProxy.check() which is properly async, instead of
            # OrchestratorProxy.get_status() which uses run_until_complete
            health = await get_health_proxy()
            status = await health.check()
            endpoints = status.get("endpoints", {})

            if not endpoints:
                return CheckResult(
                    name="Stuck Endpoints",
                    status=CheckStatus.PASS,
                    message="No endpoints configured",
                    details={"endpoint_count": 0},
                )

            # Thresholds for stuck detection
            STARTING_TIMEOUT_SECS = 300  # 5 minutes
            STOPPING_TIMEOUT_SECS = 120  # 2 minutes
            now = datetime.now()

            transitional = []  # Endpoints in transitional state (not yet stuck)
            stuck_critical = []  # Endpoints stuck past timeout (FAIL)

            for name, ep in endpoints.items():
                if isinstance(ep, dict):
                    ep_status = ep.get("status", "unknown")
                    if ep_status in ("starting", "stopping"):
                        started_at = ep.get("started_at")
                        elapsed_secs = 0
                        if started_at:
                            try:
                                start_time = datetime.fromisoformat(started_at)
                                elapsed_secs = (now - start_time).total_seconds()
                            except (ValueError, TypeError):
                                pass

                        timeout = STARTING_TIMEOUT_SECS if ep_status == "starting" else STOPPING_TIMEOUT_SECS
                        entry = {
                            "name": name,
                            "status": ep_status,
                            "elapsed_secs": int(elapsed_secs),
                            "timeout_secs": timeout,
                        }

                        if elapsed_secs > timeout:
                            stuck_critical.append(entry)
                        else:
                            transitional.append(entry)

            # Critical: endpoints stuck past timeout
            if stuck_critical:
                stuck_names = [s["name"] for s in stuck_critical]
                stopping_stuck = [s for s in stuck_critical if s["status"] == "stopping"]
                starting_stuck = [s for s in stuck_critical if s["status"] == "starting"]

                # Use specific heuristic based on stuck type
                # Maps to FMEA catalog: VLLM_001 (Stuck Starting), VLLM_002 (Stuck Stopping)
                heuristic = "inference/endpoint_stuck_stopping" if stopping_stuck else "inference/endpoint_stuck_starting"
                failure_mode = "VLLM_002" if stopping_stuck else "VLLM_001"

                return CheckResult(
                    name="Stuck Endpoints",
                    status=CheckStatus.FAIL,
                    message=f"{len(stuck_critical)} endpoint(s) stuck past timeout",
                    details={
                        "stuck_endpoints": stuck_critical,
                        "transitional_endpoints": transitional,
                        "total_endpoints": len(endpoints),
                        "failure_mode_id": failure_mode,  # FMEA catalog reference
                    },
                    heuristic_id=heuristic,
                    suggestion=f"Fix with: /health fix endpoints (force clean start) or kill stuck processes",
                )

            # Warning: endpoints in transitional state but not yet stuck
            if transitional:
                transitional_names = [s["name"] for s in transitional]
                return CheckResult(
                    name="Stuck Endpoints",
                    status=CheckStatus.WARN,
                    message=f"{len(transitional)} endpoint(s) in transitional state",
                    details={
                        "transitional_endpoints": transitional,
                        "total_endpoints": len(endpoints),
                    },
                    suggestion=f"Monitor: {transitional_names[0]} may be loading model",
                )

            return CheckResult(
                name="Stuck Endpoints",
                status=CheckStatus.PASS,
                message=f"All {len(endpoints)} endpoints in stable state",
                details={"endpoint_count": len(endpoints)},
            )

        except Exception as e:
            return CheckResult(
                name="Stuck Endpoints",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_routing_quality(self) -> CheckResult:
        """Check capability-based routing quality."""
        try:
            from ..storage.database import get_routing_summary

            summary = await get_routing_summary(hours=24)

            if "error" in summary:
                # Table might not exist yet
                if "does not exist" in str(summary.get("error", "")):
                    return CheckResult(
                        name="Model Routing",
                        status=CheckStatus.SKIP,
                        message="Routing analytics not yet configured",
                    )
                return CheckResult(
                    name="Model Routing",
                    status=CheckStatus.WARN,
                    message=f"Query failed: {summary['error'][:60]}",
                )

            total = summary.get("total_requests", 0)
            if total == 0:
                return CheckResult(
                    name="Model Routing",
                    status=CheckStatus.PASS,
                    message="No routing decisions recorded yet",
                    details={"total_requests": 0},
                )

            mismatch_rate = summary.get("mismatch_rate", 0)
            fallback_rate = summary.get("fallback_rate", 0)
            starved_agents = summary.get("starved_agents", [])
            capability_gaps = summary.get("capability_gaps", [])

            details = {
                "total_requests": total,
                "mismatch_rate": f"{mismatch_rate:.1%}",
                "fallback_rate": f"{fallback_rate:.1%}",
                "starved_agents": starved_agents,
                "top_capability_gaps": capability_gaps[:3] if capability_gaps else [],
            }

            # High mismatch or multiple starved agents
            if mismatch_rate > 0.5 or len(starved_agents) >= 3:
                return CheckResult(
                    name="Model Routing",
                    status=CheckStatus.WARN,
                    message=f"High mismatch: {mismatch_rate:.0%}, {len(starved_agents)} starved agents",
                    details=details,
                    suggestion="Consider deploying models with missing capabilities",
                )

            if mismatch_rate > 0.25 or len(starved_agents) >= 1:
                return CheckResult(
                    name="Model Routing",
                    status=CheckStatus.WARN,
                    message=f"Some mismatches: {mismatch_rate:.0%}",
                    details=details,
                )

            return CheckResult(
                name="Model Routing",
                status=CheckStatus.PASS,
                message=f"Routing quality good: {1-mismatch_rate:.0%} optimal",
                details=details,
            )

        except ImportError:
            return CheckResult(
                name="Model Routing",
                status=CheckStatus.SKIP,
                message="Routing analytics module not available",
            )
        except Exception as e:
            return CheckResult(
                name="Model Routing",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_rase_objectives(self) -> CheckResult:
        """Check RASE intrinsic verification components.

        Validates:
        - KB objectives directory exists and has objectives
        - KBOracle can be instantiated
        - Evidence capture is available
        - DaemonOracle is functional
        """
        start_time = time.time()

        try:
            from pathlib import Path

            kb_root = str(self.kb_root)
            objectives_dir = Path(kb_root) / "current" / "objectives"
            issues = []
            details = {}

            # Check objectives directory
            if not objectives_dir.exists():
                return CheckResult(
                    name="RASE Objectives",
                    status=CheckStatus.WARN,
                    message="Objectives directory not found",
                    details={"path": str(objectives_dir)},
                    suggestion="Run: /health fix rase",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # List objectives
            objectives = list(objectives_dir.glob("*.md"))
            details["objectives_count"] = len(objectives)
            details["objectives"] = [o.stem for o in objectives]

            if len(objectives) == 0:
                issues.append("No objectives defined")

            # Test KB domain imports
            try:
                from gaius.rase.domains.kb import KBState, KBOracle, Objective

                details["kb_imports"] = "ok"

                # Test KBState capture
                state = KBState.capture(kb_root, paths=None)
                details["kb_state_docs"] = len(state.documents)

                # Test KBOracle creation
                oracle = KBOracle(kb_root=kb_root, use_minio=False)
                details["kb_oracle"] = "ok"

            except ImportError as e:
                issues.append(f"KB domain import failed: {e}")
                details["kb_imports"] = str(e)
            except Exception as e:
                issues.append(f"KB component error: {e}")
                details["kb_error"] = str(e)

            # Test evolution daemon components
            try:
                from gaius.agents.evolution import (
                    get_daemon_oracle,
                    get_objective_generator,
                    get_calibration_oracle,
                )

                details["evolution_imports"] = "ok"

            except ImportError as e:
                issues.append(f"Evolution import failed: {e}")
                details["evolution_imports"] = str(e)

            # Test evidence capture
            try:
                from gaius.hx import get_evidence_capture

                capture = get_evidence_capture()
                details["evidence_capture"] = "ok"

            except ImportError as e:
                issues.append(f"Evidence capture import failed: {e}")
                details["evidence_imports"] = str(e)
            except Exception as e:
                # Non-critical - MinIO might not be available
                details["evidence_capture"] = f"warn: {e}"

            duration_ms = int((time.time() - start_time) * 1000)

            if issues:
                return CheckResult(
                    name="RASE Objectives",
                    status=CheckStatus.WARN,
                    message=f"{len(issues)} issue(s): {issues[0][:50]}",
                    details=details,
                    suggestion="Run: /health fix rase",
                    duration_ms=duration_ms,
                )

            return CheckResult(
                name="RASE Objectives",
                status=CheckStatus.PASS,
                message=f"{len(objectives)} objectives, components OK",
                details=details,
                duration_ms=duration_ms,
            )

        except Exception as e:
            return CheckResult(
                name="RASE Objectives",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
                suggestion="Run: /health fix rase",
            )

    # =========================================================================
    # Self-Healing Integration
    # =========================================================================

    def set_healing_coordinator(self, coordinator: "SelfHealingCoordinator") -> None:
        """Set the self-healing coordinator.

        Args:
            coordinator: SelfHealingCoordinator instance
        """
        self._healing_coordinator = coordinator
        logger.info("Self-healing coordinator attached to HealthChecker")

    async def _emit_issues_to_coordinator(self, results: list[CheckResult]) -> None:
        """Emit failed checks to self-healing coordinator.

        Args:
            results: List of check results
        """
        if not self._healing_coordinator:
            return

        from .self_healing import HealthIssue

        for result in results:
            if result.status != CheckStatus.FAIL:
                continue

            # Extract endpoint from details if available
            endpoint = result.details.get("endpoint")

            # For endpoint-related checks, try to extract affected endpoints
            if not endpoint:
                if "unhealthy" in result.details:
                    unhealthy_endpoints = result.details.get("unhealthy", [])
                    if unhealthy_endpoints:
                        # Emit an issue for each unhealthy endpoint
                        for ep in unhealthy_endpoints:
                            issue = HealthIssue(
                                endpoint=ep,
                                issue_type=result.status.value,
                                error_message=result.message,
                                check_name=result.name,
                                severity="critical",
                                context=result.details,
                            )
                            try:
                                await self._healing_coordinator.handle_health_issue(issue)
                            except Exception as e:
                                logger.error(f"Failed to emit issue to coordinator: {e}")
                        continue

            # Generic issue without specific endpoint
            if endpoint:
                issue = HealthIssue(
                    endpoint=endpoint,
                    issue_type=result.status.value,
                    error_message=result.message,
                    check_name=result.name,
                    severity="critical",
                    context=result.details,
                )
                try:
                    await self._healing_coordinator.handle_health_issue(issue)
                except Exception as e:
                    logger.error(f"Failed to emit issue to coordinator: {e}")

    async def _check_config_audit(self) -> CheckResult:
        """Audit configuration for port/URL mismatches.

        Detects common configuration issues:
        1. optillm: env var vs gunicorn bind port mismatch
        2. vLLM endpoints: configured URLs vs actual listening ports
        3. Database URLs: connectivity with configured credentials

        This check proactively identifies misconfigurations that cause
        confusing "not responding" errors when services are actually running.
        """
        import os
        import re
        import subprocess
        from pathlib import Path
        from urllib.parse import urlparse

        mismatches: list[dict] = []
        audited_configs: list[str] = []

        # 1. Check optillm port configuration
        try:
            optillm_url = os.getenv("GAIUS_OPTILLM_URL", "http://localhost:8000/v1")
            expected_port = urlparse(optillm_url).port or 8000

            # Check gunicorn config if it exists
            gunicorn_config = Path("/tmp/gaius/gunicorn_optillm.conf.py")
            if gunicorn_config.exists():
                config_text = gunicorn_config.read_text()
                # Extract bind port from gunicorn config
                bind_match = re.search(r'bind\s*=\s*["\'][\d.]+:(\d+)["\']', config_text)
                if bind_match:
                    actual_port = int(bind_match.group(1))
                    if actual_port != expected_port:
                        mismatches.append({
                            "service": "optillm",
                            "issue": "port_mismatch",
                            "expected": expected_port,
                            "actual": actual_port,
                            "env_var": "GAIUS_OPTILLM_URL",
                            "config_file": str(gunicorn_config),
                            "fix": f"export GAIUS_OPTILLM_URL=http://localhost:{actual_port}/v1",
                        })
                    audited_configs.append(f"optillm:gunicorn={actual_port}")
                else:
                    audited_configs.append("optillm:gunicorn=parse_error")
            else:
                # Check if optillm is running and what port it's listening on
                try:
                    result = subprocess.run(
                        ["ss", "-tlnp"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    # Look for gunicorn listening ports
                    for line in result.stdout.split("\n"):
                        if "gunicorn" in line:
                            port_match = re.search(r":(\d+)\s", line)
                            if port_match:
                                actual_port = int(port_match.group(1))
                                if actual_port != expected_port and actual_port in [8000, 8080]:
                                    mismatches.append({
                                        "service": "optillm",
                                        "issue": "port_mismatch",
                                        "expected": expected_port,
                                        "actual": actual_port,
                                        "env_var": "GAIUS_OPTILLM_URL",
                                        "fix": f"export GAIUS_OPTILLM_URL=http://localhost:{actual_port}/v1",
                                    })
                                audited_configs.append(f"optillm:ss={actual_port}")
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

        except Exception as e:
            logger.debug(f"optillm config audit failed: {e}")

        # 2. Check vLLM endpoint configuration
        vllm_endpoints = [
            ("thinking", os.getenv("GAIUS_VLLM_THINKING_URL", "http://localhost:8081/v1")),
            ("reasoning", os.getenv("GAIUS_VLLM_REASONING_URL", "http://localhost:8083/v1")),
        ]
        for name, url in vllm_endpoints:
            port = urlparse(url).port
            if port:
                audited_configs.append(f"vllm_{name}:{port}")

        # 3. Check database URL format
        try:
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            if db_url:
                parsed = urlparse(db_url)
                audited_configs.append(f"postgres:{parsed.port or 5432}")
        except Exception:
            pass

        # Generate result
        if mismatches:
            return CheckResult(
                name="Config Audit",
                status=CheckStatus.WARN,
                message=f"{len(mismatches)} config mismatch(es) detected",
                details={
                    "mismatches": mismatches,
                    "audited": audited_configs,
                },
                suggestion=f"/health fix config or: {mismatches[0].get('fix', 'check heuristic')}",
            )

        return CheckResult(
            name="Config Audit",
            status=CheckStatus.PASS,
            message=f"Audited {len(audited_configs)} config(s), no mismatches",
            details={"audited": audited_configs},
        )

    # =========================================================================
    # Content Pipeline Health Checks
    # =========================================================================

    async def _check_pipeline_status(self) -> CheckResult:
        """Check content pipeline stage health.

        Queries v_pipeline_status view to monitor:
        - fetch: Feed/arxiv fetch jobs
        - heuristic_triage: Fast keyword scoring
        - llm_triage: LLM quality assessment
        - kb_write: Writing triaged content to KB
        """
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()

            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                # Check if the view exists (migration may not have run)
                view_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.views
                        WHERE table_schema = 'public' AND table_name = 'v_pipeline_status'
                    )
                """)

                if not view_exists:
                    await conn.close()
                    return CheckResult(
                        name="Pipeline Status",
                        status=CheckStatus.SKIP,
                        message="Pipeline monitoring not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                # Query pipeline status
                rows = await conn.fetch("SELECT * FROM v_pipeline_status")
                await conn.close()

                stages = {}
                warnings = []
                failures = []

                for row in rows:
                    stage = row["stage"]
                    pending = row["pending"]
                    completed_1h = row["completed_1h"]
                    warn_threshold = row.get("backlog_warn", 100)
                    critical_threshold = row.get("backlog_critical", 500)

                    stages[stage] = {
                        "pending": pending,
                        "completed_1h": completed_1h,
                    }

                    if pending >= critical_threshold:
                        failures.append(f"{stage}: {pending} pending (critical)")
                    elif pending >= warn_threshold:
                        warnings.append(f"{stage}: {pending} pending")

                if failures:
                    return CheckResult(
                        name="Pipeline Status",
                        status=CheckStatus.FAIL,
                        message=f"Pipeline backlog critical: {failures[0]}",
                        details={"stages": stages, "issues": failures},
                        suggestion="Run: /health fix pipeline",
                    )

                if warnings:
                    return CheckResult(
                        name="Pipeline Status",
                        status=CheckStatus.WARN,
                        message=f"Pipeline backlog elevated: {warnings[0]}",
                        details={"stages": stages, "issues": warnings},
                        suggestion="Triage tasks will process backlog automatically",
                    )

                # Calculate total throughput
                total_completed = sum(s.get("completed_1h", 0) for s in stages.values())
                return CheckResult(
                    name="Pipeline Status",
                    status=CheckStatus.PASS,
                    message=f"Pipeline healthy, {total_completed} items processed in last hour",
                    details={"stages": stages},
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Pipeline Status",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str:
                return CheckResult(
                    name="Pipeline Status",
                    status=CheckStatus.SKIP,
                    message="Pipeline views not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Pipeline Status",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_task_queue(self) -> CheckResult:
        """Check for stalled or stuck scheduled tasks.

        Queries v_task_watchdog view to detect:
        - stale_pending: Tasks waiting too long to be picked up
        - stuck_running: Tasks running too long without completion
        """
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()

            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                # Check if the view exists
                view_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.views
                        WHERE table_schema = 'public' AND table_name = 'v_task_watchdog'
                    )
                """)

                if not view_exists:
                    # Fall back to direct query
                    stale = await conn.fetchval("""
                        SELECT COUNT(*) FROM scheduled_tasks
                        WHERE picked_up_at IS NULL
                          AND scheduled_for < NOW() - interval '30 minutes'
                    """)
                    stuck = await conn.fetchval("""
                        SELECT COUNT(*) FROM scheduled_tasks
                        WHERE picked_up_at IS NOT NULL
                          AND completed_at IS NULL
                          AND picked_up_at < NOW() - interval '10 minutes'
                    """)
                    completed_1h = await conn.fetchval("""
                        SELECT COUNT(*) FROM scheduled_tasks
                        WHERE completed_at > NOW() - interval '1 hour'
                    """)
                    await conn.close()

                    if stale > 0 or stuck > 0:
                        return CheckResult(
                            name="Task Queue",
                            status=CheckStatus.WARN if (stale + stuck) < 5 else CheckStatus.FAIL,
                            message=f"{stale} stale, {stuck} stuck tasks",
                            details={
                                "stale_pending": stale,
                                "stuck_running": stuck,
                                "completed_1h": completed_1h,
                            },
                            suggestion="Run: /health fix pipeline",
                        )

                    return CheckResult(
                        name="Task Queue",
                        status=CheckStatus.PASS,
                        message=f"Task queue healthy, {completed_1h} completed in last hour",
                        details={
                            "stale_pending": 0,
                            "stuck_running": 0,
                            "completed_1h": completed_1h,
                        },
                    )

                # Query task watchdog view
                rows = await conn.fetch("SELECT * FROM v_task_watchdog")
                await conn.close()

                task_types = {}
                total_stale = 0
                total_stuck = 0
                total_completed = 0
                total_failed = 0

                for row in rows:
                    task_type = row["task_type"]
                    stale = row["stale_pending"]
                    stuck = row["stuck_running"]
                    completed = row["completed_1h"]
                    failed = row.get("failed_24h", 0)

                    task_types[task_type] = {
                        "stale_pending": stale,
                        "stuck_running": stuck,
                        "completed_1h": completed,
                        "failed_24h": failed,
                    }

                    total_stale += stale
                    total_stuck += stuck
                    total_completed += completed
                    total_failed += failed

                if total_stale > 0 or total_stuck > 0:
                    severity = CheckStatus.FAIL if (total_stale + total_stuck) >= 5 else CheckStatus.WARN
                    issues = []
                    if total_stale > 0:
                        issues.append(f"{total_stale} stale")
                    if total_stuck > 0:
                        issues.append(f"{total_stuck} stuck")

                    return CheckResult(
                        name="Task Queue",
                        status=severity,
                        message=f"Task queue issues: {', '.join(issues)}",
                        details={
                            "task_types": task_types,
                            "stale_total": total_stale,
                            "stuck_total": total_stuck,
                            "completed_1h": total_completed,
                            "failed_24h": total_failed,
                        },
                        suggestion="Run: /health fix pipeline",
                    )

                return CheckResult(
                    name="Task Queue",
                    status=CheckStatus.PASS,
                    message=f"Task queue healthy, {total_completed} completed in last hour",
                    details={
                        "task_types": task_types,
                        "completed_1h": total_completed,
                        "failed_24h": total_failed,
                    },
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Task Queue",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            return CheckResult(
                name="Task Queue",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_landing_page_pipeline(self) -> CheckResult:
        """Check landing page pipeline health.

        Monitors article curation and card publishing pipeline:
        - Task failures in last 24h (zero tolerance - any failure = WARN)
        - Cards published today vs expected (~6/day)
        - Curations this week vs expected (~4-5/week)
        - Current backlog level

        Any non-zero error rate surfaces as WARN for investigation.
        """
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()

            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                # Check if collections schema exists
                schema_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'collections'
                    )
                """)

                if not schema_exists:
                    await conn.close()
                    return CheckResult(
                        name="Landing Page",
                        status=CheckStatus.SKIP,
                        message="Collections schema not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                # Count task failures in last 24h. Ground truth is the
                # `error` column — task handlers never write a
                # result->>'success' key, so the old predicate was
                # permanently NULL and this check sat green while the
                # live site aged (found 2026-09-01). Watchdog resets
                # leave completed_at NULL, so failures are counted from
                # created_at, not completed_at.
                curate_failures = await conn.fetchval("""
                    SELECT COUNT(*) FROM scheduled_tasks
                    WHERE task_type = 'article_curate'
                      AND created_at > NOW() - interval '24 hours'
                      AND error IS NOT NULL
                """) or 0

                publish_failures = await conn.fetchval("""
                    SELECT COUNT(*) FROM scheduled_tasks
                    WHERE task_type = 'publish_cards'
                      AND created_at > NOW() - interval '24 hours'
                      AND error IS NOT NULL
                """) or 0

                # Get cards published in last 24h
                cards_today = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE published_at > NOW() - interval '24 hours'
                """) or 0

                # Get curations in last 7 days (clean completions)
                curations_week = await conn.fetchval("""
                    SELECT COUNT(*) FROM scheduled_tasks
                    WHERE task_type = 'article_curate'
                      AND completed_at > NOW() - interval '7 days'
                      AND error IS NULL
                """) or 0

                # Get current pending backlog
                pending_cards = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards c
                    JOIN collections.collections col ON c.collection_id = col.collection_id
                    WHERE col.featured = TRUE AND c.status = 'pending'
                """) or 0

                await conn.close()

                # Any failure = FAIL (pipeline errors degrade the live site)
                if curate_failures > 0 or publish_failures > 0:
                    return CheckResult(
                        name="Landing Page",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000007.EMPTYBACKLOG: Pipeline errors: {curate_failures} curate, {publish_failures} publish failures (24h)",
                        details={
                            "curate_failures": curate_failures,
                            "publish_failures": publish_failures,
                            "cards_published_today": cards_today,
                            "curations_this_week": curations_week,
                            "pending_cards": pending_cards,
                        },
                        suggestion="Run: /health fix pipeline",
                    )

                # All operational metrics in details
                details = {
                    "cards_published_today": cards_today,
                    "curations_this_week": curations_week,
                    "pending_cards": pending_cards,
                    "expected_cards_per_day": 6,
                    "expected_curations_per_week": 4,
                }

                # Empty backlog = pipeline has stopped feeding the site
                if pending_cards == 0:
                    return CheckResult(
                        name="Landing Page",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000007.EMPTYBACKLOG: {cards_today} cards today, {curations_week} curations/week, 0 pending",
                        details=details,
                        suggestion="Run article curation to replenish backlog:\n  uv run gaius-cli --cmd \"/curate\"",
                    )

                return CheckResult(
                    name="Landing Page",
                    status=CheckStatus.PASS,
                    message=f"Pipeline OK: {cards_today} cards today, {curations_week}/wk, {pending_cards} pending",
                    details=details,
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Landing Page",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str:
                return CheckResult(
                    name="Landing Page",
                    status=CheckStatus.SKIP,
                    message="Landing page tables not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Landing Page",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_periodic_task_freshness(self) -> CheckResult:
        """Check periodic task completion cadence.

        Answers: "Are my periodic processes actually completing on their
        expected cadence?"  Uses _PERIODIC_TASK_CADENCES to compare last
        successful completion time against expected intervals.

        Ratio thresholds:
          <= 1.0  → current (ok)
          1–3×    → overdue (WARN)
          > 3×    → critically overdue (FAIL)

        Task types not present in scheduled_tasks are silently skipped
        (no false positives for features not yet exercised).
        """
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                rows = await conn.fetch("""
                    SELECT
                        task_type,
                        MAX(completed_at) FILTER (WHERE error IS NULL) AS last_success,
                        COUNT(*) FILTER (WHERE completed_at IS NULL) AS pending,
                        COUNT(*) FILTER (WHERE error IS NOT NULL
                                         AND completed_at > NOW() - interval '7 days') AS errors_7d
                    FROM scheduled_tasks
                    GROUP BY task_type
                """)
                await conn.close()
            except Exception as e:
                await conn.close()
                raise e

            from datetime import timezone

            now = datetime.now(timezone.utc)
            task_details: dict[str, dict[str, Any]] = {}
            worst = CheckStatus.PASS
            summary_parts: list[str] = []

            for row in rows:
                task_type = row["task_type"]
                if task_type not in _PERIODIC_TASK_CADENCES:
                    continue  # fail-open: skip unknown types

                expected_interval, label, hint = _PERIODIC_TASK_CADENCES[task_type]
                last_success = row["last_success"]
                pending = row["pending"]
                errors_7d = row["errors_7d"]

                if last_success is None:
                    status = "fail"
                    age_str = "never"
                    worst = CheckStatus.FAIL
                    summary_parts.append(f"{label} NEVER")
                else:
                    # Ensure tz-aware comparison
                    if last_success.tzinfo is None:
                        last_success = last_success.replace(tzinfo=timezone.utc)
                    age = now - last_success

                    ratio = age / expected_interval
                    age_str = _format_timedelta(age)

                    if ratio <= 1.0:
                        status = "ok"
                    elif ratio <= 3.0:
                        status = "warn"
                        summary_parts.append(f"{label} {age_str}")
                        if worst == CheckStatus.PASS:
                            worst = CheckStatus.WARN
                    else:
                        status = "fail"
                        summary_parts.append(f"{label} {age_str}")
                        worst = CheckStatus.FAIL

                entry: dict[str, Any] = {
                    "status": status,
                    "last_success": str(last_success) if last_success else None,
                    "age": age_str,
                    "expected_interval": _format_timedelta(expected_interval),
                    "pending": pending,
                    "errors_7d": errors_7d,
                }
                if status != "ok":
                    entry["hint"] = hint
                if errors_7d > 0:
                    entry["note"] = f"{errors_7d} errors in last 7d"
                task_details[task_type] = entry

            if not task_details:
                return CheckResult(
                    name="Periodic Tasks",
                    status=CheckStatus.SKIP,
                    message="No periodic tasks found in scheduled_tasks table",
                )

            if worst == CheckStatus.PASS:
                message = f"All {len(task_details)} periodic tasks current"
            elif worst == CheckStatus.WARN:
                message = f"Overdue: {', '.join(summary_parts)}"
            else:
                message = f"Critically overdue: {', '.join(summary_parts)}"

            return CheckResult(
                name="Periodic Tasks",
                status=worst,
                message=message,
                details={"tasks": task_details},
                suggestion="Engine must be running: devenv processes up" if worst != CheckStatus.PASS else None,
            )

        except asyncio.TimeoutError:
            return CheckResult(
                name="Periodic Tasks",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str:
                return CheckResult(
                    name="Periodic Tasks",
                    status=CheckStatus.SKIP,
                    message="scheduled_tasks table not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Periodic Tasks",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    # =========================================================================
    # Site Content Completeness Checks
    # =========================================================================

    async def _check_site_card_images(self) -> CheckResult:
        """Check all published cards have LuxCore visualization images."""
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                schema_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'collections'
                    )
                """)

                if not schema_exists:
                    await conn.close()
                    return CheckResult(
                        name="Card Images",
                        status=CheckStatus.SKIP,
                        message="Collections schema not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                total = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE status = 'published'
                """) or 0

                missing = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE status = 'published'
                      AND (image_url IS NULL OR image_url = '')
                """) or 0

                missing_ids = []
                if missing > 0:
                    rows = await conn.fetch("""
                        SELECT card_id FROM collections.cards
                        WHERE status = 'published'
                          AND (image_url IS NULL OR image_url = '')
                        LIMIT 20
                    """)
                    missing_ids = [row["card_id"] for row in rows]

                await conn.close()

                if missing > 0:
                    return CheckResult(
                        name="Card Images",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000001.NOIMAGES: {missing}/{total} published cards missing images",
                        details={
                            "total_published": total,
                            "missing_images": missing,
                            "affected_cards": missing_ids,
                        },
                        suggestion="Run: scripts/backfill_card_images.sh --all\n  Then: uv run python scripts/remediate_card_summaries.py  (to sync KV)",
                    )

                return CheckResult(
                    name="Card Images",
                    status=CheckStatus.PASS,
                    message=f"All {total} published cards have images",
                    details={"total_published": total},
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Card Images",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            if "does not exist" in str(e):
                return CheckResult(
                    name="Card Images",
                    status=CheckStatus.SKIP,
                    message="Cards table not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Card Images",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_site_card_summaries(self) -> CheckResult:
        """Check published cards have the required local open-weights panel.

        Brave and Cerebras panels vary with API/budget and are not a FAIL.
        """
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                schema_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'collections'
                    )
                """)

                if not schema_exists:
                    await conn.close()
                    return CheckResult(
                        name="Card Summaries",
                        status=CheckStatus.SKIP,
                        message="Collections schema not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                rows = await conn.fetch("""
                    WITH card_summary_counts AS (
                        SELECT
                            c.card_id,
                            COUNT(*) FILTER (WHERE cs.summary_type = 'frontier') AS has_frontier,
                            COUNT(*) FILTER (WHERE cs.summary_type = 'open_weights') AS has_open_weights,
                            COUNT(*) FILTER (WHERE cs.summary_type = 'cerebras') AS has_cerebras
                        FROM collections.cards c
                        LEFT JOIN collections.card_summaries cs ON c.card_id = cs.card_id
                        WHERE c.status = 'published'
                        GROUP BY c.card_id
                    )
                    SELECT
                        card_id,
                        has_frontier,
                        has_open_weights,
                        has_cerebras
                    FROM card_summary_counts
                    WHERE has_open_weights = 0
                    LIMIT 20
                """)

                total = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE status = 'published'
                """) or 0

                await conn.close()

                if rows:
                    missing_ow = sum(1 for r in rows if r["has_open_weights"] == 0)
                    affected_cards = [r["card_id"] for r in rows]

                    return CheckResult(
                        name="Card Summaries",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000002.NOSUMMARIES: {len(rows)} cards missing local open-weights",
                        details={
                            "total_published": total,
                            "incomplete_cards": len(rows),
                            "missing_open_weights": missing_ow,
                            "affected_cards": affected_cards,
                        },
                        suggestion="Run: uv run python scripts/remediate_card_summaries.py",
                    )

                return CheckResult(
                    name="Card Summaries",
                    status=CheckStatus.PASS,
                    message=f"All {total} published cards have local open-weights summaries",
                    details={"total_published": total},
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Card Summaries",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            if "does not exist" in str(e):
                return CheckResult(
                    name="Card Summaries",
                    status=CheckStatus.SKIP,
                    message="Card summaries table not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Card Summaries",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_site_card_briefs(self) -> CheckResult:
        """Check all published cards have unique, substantive brief text."""
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                schema_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'collections'
                    )
                """)

                if not schema_exists:
                    await conn.close()
                    return CheckResult(
                        name="Card Briefs",
                        status=CheckStatus.SKIP,
                        message="Collections schema not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                total = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE status = 'published'
                """) or 0

                short_briefs = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE status = 'published'
                      AND (summary IS NULL OR LENGTH(TRIM(summary)) < 20)
                """) or 0

                duplicate_rows = await conn.fetch("""
                    SELECT summary, COUNT(*) as cnt
                    FROM collections.cards
                    WHERE status = 'published'
                      AND summary IS NOT NULL
                      AND LENGTH(TRIM(summary)) >= 20
                    GROUP BY summary
                    HAVING COUNT(*) > 1
                    LIMIT 10
                """)
                duplicate_count = sum(r["cnt"] for r in duplicate_rows)

                # Formulaic suffix detection — LLM-generated relevance
                # justifications that make briefs feel robotic
                formulaic_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM collections.cards
                    WHERE status = 'published'
                      AND summary IS NOT NULL
                      AND summary ~* '(Relevant to AI|Key relevance:|Key for AI)'
                """) or 0

                await conn.close()

                issues = []
                details: dict[str, Any] = {"total_published": total}

                if short_briefs > 0:
                    issues.append(f"{short_briefs} short/empty briefs")
                    details["short_briefs"] = short_briefs

                if duplicate_count > 0:
                    issues.append(f"{duplicate_count} cards with duplicate briefs")
                    details["duplicate_briefs"] = duplicate_count
                    details["duplicate_examples"] = [
                        r["summary"][:60] for r in duplicate_rows[:3]
                    ]

                if formulaic_count > 0:
                    pct = 100 * formulaic_count / total if total else 0
                    issues.append(f"{formulaic_count}/{total} ({pct:.0f}%) with formulaic suffixes")
                    details["formulaic_briefs"] = formulaic_count
                    details["formulaic_pct"] = round(pct, 1)

                if issues:
                    return CheckResult(
                        name="Card Briefs",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000003.BRIEFS: {', '.join(issues)}",
                        details=details,
                        suggestion="Fix briefs in DB then re-sync KV:\n  uv run python scripts/remediate_card_summaries.py",
                    )

                return CheckResult(
                    name="Card Briefs",
                    status=CheckStatus.PASS,
                    message=f"All {total} published card briefs are unique and substantive",
                    details=details,
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Card Briefs",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            if "does not exist" in str(e):
                return CheckResult(
                    name="Card Briefs",
                    status=CheckStatus.SKIP,
                    message="Cards table not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Card Briefs",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_site_collection_completeness(self) -> CheckResult:
        """Check featured collection has published cards and frontier+open_weights."""
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                schema_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'collections'
                    )
                """)

                if not schema_exists:
                    await conn.close()
                    return CheckResult(
                        name="Collection Completeness",
                        status=CheckStatus.SKIP,
                        message="Collections schema not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                rows = await conn.fetch("""
                    SELECT
                        col.collection_id,
                        col.slug,
                        COUNT(DISTINCT c.card_id) FILTER (WHERE c.status = 'published') AS published_cards,
                        COUNT(DISTINCT cs.card_id) FILTER (WHERE cs.summary_type = 'frontier') AS has_frontier,
                        COUNT(DISTINCT cs.card_id) FILTER (WHERE cs.summary_type = 'open_weights') AS has_open_weights,
                        COUNT(DISTINCT cs.card_id) FILTER (WHERE cs.summary_type = 'cerebras') AS has_cerebras
                    FROM collections.collections col
                    LEFT JOIN collections.cards c ON col.collection_id = c.collection_id
                    LEFT JOIN collections.card_summaries cs ON c.card_id = cs.card_id
                    WHERE col.featured = TRUE
                    GROUP BY col.collection_id, col.slug
                """)

                await conn.close()

                incomplete = []
                for row in rows:
                    issues = []
                    if row["published_cards"] == 0:
                        issues.append("no published cards")
                    else:
                        if row["has_open_weights"] < row["published_cards"]:
                            issues.append(f"open_weights: {row['has_open_weights']}/{row['published_cards']}")
                    if issues:
                        incomplete.append({
                            "slug": row["slug"],
                            "published_cards": row["published_cards"],
                            "issues": issues,
                        })

                if incomplete:
                    return CheckResult(
                        name="Collection Completeness",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000004.INCOMPLETE: {len(incomplete)}/{len(rows)} featured collections incomplete",
                        details={
                            "total_collections": len(rows),
                            "incomplete": incomplete[:20],
                        },
                        suggestion="Run: uv run python scripts/remediate_card_summaries.py",
                    )

                return CheckResult(
                    name="Collection Completeness",
                    status=CheckStatus.PASS,
                    message=f"All {len(rows)} featured collections complete",
                    details={"total_collections": len(rows)},
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Collection Completeness",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            if "does not exist" in str(e):
                return CheckResult(
                    name="Collection Completeness",
                    status=CheckStatus.SKIP,
                    message="Collections tables not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Collection Completeness",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_site_live_verification(self) -> CheckResult:
        """Verify live site renders content correctly.

        Three probes:
        1. Landing page — GET https://gaius.zndx.org/
        2. Sample card page — most recently published card
        3. Image URL — HEAD request to card's image_url
        """
        try:
            import httpx
        except ImportError:
            return CheckResult(
                name="Live Site",
                status=CheckStatus.SKIP,
                message="httpx not available",
            )

        details: dict[str, Any] = {}

        try:
            import asyncpg

            from ..core.config import get_database_url

            # Get sample card from DB for probes 2 and 3
            db_url = get_database_url()
            sample_card = None
            try:
                conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)
                try:
                    row = await conn.fetchrow("""
                        SELECT card_id, title, image_url
                        FROM collections.cards
                        WHERE status = 'published'
                        ORDER BY published_at DESC NULLS LAST
                        LIMIT 1
                    """)
                    if row:
                        sample_card = {
                            "card_id": row["card_id"],
                            "title": row["title"],
                            "image_url": row["image_url"],
                        }
                    await conn.close()
                except Exception:
                    await conn.close()
            except Exception:
                pass  # DB unavailable — still try landing page probe

            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                # Probe 1: Landing page
                try:
                    resp = await client.get("https://gaius.zndx.org/")
                    details["landing_status"] = resp.status_code
                    if resp.status_code == 200:
                        body = resp.text
                        has_title = "<title>" in body.lower() or "<title " in body.lower()
                        has_card_links = "/cards/card_" in body
                        details["landing_has_title"] = has_title
                        details["landing_has_card_links"] = has_card_links
                        if not has_card_links:
                            details["landing_issue"] = "No card links found on landing page"
                    else:
                        details["landing_issue"] = f"HTTP {resp.status_code}"
                except Exception as e:
                    details["landing_status"] = "error"
                    details["landing_issue"] = str(e)[:80]

                # Probe 2: Sample card page
                if sample_card:
                    details["card_id_tested"] = sample_card["card_id"]
                    try:
                        card_url = f"https://gaius.zndx.org/cards/{sample_card['card_id']}"
                        resp = await client.get(card_url)
                        details["card_page_status"] = resp.status_code
                        if resp.status_code == 200:
                            body = resp.text
                            has_image = "viz.gaius.zndx.org" in body
                            details["card_has_image_ref"] = has_image
                            # KV coherence: DB has image_url but rendered page doesn't show it
                            if sample_card.get("image_url") and not has_image:
                                details["kv_stale_issue"] = (
                                    f"KV stale: DB has image_url but card page missing image "
                                    f"(card {sample_card['card_id']})"
                                )
                        else:
                            details["card_page_issue"] = f"HTTP {resp.status_code}"
                    except Exception as e:
                        details["card_page_status"] = "error"
                        details["card_page_issue"] = str(e)[:80]

                    # Probe 3: Image URL — verify R2 asset exists
                    if sample_card.get("image_url"):
                        try:
                            resp = await client.head(sample_card["image_url"])
                            details["image_status"] = resp.status_code
                            content_type = resp.headers.get("content-type", "")
                            details["image_content_type"] = content_type
                            if resp.status_code != 200:
                                details["image_issue"] = f"HTTP {resp.status_code}"
                            elif "image/" not in content_type:
                                details["image_issue"] = f"Unexpected content-type: {content_type}"
                        except Exception as e:
                            details["image_status"] = "error"
                            details["image_issue"] = str(e)[:80]

            # Determine overall status
            issues = [v for k, v in details.items() if k.endswith("_issue")]

            if details.get("landing_status") == "error" and not sample_card:
                return CheckResult(
                    name="Live Site",
                    status=CheckStatus.SKIP,
                    message="Site unreachable (external network may be unavailable)",
                    details=details,
                )

            if issues:
                return CheckResult(
                    name="Live Site",
                    status=CheckStatus.FAIL,
                    message=f"#SITE.00000005.LIVEFAIL: {'; '.join(str(i) for i in issues[:3])}",
                    details=details,
                    suggestion="Re-sync KV: uv run python scripts/remediate_card_summaries.py",
                )

            return CheckResult(
                name="Live Site",
                status=CheckStatus.PASS,
                message="Live site verified (landing + card page + image)",
                details=details,
            )

        except Exception as e:
            return CheckResult(
                name="Live Site",
                status=CheckStatus.SKIP,
                message=f"Verification skipped: {str(e)[:80]}",
                details=details,
            )

    async def _check_site_content_freshness(self) -> CheckResult:
        """Check that the site is receiving new published cards at expected cadence.

        The site decays in relevance if no new content is being produced.
        This check detects a stalled content pipeline by looking at card
        creation timestamps — the most direct signal of pipeline health.
        """
        try:
            import asyncpg

            from ..core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncio.wait_for(asyncpg.connect(db_url), timeout=5)

            try:
                schema_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.schemata
                        WHERE schema_name = 'collections'
                    )
                """)

                if not schema_exists:
                    await conn.close()
                    return CheckResult(
                        name="Content Freshness",
                        status=CheckStatus.SKIP,
                        message="Collections schema not configured (run migration)",
                        suggestion="Run: dbmate up",
                    )

                row = await conn.fetchrow("""
                    SELECT
                        MAX(created_at) AS last_created,
                        COUNT(*) FILTER (
                            WHERE created_at > NOW() - interval '48 hours'
                        ) AS cards_48h,
                        COUNT(*) FILTER (
                            WHERE created_at > NOW() - interval '7 days'
                        ) AS cards_7d,
                        COUNT(*) AS total_published
                    FROM collections.cards
                    WHERE status = 'published'
                """)

                await conn.close()

                if not row or row["total_published"] == 0:
                    return CheckResult(
                        name="Content Freshness",
                        status=CheckStatus.FAIL,
                        message="#SITE.00000006.STALE: No published cards exist",
                        suggestion="Run article curation: uv run gaius-cli --cmd \"/curate\"",
                    )

                last_created = row["last_created"]
                cards_48h = row["cards_48h"] or 0
                cards_7d = row["cards_7d"] or 0
                total = row["total_published"]

                # Calculate age of most recent card
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                age = now - last_created.replace(tzinfo=timezone.utc) if last_created.tzinfo is None else now - last_created
                age_hours = age.total_seconds() / 3600
                age_days = age.total_seconds() / 86400

                if age_days >= 1:
                    age_str = f"{age_days:.1f}d"
                else:
                    age_str = f"{age_hours:.1f}h"

                details = {
                    "total_published": total,
                    "last_card_created": last_created.isoformat(),
                    "last_card_age": age_str,
                    "cards_last_48h": cards_48h,
                    "cards_last_7d": cards_7d,
                }

                # No cards in 48h = pipeline stalled
                if cards_48h == 0:
                    return CheckResult(
                        name="Content Freshness",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000006.STALE: No new cards in {age_str} (last: {last_created.strftime('%Y-%m-%d')})",
                        details=details,
                        suggestion="Content pipeline stalled. Run article curation:\n  uv run gaius-cli --cmd \"/curate\"",
                    )

                # Less than 1 card/day average over the week
                if cards_7d < 7:
                    return CheckResult(
                        name="Content Freshness",
                        status=CheckStatus.FAIL,
                        message=f"#SITE.00000006.STALE: Only {cards_7d} cards in 7d ({cards_7d/7:.1f}/day, expected >= 1/day)",
                        details=details,
                        suggestion="Content cadence below minimum. Run article curation:\n  uv run gaius-cli --cmd \"/curate\"",
                    )

                return CheckResult(
                    name="Content Freshness",
                    status=CheckStatus.PASS,
                    message=f"Content fresh: {cards_48h} cards in 48h, {cards_7d} in 7d (last: {age_str} ago)",
                    details=details,
                )

            except Exception as e:
                await conn.close()
                raise e

        except asyncio.TimeoutError:
            return CheckResult(
                name="Content Freshness",
                status=CheckStatus.FAIL,
                message="Database connection timeout",
                suggestion="Check PostgreSQL is running",
            )
        except Exception as e:
            if "does not exist" in str(e):
                return CheckResult(
                    name="Content Freshness",
                    status=CheckStatus.SKIP,
                    message="Cards table not yet created",
                    suggestion="Run: dbmate up",
                )
            return CheckResult(
                name="Content Freshness",
                status=CheckStatus.FAIL,
                message=f"Check failed: {str(e)[:80]}",
            )

    async def _check_metaflow_stack(self) -> CheckResult:
        """Validate the full Metaflow pipeline stack.

        Validates four layers:
        1. meta.flow_runs table accessible (DB → Metaflow schema)
        2. Engine dispatch readiness (gRPC reachable, task processor active)
        3. Metaflow service reachable (HTTP health check)
        4. Recent flow success rate above threshold
        """
        import os

        issues: list[str] = []
        details: dict[str, Any] = {"endpoint": "metaflow_stack"}

        # 1. Query meta.flow_runs for recent stats
        try:
            from ..engine.services.metaflow_query import get_metaflow_client

            client = get_metaflow_client()
            stats = await client.get_flow_stats(hours=24)

            if "error" in stats:
                issues.append(f"Flow query failed: {stats['error'][:60]}")
            else:
                details["flow_stats_24h"] = stats
                total_runs = stats.get("total_runs", 0)
                success_pct = stats.get("success_rate_pct", 0.0)

                if total_runs == 0:
                    issues.append("No flow runs in last 24h")
                elif success_pct < 80.0:
                    issues.append(
                        f"Flow success rate {success_pct:.0f}% (last 24h, {total_runs} runs)"
                    )

        except Exception as e:
            issues.append(f"Cannot query meta.flow_runs: {str(e)[:60]}")

        # 1b. Engine dispatch readiness — verify the gRPC engine is running
        # and the ScheduledTaskProcessor is picking up tasks.
        # This is the critical bridge: pg_cron → engine → Metaflow.
        try:
            from ..client.engine_proxy import use_engine_proxy

            if not use_engine_proxy():
                issues.append("Engine not reachable (flow dispatch blocked)")
                details["engine_dispatch"] = "engine_unreachable"
            else:
                details["engine_dispatch"] = "engine_reachable"

                # Verify task processor is picking up work by checking
                # scheduled_tasks for recent pickup activity.  If pg_cron
                # inserts tasks but nothing picks them up, the processor
                # is stalled.
                from ..storage.database import get_pool

                pool = await get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow("""
                            SELECT
                                COUNT(*) FILTER (
                                    WHERE picked_up_at >= NOW() - INTERVAL '1 hour'
                                ) AS picked_up_1h,
                                COUNT(*) FILTER (
                                    WHERE picked_up_at IS NULL
                                      AND scheduled_for < NOW() - INTERVAL '10 minutes'
                                ) AS stale_pending
                            FROM scheduled_tasks
                            WHERE scheduled_for >= NOW() - INTERVAL '2 hours'
                        """)
                    picked_up = row["picked_up_1h"] or 0
                    stale = row["stale_pending"] or 0
                    details["task_processor"] = {
                        "picked_up_1h": picked_up,
                        "stale_pending": stale,
                    }
                    if stale > 0 and picked_up == 0:
                        issues.append(
                            f"Task processor stalled: {stale} tasks pending, "
                            f"none picked up in 1h"
                        )
        except Exception as e:
            issues.append(f"Engine dispatch check failed: {str(e)[:60]}")

        # 2. Metaflow service HTTP health check
        service_url = os.environ.get("METAFLOW_SERVICE_URL", "http://localhost:30180")
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{service_url}/flows",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        issues.append(
                            f"Metaflow service returned {resp.status}"
                        )
                    else:
                        details["metaflow_service"] = "reachable"
        except ImportError:
            # aiohttp not available — try urllib
            try:
                import urllib.request

                req = urllib.request.Request(f"{service_url}/flows", method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status != 200:
                        issues.append(f"Metaflow service returned {resp.status}")
                    else:
                        details["metaflow_service"] = "reachable"
            except Exception as e:
                issues.append(f"Metaflow service unreachable: {str(e)[:60]}")
        except Exception as e:
            issues.append(f"Metaflow service unreachable: {str(e)[:60]}")

        # 3. K8s cluster reachability
        # Canonical KUBECONFIG path — matches devenv.nix enterShell and all
        # process scripts in scripts/processes/*.sh. The system KUBECONFIG
        # (/etc/rancher/rke2/rke2.yaml) is root-owned and unreadable.
        import pathlib

        canonical_kubeconfig = pathlib.Path.home() / ".config" / "kube" / "rke2.yaml"
        system_kubeconfig = pathlib.Path("/etc/rancher/rke2/rke2.yaml")

        if not canonical_kubeconfig.is_file():
            issues.append(
                "KUBECONFIG not found at ~/.config/kube/rke2.yaml"
            )
            details["k8s_cluster"] = "no_kubeconfig"
            details["k8s_remediation"] = "just kubeconfig-sync"
        elif not os.access(str(canonical_kubeconfig), os.R_OK):
            issues.append(
                "KUBECONFIG at ~/.config/kube/rke2.yaml is not readable"
            )
            details["k8s_cluster"] = "kubeconfig_unreadable"
            details["k8s_remediation"] = "chmod 600 ~/.config/kube/rke2.yaml"
        else:
            # Check if user copy is stale vs system copy
            if system_kubeconfig.is_file():
                try:
                    sys_mtime = system_kubeconfig.stat().st_mtime
                    usr_mtime = canonical_kubeconfig.stat().st_mtime
                    if sys_mtime > usr_mtime:
                        details["k8s_kubeconfig_stale"] = True
                        details["k8s_stale_remediation"] = "just kubeconfig-sync"
                except OSError:
                    pass  # Can't stat system file — not critical
            kubectl_env = {**os.environ, "KUBECONFIG": str(canonical_kubeconfig)}
            try:
                proc = await asyncio.create_subprocess_exec(
                    "kubectl", "cluster-info",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=kubectl_env,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode != 0:
                    err_msg = stderr.decode()[:60] if stderr else "unknown error"
                    if details.get("k8s_kubeconfig_stale"):
                        issues.append(
                            "K8s unreachable (kubeconfig may be stale — "
                            "run: just kubeconfig-sync)"
                        )
                    else:
                        issues.append(f"K8s cluster unreachable: {err_msg}")
                else:
                    details["k8s_cluster"] = "reachable"
                    details["kubeconfig"] = str(canonical_kubeconfig)

                    # 3b. Check Metaflow pod status (cluster is reachable)
                    try:
                        pod_proc = await asyncio.create_subprocess_exec(
                            "kubectl", "get", "pods",
                            "-l", "app.kubernetes.io/name=metaflow-service",
                            "--no-headers",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=kubectl_env,
                        )
                        pod_stdout, _ = await asyncio.wait_for(
                            pod_proc.communicate(), timeout=10
                        )
                        pod_output = pod_stdout.decode().strip()
                        if not pod_output:
                            issues.append(
                                "No metaflow-service pods found in K8s"
                            )
                            details["metaflow_pods"] = "missing"
                        else:
                            pod_statuses = []
                            for line in pod_output.splitlines():
                                parts = line.split()
                                if len(parts) >= 3:
                                    pod_statuses.append(
                                        {"name": parts[0], "ready": parts[1], "status": parts[2]}
                                    )
                            details["metaflow_pods"] = pod_statuses
                            # Detect bad pod states
                            bad_states = {"CrashLoopBackOff", "Error", "Unknown", "ImagePullBackOff"}
                            for ps in pod_statuses:
                                if ps["status"] in bad_states:
                                    issues.append(
                                        f"Metaflow pod {ps['name']}: {ps['status']}"
                                    )
                    except (asyncio.TimeoutError, Exception):
                        pass  # Pod check is supplementary — don't fail on it

                    # 3c. Check CoreDNS status (DNS is required for all K8s services)
                    try:
                        dns_proc = await asyncio.create_subprocess_exec(
                            "kubectl", "get", "pods",
                            "-n", "kube-system",
                            "-l", "k8s-app=kube-dns",
                            "--no-headers",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=kubectl_env,
                        )
                        dns_stdout, _ = await asyncio.wait_for(
                            dns_proc.communicate(), timeout=10
                        )
                        dns_output = dns_stdout.decode().strip()
                        if dns_output:
                            for line in dns_output.splitlines():
                                parts = line.split()
                                if len(parts) >= 3 and parts[2] in {"CrashLoopBackOff", "Error", "Unknown"}:
                                    issues.append(
                                        f"CoreDNS pod {parts[0]}: {parts[2]} — "
                                        f"K8s DNS broken, pods cannot resolve service names"
                                    )
                                    details["coredns_status"] = parts[2]
                                    details["coredns_remediation"] = (
                                        "Edit CoreDNS ConfigMap to remove DNS loop: "
                                        "kubectl -n kube-system edit configmap rke2-coredns-rke2-coredns"
                                    )
                    except (asyncio.TimeoutError, Exception):
                        pass  # CoreDNS check is supplementary

            except FileNotFoundError:
                issues.append("kubectl not found in PATH")
            except asyncio.TimeoutError:
                issues.append("K8s cluster-info timed out (10s)")
            except Exception as e:
                issues.append(f"K8s check failed: {str(e)[:60]}")

        # Compose result
        if not issues:
            return CheckResult(
                name="Metaflow Stack",
                status=CheckStatus.PASS,
                message="Metaflow stack healthy (engine, DB, service, K8s all reachable)",
                details=details,
            )

        # Single non-critical issue (e.g. low success rate) → WARN
        if len(issues) == 1 and "success rate" in issues[0]:
            return CheckResult(
                name="Metaflow Stack",
                status=CheckStatus.WARN,
                message=issues[0],
                details=details,
                suggestion="Check recent flow failures: uv run gaius-cli --cmd \"/metaflow status\"",
            )

        return CheckResult(
            name="Metaflow Stack",
            status=CheckStatus.FAIL,
            message=f"#MF.00000003.STACKDOWN: {'; '.join(issues)}",
            details=details,
            suggestion="Check K8s cluster and Metaflow service: /health fix metaflow",
        )
