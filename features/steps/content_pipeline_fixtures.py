"""Content pipeline test fixtures for BDD testing.

This module provides test infrastructure for end-to-end content pipeline testing,
including:
- PipelineTestConfig: Configuration dataclass for test isolation
- InfrastructureManager: Start/stop postgres, aeron, engine without devenv
- TestDatabaseManager: Tracking and cleanup of test data
- ServiceLifecycleManager: Service startup/shutdown in dependency order
- KBFixtureManager: Per-scenario KB isolation
- InferenceFixtureManager: Inference endpoint availability checks

The pipeline flows:
  fetch → heuristic_triage → llm_triage → kb_creation → qwq_reflection → evolution

Tier Architecture:
- Tier 1: DB only (fetch, basic triage)
- Tier 2: DB + KB (content processing, markdown generation)
- Tier 3: DB + KB + Inference (LLM triage, fast model)
- Tier 4: Full pipeline (QwQ reasoning, 4-GPU deployment)
- Tier 5: + Evolution (agent optimization)

Standalone Execution (without devenv):
  The InfrastructureManager can start required services directly when
  devenv process-compose is not running.
"""

import asyncio
import logging
import os
import shutil
import signal
import socket
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PipelineTestConfig:
    """Configuration for content pipeline E2E tests.

    Provides isolation settings and timeouts for each test scenario.

    Database URLs:
    - devenv postgres: postgresql://rch@localhost:5438/zndx_gaius (uses system user)
    - System postgres: postgresql://gaius:gaius@localhost:5432/gaius

    MinIO/S3 Configuration:
    - Test bucket: zndx-gaius-test (separate from production zndx-gaius)
    - Per-scenario prefix: hx-test/{scenario_id}/
    """

    # Database connection (defaults to devenv postgres on port 5438)
    # Note: devenv postgres uses the system user (rch), not 'postgres'
    db_url: str = field(default_factory=lambda: os.environ.get(
        "GAIUS_DATABASE_URL",
        "postgresql://rch@localhost:5438/zndx_gaius"
    ))

    # Project root for finding config files
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)

    # KB root for isolation
    kb_root: Path = field(default_factory=lambda: Path("build/test"))

    # Unique scenario ID for data isolation
    scenario_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # MinIO/S3 configuration for test isolation
    minio_endpoint: str = field(default_factory=lambda: os.environ.get(
        "GAIUS_MINIO_ENDPOINT", "localhost:9010"
    ))
    minio_bucket: str = "zndx-gaius-test"  # Dedicated test bucket
    minio_access_key: str = field(default_factory=lambda: os.environ.get(
        "GAIUS_MINIO_ACCESS_KEY", "minioadmin"
    ))
    minio_secret_key: str = field(default_factory=lambda: os.environ.get(
        "GAIUS_MINIO_SECRET_KEY", "minioadmin"
    ))

    # Inference endpoints
    qwq_endpoint: str = "http://localhost:8081"
    optillm_endpoint: str = "http://localhost:8000"
    fast_endpoint: str = "http://localhost:8083"

    # Timeouts
    service_start_timeout: float = 30.0
    job_completion_timeout: float = 60.0
    qwq_startup_timeout: float = 180.0  # QwQ takes longer with 4-GPU tensor parallel
    postgres_start_timeout: float = 30.0

    # Triage configuration
    heuristic_score_threshold: int = 30
    combined_score_threshold: int = 50

    @property
    def scenario_kb_root(self) -> Path:
        """Get isolated KB root for this scenario."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.kb_root / "scratch" / today / self.scenario_id

    @property
    def scenario_minio_prefix(self) -> str:
        """Get isolated MinIO prefix for this scenario."""
        today = datetime.now().strftime("%Y-%m-%d")
        return f"hx-test/{today}/{self.scenario_id}/"

    @property
    def postgres_port(self) -> int:
        """Extract port from db_url."""
        # Parse port from URL like postgresql://user@host:port/db
        if ":5438" in self.db_url:
            return 5438
        elif ":5432" in self.db_url:
            return 5432
        return 5438  # Default to devenv port


# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure Manager (for standalone execution without devenv)
# ─────────────────────────────────────────────────────────────────────────────


class InfrastructureManager:
    """Manages infrastructure services via devenv process-compose.

    Can start/stop via devenv:
    - PostgreSQL
    - MinIO (S3-compatible storage)
    - Aeron media driver
    - Gaius engine
    - Worker pool

    Uses devenv process-compose for reliable service lifecycle management.
    Falls back to direct process control when devenv is unavailable.
    """

    def __init__(self, config: PipelineTestConfig):
        self.config = config
        self._postgres_process: Optional[subprocess.Popen] = None
        self._aeron_process: Optional[subprocess.Popen] = None
        self._engine_process: Optional[subprocess.Popen] = None
        self._started_services: list[str] = []

    def _devenv_up(self, service: str) -> bool:
        """Start a service via devenv process-compose."""
        try:
            result = subprocess.run(
                ["devenv", "processes", "up", service, "-d"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.config.project_root),
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"devenv up {service} failed: {e}")
            return False

    def _devenv_stop(self, service: str) -> bool:
        """Stop a service via devenv process-compose."""
        try:
            result = subprocess.run(
                ["devenv", "processes", "stop", service],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.config.project_root),
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"devenv stop {service} failed: {e}")
            return False

    def is_postgres_running(self) -> bool:
        """Check if postgres is running on configured port."""
        try:
            with socket.create_connection(("localhost", self.config.postgres_port), timeout=2):
                return True
        except (socket.error, socket.timeout):
            return False

    def is_aeron_running(self) -> bool:
        """Check if Aeron media driver is running."""
        aeron_dir = Path("/dev/shm/gaius-aeron")
        return (aeron_dir / "cnc.dat").exists()

    def is_minio_running(self) -> bool:
        """Check if MinIO is running on configured port."""
        try:
            # MinIO runs on port 9010 by default in devenv
            host, port = self.config.minio_endpoint.split(":")
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except (socket.error, socket.timeout, ValueError):
            return False

    async def start_minio(self) -> bool:
        """Start MinIO via devenv if not running."""
        if self.is_minio_running():
            logger.info(f"MinIO already running on {self.config.minio_endpoint}")
            return True

        logger.info("Starting MinIO via devenv...")
        if self._devenv_up("minio"):
            # Wait for MinIO to be ready
            for _ in range(10):
                await asyncio.sleep(1)
                if self.is_minio_running():
                    self._started_services.append("minio")
                    logger.info("MinIO started successfully")
                    return True

        logger.error("MinIO failed to start")
        return False

    async def start_postgres(self) -> bool:
        """Start postgres if not running.

        Tries devenv postgres first, falls back to detecting system postgres.
        """
        if self.is_postgres_running():
            logger.info(f"PostgreSQL already running on port {self.config.postgres_port}")
            return True

        # Try to start via devenv
        devenv_state = self.config.project_root / ".devenv" / "state"
        pg_data = devenv_state / "postgres"

        if pg_data.exists():
            logger.info("Starting PostgreSQL via devenv...")
            try:
                # Use pg_ctl to start postgres
                result = subprocess.run(
                    [
                        "pg_ctl", "start",
                        "-D", str(pg_data),
                        "-l", str(pg_data / "postgres.log"),
                        "-o", f"-p {self.config.postgres_port}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    # Wait for postgres to be ready
                    for _ in range(int(self.config.postgres_start_timeout)):
                        if self.is_postgres_running():
                            self._started_services.append("postgres")
                            logger.info("PostgreSQL started successfully")
                            return True
                        await asyncio.sleep(1)
                else:
                    logger.warning(f"pg_ctl start failed: {result.stderr}")
            except Exception as e:
                logger.warning(f"Failed to start postgres via pg_ctl: {e}")

        # Check if system postgres has our database
        if self._check_system_postgres():
            logger.info("Using system PostgreSQL")
            return True

        logger.error("PostgreSQL not available")
        return False

    def _check_system_postgres(self) -> bool:
        """Check if system postgres has gaius database."""
        try:
            result = subprocess.run(
                ["pg_isready", "-h", "localhost", "-p", "5432"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def start_aeron(self) -> bool:
        """Start Aeron media driver if not running."""
        if self.is_aeron_running():
            logger.info("Aeron media driver already running")
            return True

        logger.info("Starting Aeron media driver...")
        aeron_dir = Path("/dev/shm/gaius-aeron")

        # Clean up stale directory
        if aeron_dir.exists():
            shutil.rmtree(aeron_dir)

        try:
            env = os.environ.copy()
            env["AERON_DIR"] = str(aeron_dir)

            self._aeron_process = subprocess.Popen(
                ["aeronmd"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )

            # Wait for cnc.dat
            for _ in range(10):
                if self.is_aeron_running():
                    self._started_services.append("aeron")
                    logger.info("Aeron media driver started")
                    return True
                await asyncio.sleep(1)

            logger.error("Aeron media driver failed to start")
            return False

        except FileNotFoundError:
            logger.warning("aeronmd not found - Aeron IPC disabled")
            return False
        except Exception as e:
            logger.error(f"Failed to start Aeron: {e}")
            return False

    async def start_engine(self) -> bool:
        """Start gaius-engine daemon."""
        logger.info("Starting gaius-engine...")

        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = ""
            env["OPTILLM_API_KEY"] = env.get("OPTILLM_API_KEY", "gaius-local-key")
            env["OPENAI_API_KEY"] = env.get("OPTILLM_API_KEY", "gaius-local-key")

            venv_python = self.config.project_root / ".devenv" / "state" / "venv" / "bin" / "python"

            self._engine_process = subprocess.Popen(
                [str(venv_python), "-m", "gaius.engine", "--config", "config/agents.conf"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                cwd=str(self.config.project_root),
            )

            # Wait for engine to be ready (check gRPC port)
            for _ in range(int(self.config.service_start_timeout)):
                try:
                    with socket.create_connection(("localhost", 50051), timeout=1):
                        self._started_services.append("engine")
                        logger.info("Gaius engine started")
                        return True
                except socket.error:
                    await asyncio.sleep(1)

            logger.error("Gaius engine failed to start")
            return False

        except Exception as e:
            logger.error(f"Failed to start engine: {e}")
            return False

    async def ensure_infrastructure(self, services: list[str] = None) -> dict:
        """Ensure required infrastructure is running.

        Args:
            services: List of services to ensure
                     ["postgres", "minio", "aeron", "engine", "worker"]
                     Default: ["postgres"]

        Returns:
            Dict with status of each service
        """
        if services is None:
            services = ["postgres"]

        results = {}

        if "postgres" in services:
            results["postgres"] = await self.start_postgres()

        if "minio" in services:
            results["minio"] = await self.start_minio()

        if "aeron" in services:
            results["aeron"] = await self.start_aeron()

        if "engine" in services:
            # Engine requires aeron
            if not self.is_aeron_running():
                await self.start_aeron()
            results["engine"] = await self.start_engine()

        if "worker" in services:
            # Worker pool via devenv
            results["worker"] = self._devenv_up("worker-pool")

        return results

    async def stop_infrastructure(self) -> None:
        """Stop services we started."""
        # Stop in reverse order
        for service in reversed(self._started_services):
            if service == "engine" and self._engine_process:
                logger.info("Stopping gaius-engine...")
                self._engine_process.terminate()
                try:
                    self._engine_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._engine_process.kill()
                self._engine_process = None

            elif service == "aeron" and self._aeron_process:
                logger.info("Stopping Aeron media driver...")
                self._aeron_process.terminate()
                try:
                    self._aeron_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._aeron_process.kill()
                self._aeron_process = None

            elif service == "postgres":
                logger.info("Stopping PostgreSQL...")
                pg_data = self.config.project_root / ".devenv" / "state" / "postgres"
                if pg_data.exists():
                    subprocess.run(
                        ["pg_ctl", "stop", "-D", str(pg_data), "-m", "fast"],
                        capture_output=True,
                        timeout=10,
                    )

        self._started_services.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Database Manager
# ─────────────────────────────────────────────────────────────────────────────


class TestDatabaseManager:
    """Manages test data creation and cleanup with FK-aware ordering.

    Tracks all test data by scenario ID for proper cleanup.
    Cleanup order (reverse FK): items → jobs → sources
    """

    def __init__(self, db_url: str, scenario_id: str):
        self.db_url = db_url
        self.scenario_id = scenario_id
        self._pool: Optional[Any] = None
        self._created_sources: list[str] = []
        self._created_jobs: list[str] = []
        self._created_items: list[str] = []
        self._created_assessments: list[str] = []

    async def connect(self) -> bool:
        """Connect to database."""
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(self.db_url)
            return True
        except Exception as e:
            print(f"Database connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from database."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def create_test_source(
        self,
        name: str,
        source_type: str,
        url: str,
    ) -> int:
        """Create a test feed source.

        Matches actual schema:
        - id: SERIAL (auto-increment integer)
        - name: text
        - source_type: source_type enum
        - base_url: text (not 'url')
        - active: boolean (not 'enabled')

        Returns:
            Source ID (integer)
        """
        if not self._pool:
            raise RuntimeError("Not connected to database")

        # Add scenario ID to name for test isolation
        test_name = f"{name}-{self.scenario_id}"
        async with self._pool.acquire() as conn:
            source_id = await conn.fetchval(
                """
                INSERT INTO feed_sources (name, source_type, base_url, active)
                VALUES ($1, $2, $3, true)
                RETURNING id
                """,
                test_name,
                source_type,
                url,
            )
        self._created_sources.append(source_id)
        return source_id

    async def create_test_job(
        self,
        source_id: int,
        status: str = "running",
    ) -> int:
        """Create a test fetch job.

        Matches actual schema:
        - id: SERIAL (auto-increment integer)
        - source_id: integer FK
        - status: text (default 'running')

        Returns:
            Job ID (integer)
        """
        if not self._pool:
            raise RuntimeError("Not connected to database")

        async with self._pool.acquire() as conn:
            job_id = await conn.fetchval(
                """
                INSERT INTO fetch_jobs (source_id, status)
                VALUES ($1, $2)
                RETURNING id
                """,
                source_id,
                status,
            )
        self._created_jobs.append(job_id)
        return job_id

    async def create_test_content_item(
        self,
        source_id: int,
        title: str,
        summary: str = "",
        external_id: Optional[str] = None,
        iceberg_id: Optional[str] = None,
    ) -> int:
        """Create a test content item.

        Matches actual schema:
        - id: SERIAL (auto-increment integer)
        - source_id: integer FK
        - title: text
        - summary: text
        - external_id: text (for dedup)
        - iceberg_id: text (for raw content reference)

        Returns:
            Content item ID (integer)
        """
        if not self._pool:
            raise RuntimeError("Not connected to database")

        # Generate external_id if not provided (for uniqueness)
        if external_id is None:
            external_id = f"test-{self.scenario_id}-{uuid.uuid4().hex[:8]}"

        async with self._pool.acquire() as conn:
            item_id = await conn.fetchval(
                """
                INSERT INTO content_items
                    (source_id, title, summary, external_id, iceberg_id)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                source_id,
                title,
                summary,
                external_id,
                iceberg_id,
            )
        self._created_items.append(item_id)
        return item_id

    async def get_content_items_by_score(
        self,
        min_score: int,
        score_field: str = "combined_score",
    ) -> list[dict]:
        """Get content items with score above threshold."""
        if not self._pool:
            raise RuntimeError("Not connected to database")

        # For combined score, we compute heuristic + llm
        if score_field == "combined_score":
            query = """
                SELECT id, title, source_id, heuristic_score, llm_quality_score,
                       COALESCE(heuristic_score, 0) + COALESCE(llm_quality_score, 0) as combined_score
                FROM content_items
                WHERE id LIKE $1
                  AND COALESCE(heuristic_score, 0) + COALESCE(llm_quality_score, 0) >= $2
                ORDER BY combined_score DESC
            """
        else:
            query = f"""
                SELECT id, title, source_id, heuristic_score, llm_quality_score
                FROM content_items
                WHERE id LIKE $1 AND {score_field} >= $2
                ORDER BY {score_field} DESC
            """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, f"%{self.scenario_id}%", min_score)
            return [dict(row) for row in rows]

    async def cleanup(self) -> dict:
        """Clean up all test data in reverse FK order.

        Returns:
            Dict with cleanup counts
        """
        if not self._pool:
            return {"error": "Not connected"}

        counts = {
            "assessments": 0,
            "items": 0,
            "jobs": 0,
            "sources": 0,
        }

        async with self._pool.acquire() as conn:
            # Assessments first (FK to items)
            if self._created_assessments:
                result = await conn.execute(
                    "DELETE FROM triage_assessments WHERE id = ANY($1)",
                    self._created_assessments,
                )
                counts["assessments"] = len(self._created_assessments)

            # Items (FK to sources)
            if self._created_items:
                result = await conn.execute(
                    "DELETE FROM content_items WHERE id = ANY($1)",
                    self._created_items,
                )
                counts["items"] = len(self._created_items)

            # Jobs (FK to sources)
            if self._created_jobs:
                result = await conn.execute(
                    "DELETE FROM fetch_jobs WHERE id = ANY($1)",
                    self._created_jobs,
                )
                counts["jobs"] = len(self._created_jobs)

            # Sources last
            if self._created_sources:
                result = await conn.execute(
                    "DELETE FROM feed_sources WHERE id = ANY($1)",
                    self._created_sources,
                )
                counts["sources"] = len(self._created_sources)

        return counts


# ─────────────────────────────────────────────────────────────────────────────
# Service Lifecycle Manager
# ─────────────────────────────────────────────────────────────────────────────


class ServiceLifecycleManager:
    """Manages service startup/shutdown in dependency order.

    Start order:  orchestrator → worker_pool → content_processor → scheduler
    Stop order:   scheduler → content_processor → worker_pool → orchestrator

    Uses the local GPUOrchestrator for vLLM subprocess management.
    This is the same orchestrator used by the MCP tools.
    """

    def __init__(self, config: PipelineTestConfig):
        self.config = config
        self._orchestrator: Optional[Any] = None
        self._started_services: list[str] = []

    async def get_orchestrator(self) -> Any:
        """Get or create local GPU orchestrator instance.

        Uses the local GPUOrchestrator from gaius.inference.orchestrator,
        which manages vLLM subprocesses directly. This is the same orchestrator
        used by the MCP tools.
        """
        if self._orchestrator is None:
            from gaius.inference.orchestrator import get_orchestrator
            self._orchestrator = get_orchestrator()
        return self._orchestrator

    async def start_orchestrator(self) -> bool:
        """Start the orchestrator service."""
        orchestrator = await self.get_orchestrator()
        if orchestrator:
            await orchestrator.start()
            self._started_services.append("orchestrator")
            return True
        return False

    async def clean_start(self, endpoints: list[str] = None) -> dict:
        """Perform a clean start via orchestrator.

        Cleans stale processes and starts specified endpoints.
        """
        orchestrator = await self.get_orchestrator()
        if orchestrator:
            result = await orchestrator.clean_start(endpoints=endpoints)
            self._started_services.append("orchestrator")
            return result
        return {"success": False, "error": "No orchestrator available"}

    async def prepare_for_large_model(self, gpu_ids: list[int]) -> dict:
        """Scale down optillm for large model deployment."""
        orchestrator = await self.get_orchestrator()
        if orchestrator:
            return await orchestrator.prepare_for_large_model(gpu_ids)
        return {"success": False, "error": "No orchestrator available"}

    async def restore_normal_operations(self, workers: int = 4) -> dict:
        """Restore optillm workers after large model completes."""
        orchestrator = await self.get_orchestrator()
        if orchestrator:
            return await orchestrator.restore_normal_operations(workers)
        return {"success": False, "error": "No orchestrator available"}

    async def run_worker_once(self) -> int:
        """Run worker pool for one pass.

        Returns:
            Number of jobs processed
        """
        from gaius.workers.manager import run_once
        from gaius.workers.config import WorkerConfig

        # Create worker config with test database URL
        config = WorkerConfig(
            db_url=self.config.db_url,
            pool_size=2,  # Smaller pool for tests
            batch_size=5,
        )
        return await run_once(config)

    async def run_processor_batch(self, limit: int = 50) -> int:
        """Run content processor on a batch.

        Returns:
            Number of items processed
        """
        from gaius.workers.processor import process_content
        return await process_content(limit=limit)

    async def stop_all(self) -> None:
        """Stop all started services in reverse order."""
        for service in reversed(self._started_services):
            if service == "orchestrator" and self._orchestrator:
                await self._orchestrator.stop()
        self._started_services.clear()


# ─────────────────────────────────────────────────────────────────────────────
# MinIO Fixture Manager
# ─────────────────────────────────────────────────────────────────────────────


class MinIOFixtureManager:
    """Manages isolated MinIO storage per scenario.

    Uses per-scenario prefixes in the test bucket:
        zndx-gaius-test/hx-test/{date}/{scenario_id}/

    This provides:
    - Complete test isolation
    - Easy cleanup per scenario
    - Separation from production data in zndx-gaius bucket
    """

    def __init__(self, config: PipelineTestConfig):
        self.config = config
        self._client = None
        self._bucket_verified = False

    def _get_client(self):
        """Get boto3 S3 client for MinIO."""
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=f"http://{self.config.minio_endpoint}",
                aws_access_key_id=self.config.minio_access_key,
                aws_secret_access_key=self.config.minio_secret_key,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",  # MinIO doesn't use regions but boto3 requires one
            )
        return self._client

    def ensure_test_bucket(self) -> bool:
        """Ensure test bucket exists."""
        if self._bucket_verified:
            return True

        try:
            client = self._get_client()
            # Check if bucket exists
            try:
                client.head_bucket(Bucket=self.config.minio_bucket)
            except client.exceptions.ClientError:
                # Create bucket if it doesn't exist
                client.create_bucket(Bucket=self.config.minio_bucket)
                logger.info(f"Created test bucket: {self.config.minio_bucket}")

            self._bucket_verified = True
            return True
        except Exception as e:
            logger.error(f"Failed to ensure test bucket: {e}")
            return False

    def store_content(self, key: str, data: bytes, metadata: dict = None) -> str:
        """Store content in the scenario's isolated prefix.

        Args:
            key: Object key (relative to scenario prefix)
            data: Content bytes
            metadata: Optional S3 metadata

        Returns:
            Full S3 key
        """
        client = self._get_client()
        full_key = f"{self.config.scenario_minio_prefix}{key}"

        extra_args = {}
        if metadata:
            extra_args["Metadata"] = metadata

        client.put_object(
            Bucket=self.config.minio_bucket,
            Key=full_key,
            Body=data,
            **extra_args,
        )
        return full_key

    def get_content(self, key: str) -> bytes:
        """Retrieve content from the scenario's isolated prefix.

        Args:
            key: Object key (relative to scenario prefix)

        Returns:
            Content bytes
        """
        client = self._get_client()
        full_key = f"{self.config.scenario_minio_prefix}{key}"

        response = client.get_object(
            Bucket=self.config.minio_bucket,
            Key=full_key,
        )
        return response["Body"].read()

    def list_objects(self, prefix: str = "") -> list[dict]:
        """List objects in the scenario's isolated prefix.

        Args:
            prefix: Additional prefix within scenario

        Returns:
            List of object metadata dicts
        """
        client = self._get_client()
        full_prefix = f"{self.config.scenario_minio_prefix}{prefix}"

        response = client.list_objects_v2(
            Bucket=self.config.minio_bucket,
            Prefix=full_prefix,
        )
        return response.get("Contents", [])

    def cleanup(self) -> int:
        """Delete all objects in the scenario's prefix.

        Returns:
            Number of objects deleted
        """
        client = self._get_client()

        # List and delete all objects in scenario prefix
        objects = self.list_objects()
        if not objects:
            return 0

        # Delete objects
        delete_keys = [{"Key": obj["Key"]} for obj in objects]
        client.delete_objects(
            Bucket=self.config.minio_bucket,
            Delete={"Objects": delete_keys},
        )

        logger.info(f"Cleaned up {len(delete_keys)} objects from {self.config.scenario_minio_prefix}")
        return len(delete_keys)


# ─────────────────────────────────────────────────────────────────────────────
# KB Fixture Manager
# ─────────────────────────────────────────────────────────────────────────────


class KBFixtureManager:
    """Manages isolated KB directories per scenario.

    Creates:
        build/test/scratch/{date}/{scenario_id}/
        ├── current/
        │   └── content/    # Generated markdown
        ├── scratch/
        │   └── thoughts/   # Cognition output
        └── archive/
    """

    def __init__(self, config: PipelineTestConfig):
        self.config = config
        self._created = False

    def setup_isolated_kb(self) -> Path:
        """Create isolated KB structure for this scenario."""
        root = self.config.scenario_kb_root

        # Create directory structure
        for subdir in ["current/content", "scratch/thoughts", "archive"]:
            (root / subdir).mkdir(parents=True, exist_ok=True)

        self._created = True
        return root

    def verify_kb_files_exist(self, patterns: list[str]) -> dict[str, list[Path]]:
        """Verify expected files exist in KB.

        Args:
            patterns: List of glob patterns to check

        Returns:
            Dict mapping pattern to list of matching files
        """
        root = self.config.scenario_kb_root
        result = {}

        for pattern in patterns:
            matches = list(root.glob(pattern))
            result[pattern] = matches

        return result

    def count_kb_files(self, directory: str = "current/content") -> int:
        """Count files in KB subdirectory."""
        path = self.config.scenario_kb_root / directory
        if not path.exists():
            return 0
        return len([f for f in path.iterdir() if f.is_file()])

    def get_kb_files(self, directory: str = "current/content") -> list[Path]:
        """Get all files in KB subdirectory."""
        path = self.config.scenario_kb_root / directory
        if not path.exists():
            return []
        return [f for f in path.iterdir() if f.is_file()]

    def cleanup(self) -> None:
        """Remove the isolated KB directory."""
        if self._created and self.config.scenario_kb_root.exists():
            shutil.rmtree(self.config.scenario_kb_root)


# ─────────────────────────────────────────────────────────────────────────────
# Inference Fixture Manager
# ─────────────────────────────────────────────────────────────────────────────


class InferenceFixtureManager:
    """Checks inference endpoint availability."""

    def __init__(self, config: PipelineTestConfig):
        self.config = config
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()

    async def check_qwq_available(self) -> bool:
        """Check if QwQ reasoning endpoint is healthy."""
        try:
            resp = await self._client.get(f"{self.config.qwq_endpoint}/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def check_optillm_available(self) -> bool:
        """Check if optillm endpoint is healthy."""
        try:
            resp = await self._client.get(f"{self.config.optillm_endpoint}/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def check_fast_available(self) -> bool:
        """Check if fast model endpoint is healthy."""
        try:
            resp = await self._client.get(f"{self.config.fast_endpoint}/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def wait_for_endpoint(
        self,
        endpoint: str,
        timeout: float = 180.0,
        interval: float = 5.0,
    ) -> bool:
        """Wait for an endpoint to become healthy.

        Args:
            endpoint: Endpoint URL
            timeout: Maximum wait time in seconds
            interval: Check interval in seconds

        Returns:
            True if endpoint became healthy
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            try:
                resp = await self._client.get(f"{endpoint}/health")
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(interval)

        return False


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Metrics
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PipelineMetrics:
    """Metrics collected during pipeline execution."""

    content_fetched: int = 0
    content_triaged_heuristic: int = 0
    content_triaged_llm: int = 0
    kb_entries_created: int = 0
    thoughts_generated: int = 0
    agents_evolved: int = 0

    def to_dict(self) -> dict:
        return {
            "content_fetched": self.content_fetched,
            "content_triaged": self.content_triaged_heuristic + self.content_triaged_llm,
            "kb_entries": self.kb_entries_created,
            "thoughts_created": self.thoughts_generated,
            "agents_evolved": self.agents_evolved,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Context Manager
# ─────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def pipeline_test_context(
    config: Optional[PipelineTestConfig] = None,
    start_services: bool = True,
    endpoints: list[str] = None,
    infrastructure: list[str] = None,
) -> AsyncIterator[dict]:
    """Full test lifecycle management context manager.

    Handles:
    - Infrastructure startup (postgres, aeron, engine) if needed
    - Database connection and test data tracking
    - KB isolation setup
    - Service startup (optional)
    - Cleanup on exit

    Args:
        config: Test configuration (created if not provided)
        start_services: Whether to start orchestrator services
        endpoints: Endpoints to start (if start_services=True)
        infrastructure: Infrastructure to ensure ["postgres", "aeron", "engine"]
                       Default: ["postgres"]

    Yields:
        Dict with test context:
        - config: PipelineTestConfig
        - infrastructure: InfrastructureManager
        - db: TestDatabaseManager
        - services: ServiceLifecycleManager
        - kb: KBFixtureManager
        - inference: InferenceFixtureManager
        - metrics: PipelineMetrics
    """
    if config is None:
        config = PipelineTestConfig()

    if endpoints is None:
        endpoints = ["fast"]

    if infrastructure is None:
        infrastructure = ["postgres"]

    # Create managers
    infra = InfrastructureManager(config)
    db = TestDatabaseManager(config.db_url, config.scenario_id)
    services = ServiceLifecycleManager(config)
    kb = KBFixtureManager(config)
    inference = InferenceFixtureManager(config)
    metrics = PipelineMetrics()

    try:
        # Ensure infrastructure is running
        infra_status = await infra.ensure_infrastructure(infrastructure)
        if not all(infra_status.values()):
            failed = [k for k, v in infra_status.items() if not v]
            raise RuntimeError(f"Failed to start infrastructure: {failed}")

        # Setup
        await db.connect()
        kb.setup_isolated_kb()

        # Set environment for isolated KB
        original_kb_root = os.environ.get("GAIUS_KB_ROOT")
        os.environ["GAIUS_KB_ROOT"] = str(config.scenario_kb_root)

        # Start services if requested
        if start_services:
            await services.clean_start(endpoints=endpoints)

        # Yield context
        yield {
            "config": config,
            "infrastructure": infra,
            "db": db,
            "services": services,
            "kb": kb,
            "inference": inference,
            "metrics": metrics,
        }

    finally:
        # Teardown in reverse order
        await services.stop_all()
        await inference.close()
        await db.cleanup()
        await db.disconnect()
        kb.cleanup()

        # Stop infrastructure we started (but not if tests want to keep it running)
        # Note: We don't stop infra by default to allow test re-runs without restart
        # await infra.stop_infrastructure()

        # Restore environment
        if original_kb_root is None:
            os.environ.pop("GAIUS_KB_ROOT", None)
        else:
            os.environ["GAIUS_KB_ROOT"] = original_kb_root


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Accessors
# ─────────────────────────────────────────────────────────────────────────────

_pipeline_config: Optional[PipelineTestConfig] = None
_db_manager: Optional[TestDatabaseManager] = None
_service_manager: Optional[ServiceLifecycleManager] = None
_kb_manager: Optional[KBFixtureManager] = None
_inference_manager: Optional[InferenceFixtureManager] = None


def get_pipeline_config() -> PipelineTestConfig:
    """Get or create pipeline config singleton."""
    global _pipeline_config
    if _pipeline_config is None:
        _pipeline_config = PipelineTestConfig()
    return _pipeline_config


def reset_pipeline_fixtures() -> None:
    """Reset all pipeline fixtures."""
    global _pipeline_config, _db_manager, _service_manager, _kb_manager, _inference_manager
    _pipeline_config = None
    _db_manager = None
    _service_manager = None
    _kb_manager = None
    _inference_manager = None
