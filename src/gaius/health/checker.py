"""Health checker that applies heuristics to diagnose system state.

Provides comprehensive health diagnostics including:
- Engine connectivity and status
- Inference endpoint health
- Database connectivity
- Cognition daemon status
- Resource utilization
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

if TYPE_CHECKING:
    from .self_healing import SelfHealingCoordinator

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a health check."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    heuristic_id: Optional[str] = None
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
    critical: bool = False  # If True, failure stops further checks


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
        return (
            f"{self.status_indicator} Health: {self.passed}/{total} passed, "
            f"{self.warnings} warnings, {self.failures} failures"
        )


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
                critical=False,  # Not critical - inference has fallback paths
            ),
            HealthCheck(
                id="engine_endpoints",
                name="Engine Endpoints",
                category="engine",
                description="vLLM endpoints managed by engine",
                check_fn="_check_endpoints",
                heuristic_id="inference/endpoint_unhealthy",
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
                critical=True,
            ),
            HealthCheck(
                id="qdrant_service",
                name="Qdrant",
                category="data",
                description="Primary: Vector embeddings, semantic search, latent memory",
                check_fn="_check_qdrant",
            ),
            HealthCheck(
                id="s3_minio_service",
                name="S3/MinIO",
                category="data",
                description="Primary: Object storage for artifacts, large documents",
                check_fn="_check_s3_minio",
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
        ]

    async def run_all(
        self,
        progress_callback: Optional[Callable[["CheckResult", int, int], Awaitable[None]]] = None,
    ) -> HealthReport:
        """Run all health checks with optional progress reporting.

        Args:
            progress_callback: Called after each check with (result, completed, total)

        Returns:
            Comprehensive health report
        """
        start_time = time.time()
        results = []
        metrics = {}
        total_checks = len(self._checks)

        for i, check in enumerate(self._checks):
            result = await self._run_check(check)
            results.append(result)

            # Report progress if callback provided
            if progress_callback:
                await progress_callback(result, i + 1, total_checks)

            # Stop on critical failure
            if check.critical and result.status == CheckStatus.FAIL:
                logger.warning(f"Critical check failed: {check.name}")
                # Mark remaining as skipped
                for remaining in self._checks[i + 1 :]:
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
            "grpc_connection",      # gRPC to engine
            "optillm_service",      # Primary inference
            "vllm_service",         # Fallback inference
            "database_connection",  # PostgreSQL (critical)
            "qdrant_service",       # Vector DB
            "s3_minio_service",     # Object storage
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

            return CheckResult(
                name="Engine Endpoints",
                status=CheckStatus.PASS,
                message=f"All {total} endpoints healthy",
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
            import os

            import asyncpg

            db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

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
                suggestion="Check PostgreSQL is running: pg_isready -p 5438",
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
                    suggestion="Start optillm: devenv up optillm",
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
                ("reasoning", os.getenv("GAIUS_VLLM_REASONING_URL", "http://localhost:8081/v1")),
                ("coding", os.getenv("GAIUS_VLLM_CODING_URL", "http://localhost:8082/v1")),
                ("fast", os.getenv("GAIUS_VLLM_FAST_URL", "http://localhost:8083/v1")),
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
                    status = await orch.get_status()
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
            ("reasoning", os.getenv("GAIUS_VLLM_REASONING_URL", "http://localhost:8081/v1")),
            ("coding", os.getenv("GAIUS_VLLM_CODING_URL", "http://localhost:8082/v1")),
            ("fast", os.getenv("GAIUS_VLLM_FAST_URL", "http://localhost:8083/v1")),
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
            import os

            import asyncpg

            db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

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
            import os

            import asyncpg

            db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

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
