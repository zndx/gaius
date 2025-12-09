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
from typing import TYPE_CHECKING, Any, Optional

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
    def status_emoji(self) -> str:
        """Status indicator emoji."""
        if self.failures > 0:
            return "🔴"
        if self.warnings > 0:
            return "🟡"
        return "🟢"

    def summary(self) -> str:
        """Generate summary string."""
        total = len(self.checks)
        return (
            f"{self.status_emoji} Health: {self.passed}/{total} passed, "
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
        ]

    async def run_all(self) -> HealthReport:
        """Run all health checks.

        Returns:
            Comprehensive health report
        """
        start_time = time.time()
        results = []
        metrics = {}

        for check in self._checks:
            result = await self._run_check(check)
            results.append(result)

            # Stop on critical failure
            if check.critical and result.status == CheckStatus.FAIL:
                logger.warning(f"Critical check failed: {check.name}")
                # Mark remaining as skipped
                for remaining in self._checks[self._checks.index(check) + 1 :]:
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

    async def run_category(self, category: str) -> HealthReport:
        """Run health checks for a specific category.

        Args:
            category: Category name (engine, data, cognition, inference)

        Returns:
            Health report for that category
        """
        start_time = time.time()
        results = []

        for check in self._checks:
            if check.category == category:
                result = await self._run_check(check)
                results.append(result)

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

    async def run_quick(self) -> HealthReport:
        """Run essential service connectivity checks.

        Shows all primary services and their roles:
        - gRPC Engine: Orchestration, cognition, evolution (primary)
        - optillm: Inference with optimization techniques (primary)
        - vLLM: Direct inference fallback
        - PostgreSQL: Activity logs, state (critical)
        - Qdrant: Vector embeddings, semantic search (primary)
        - S3/MinIO: Object storage (primary)

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

        for check in self._checks:
            if check.id in essential_ids:
                result = await self._run_check(check)
                results.append(result)

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
            healthy = sum(1 for e in endpoints.values() if isinstance(e, dict) and e.get("status") == "healthy")

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
                unhealthy = [name for name, e in endpoints.items() if isinstance(e, dict) and e.get("status") != "healthy"]
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

                    if mem_pct > 95:
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

            url = os.getenv("GAIUS_OPTILLM_URL", "http://localhost:8080/v1")
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

            url = os.getenv("QDRANT_URL", "http://localhost:6333")

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
                    message="Not reachable at localhost:6333",
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
            url = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")

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
                    message="Not reachable at localhost:9000",
                    details={"role": "primary"},
                    suggestion="Start MinIO: devenv up minio",
                )
            return CheckResult(
                name="S3/MinIO",
                status=CheckStatus.WARN,
                message=f"Check failed: {str(e)[:80]}",
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
