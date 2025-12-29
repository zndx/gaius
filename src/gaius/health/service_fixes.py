"""Service-specific fix strategies for health remediation.

Each strategy knows how to diagnose and fix a specific service type.
"""

import logging
import os
import socket
from pathlib import Path

from .remediation import RemediationAction, SafetyLevel, ServiceFixStrategy

logger = logging.getLogger(__name__)


class EngineFixStrategy(ServiceFixStrategy):
    """Fix strategy for gaius-engine (gRPC gateway)."""

    def __init__(self):
        super().__init__("engine")
        self.port = int(os.getenv("GAIUS_ENGINE_PORT", "50051"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix engine issues."""
        actions = []

        # Check if port is listening
        if not self._is_port_listening():
            # Engine not running - start all devenv services (engine + dependencies)
            actions.append(
                RemediationAction(
                    name="Start devenv services",
                    description="Start all devenv background services including engine",
                    command="devenv up -d",
                    safety=SafetyLevel.SAFE,
                    timeout=120,
                )
            )

            # Wait for engine startup (it preloads vLLM endpoints which takes time)
            actions.append(
                RemediationAction(
                    name="Wait for engine startup",
                    description="Wait for engine to preload endpoints (may take 2-3 minutes)",
                    command="sleep 10",
                    safety=SafetyLevel.SAFE,
                    timeout=15,
                )
            )

        # Always reset gRPC singleton to force reconnection
        actions.append(
            RemediationAction(
                name="Reset gRPC singleton",
                description="Clear stale gRPC client connection",
                code="""
from gaius.client.grpc_client import reset_grpc_client
reset_grpc_client()
print("gRPC singleton reset")
""",
                safety=SafetyLevel.SAFE,
                timeout=5,
            )
        )

        return actions

    def _is_port_listening(self) -> bool:
        """Check if engine port is listening."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(("localhost", self.port))
            return result == 0
        finally:
            sock.close()


def _is_devenv_running() -> bool:
    """Check if devenv processes are already running."""
    import subprocess
    result = subprocess.run(
        ["pgrep", "-f", "process-compose"],
        capture_output=True,
    )
    return result.returncode == 0


class PostgresFixStrategy(ServiceFixStrategy):
    """Fix strategy for PostgreSQL database."""

    def __init__(self):
        super().__init__("postgres")
        self.port = int(os.getenv("GAIUS_DB_PORT", "5438"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix PostgreSQL issues."""
        actions = []

        # Start postgres via devenv (only if devenv not already running)
        if not _is_devenv_running():
            actions.append(
                RemediationAction(
                    name="Start PostgreSQL",
                    description="Start PostgreSQL via devenv",
                    command="devenv up -d",
                    safety=SafetyLevel.SAFE,
                    timeout=60,
                )
            )

        # Wait and verify
        actions.append(
            RemediationAction(
                name="Wait for PostgreSQL",
                description="Wait for database to be ready",
                command=f"pg_isready -h localhost -p {self.port} -t 30",
                safety=SafetyLevel.SAFE,
                timeout=35,
            )
        )

        return actions


class QdrantFixStrategy(ServiceFixStrategy):
    """Fix strategy for Qdrant vector database."""

    def __init__(self):
        super().__init__("qdrant")
        self.http_port = int(os.getenv("QDRANT_HTTP_PORT", "6339"))
        self.grpc_port = int(os.getenv("QDRANT_GRPC_PORT", "6340"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix Qdrant issues."""
        actions = []

        # Start qdrant via devenv (only if devenv not already running)
        if not _is_devenv_running():
            actions.append(
                RemediationAction(
                    name="Start Qdrant",
                    description="Start Qdrant via devenv",
                    command="devenv up -d",
                    safety=SafetyLevel.SAFE,
                    timeout=60,
                )
            )

        # Wait for health endpoint
        actions.append(
            RemediationAction(
                name="Wait for Qdrant",
                description="Wait for Qdrant health check",
                command=f"timeout 30 bash -c 'until curl -s http://localhost:{self.http_port}/healthz > /dev/null; do sleep 1; done'",
                safety=SafetyLevel.SAFE,
                timeout=35,
            )
        )

        return actions


class MinioFixStrategy(ServiceFixStrategy):
    """Fix strategy for MinIO object storage."""

    def __init__(self):
        super().__init__("minio")
        self.api_port = int(os.getenv("MINIO_API_PORT", "9010"))
        self.console_port = int(os.getenv("MINIO_CONSOLE_PORT", "9011"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix MinIO issues."""
        actions = []

        # Start minio via devenv (only if devenv not already running)
        if not _is_devenv_running():
            actions.append(
                RemediationAction(
                    name="Start MinIO",
                    description="Start MinIO via devenv",
                    command="devenv up -d",
                    safety=SafetyLevel.SAFE,
                    timeout=60,
                )
            )

        # Wait for health endpoint
        actions.append(
            RemediationAction(
                name="Wait for MinIO",
                description="Wait for MinIO health check",
                command=f"timeout 30 bash -c 'until curl -s http://localhost:{self.api_port}/minio/health/live > /dev/null; do sleep 1; done'",
                safety=SafetyLevel.SAFE,
                timeout=35,
            )
        )

        return actions


class SingletonFixStrategy(ServiceFixStrategy):
    """Fix strategy for Python client singletons.

    DEPRECATED: With Engine Federation architecture, client-side singleton
    management is no longer the recommended approach. Use EngineFixStrategy
    instead, which includes gRPC client reset as part of engine recovery.

    The gRPC client reset is still available but should not be called in
    isolation - it's now part of the engine reconnection flow.
    """

    def __init__(self):
        import warnings
        warnings.warn(
            "SingletonFixStrategy is deprecated. Use EngineFixStrategy which "
            "includes gRPC singleton reset as part of engine recovery.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__("singletons")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to reset singletons."""
        actions = []

        # Reset gRPC singleton
        actions.append(
            RemediationAction(
                name="Reset gRPC client",
                description="Clear stale gRPC connection singleton",
                code="""
from gaius.client.grpc_client import reset_grpc_client
reset_grpc_client()
print("gRPC client singleton reset")
""",
                safety=SafetyLevel.SAFE,
                timeout=5,
            )
        )

        # Reset engine proxy cache
        actions.append(
            RemediationAction(
                name="Reset engine proxy",
                description="Clear cached engine proxy",
                code="""
from gaius.client import engine_proxy
if hasattr(engine_proxy, '_proxy_cache'):
    engine_proxy._proxy_cache.clear()
    print("Engine proxy cache cleared")
""",
                safety=SafetyLevel.SAFE,
                timeout=5,
            )
        )

        return actions


class AllServicesFixStrategy(ServiceFixStrategy):
    """Fix strategy that starts all devenv services."""

    def __init__(self):
        super().__init__("all")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to start all services."""
        actions = []

        # Start all devenv services in background
        actions.append(
            RemediationAction(
                name="Start all devenv services",
                description="Start all background services via devenv",
                command="devenv up -d",
                safety=SafetyLevel.SAFE,
                timeout=120,
            )
        )

        # Wait for services to stabilize
        actions.append(
            RemediationAction(
                name="Wait for services",
                description="Allow services time to initialize",
                command="sleep 5",
                safety=SafetyLevel.SAFE,
                timeout=10,
            )
        )

        # Reset singletons to pick up new connections
        actions.append(
            RemediationAction(
                name="Reset client singletons",
                description="Clear stale client connections",
                code="""
from gaius.client.grpc_client import reset_grpc_client
reset_grpc_client()
print("Client singletons reset")
""",
                safety=SafetyLevel.SAFE,
                timeout=5,
            )
        )

        return actions


class EndpointFixStrategy(ServiceFixStrategy):
    """Fix strategy for inference endpoints with intelligent diagnosis.

    Multi-step remediation:
    1. Diagnose - Identify unhealthy, stuck, and orphaned endpoints
    2. Kill orphans - Clean up vLLM processes not tracked by orchestrator
    3. Restart unhealthy - Restart endpoints with issues
    4. Verify - Confirm endpoints are healthy
    """

    def __init__(self):
        super().__init__("endpoints")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix inference endpoint issues."""
        actions = []

        # Step 1: Diagnose - Get current endpoint status via CLI
        actions.append(
            RemediationAction(
                name="Diagnose endpoint status",
                description="Check which endpoints are unhealthy and why",
                code='''
import subprocess
import json

print("Checking endpoint status...")

# Get orchestrator status via /gpu status (has endpoint info)
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])
        tracked_pids = set()

        for ep in endpoints:
            name = ep.get("name", "unknown")
            ep_status = ep.get("status", "unknown")
            pid = ep.get("pid")
            if pid:
                tracked_pids.add(pid)

            if ep_status in ("starting", "stopping"):
                print(f"  STUCK: {name} in {ep_status} state")
            elif ep_status not in ("healthy", "stopped"):
                print(f"  UNHEALTHY: {name} status={ep_status}")
            else:
                print(f"  OK: {name} status={ep_status}")
    else:
        print(f"  Could not get orchestrator status: {result.stderr[:200]}")
        tracked_pids = set()
except Exception as e:
    print(f"  Could not get orchestrator status: {e}")
    tracked_pids = set()

# Find orphaned vLLM processes
try:
    result = subprocess.run(
        ["pgrep", "-f", "vllm.entrypoints"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        running_pids = set(int(p) for p in result.stdout.strip().split() if p)
        orphan_pids = running_pids - tracked_pids
        if orphan_pids:
            print(f"  ORPHANS: {len(orphan_pids)} untracked vLLM processes: {orphan_pids}")
        else:
            print(f"  No orphan processes (all {len(running_pids)} tracked)")
    else:
        print("  No vLLM processes running")
except Exception as e:
    print(f"  Could not check for orphan processes: {e}")

print("\\nDiagnosis complete.")
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )

        # Step 2: Kill orphaned vLLM processes
        actions.append(
            RemediationAction(
                name="Kill orphaned vLLM processes",
                description="Clean up zombie processes not tracked by orchestrator",
                code='''
import subprocess
import signal
import os
import json
import time

print("Checking for orphaned vLLM processes...")

# Get tracked PIDs from orchestrator via CLI
tracked_pids = set()
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for ep in data.get("data", {}).get("endpoints", []):
            pid = ep.get("pid")
            if pid:
                tracked_pids.add(pid)
except Exception as e:
    print(f"  Warning: Could not get tracked PIDs: {e}")

# Find running vLLM processes
try:
    result = subprocess.run(
        ["pgrep", "-f", "vllm.entrypoints"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("  No vLLM processes running.")
    else:
        running_pids = set(int(p) for p in result.stdout.strip().split() if p)
        orphan_pids = running_pids - tracked_pids

        if not orphan_pids:
            print(f"  No orphaned vLLM processes found ({len(tracked_pids)} tracked)")
        else:
            # Kill orphans
            killed = 0
            for pid in orphan_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"  Killed orphan PID {pid}")
                    killed += 1
                except ProcessLookupError:
                    print(f"  PID {pid} already gone")
                except PermissionError:
                    print(f"  Cannot kill PID {pid} (permission denied)")

            if killed > 0:
                print(f"\\nKilled {killed} orphaned process(es). Waiting for cleanup...")
                time.sleep(2)

except Exception as e:
    print(f"  Error killing orphans: {e}")

print("Orphan cleanup complete.")
''',
                safety=SafetyLevel.CAUTION,
                timeout=30,
            )
        )

        # Step 3: Restart unhealthy/stuck endpoints via CLI
        actions.append(
            RemediationAction(
                name="Restart unhealthy endpoints",
                description="Stop stuck endpoints and restart unhealthy ones",
                code='''
import subprocess
import json
import time

print("Checking for endpoints needing restart...")

# Get endpoint status via /gpu status
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"  Could not get endpoint status: {result.stderr[:200]}")
    else:
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])

        restarted = []
        stopped = []

        for ep in endpoints:
            name = ep.get("name", "unknown")
            ep_status = ep.get("status", "unknown")

            # Handle stuck in stopping - force stop
            if ep_status == "stopping":
                print(f"  Force stopping stuck endpoint: {name}")
                cmd_result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", f"/gpu stop {name}", "--format", "json"],
                    capture_output=True, text=True, timeout=60
                )
                if cmd_result.returncode == 0:
                    stopped.append(name)
                else:
                    print(f"    Failed: {cmd_result.stderr[:100]}")

            # Handle stuck in starting - stop then restart
            elif ep_status == "starting":
                print(f"  Resetting stuck endpoint: {name}")
                subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", f"/gpu stop {name}", "--format", "json"],
                    capture_output=True, text=True, timeout=60
                )
                time.sleep(2)
                cmd_result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", f"/gpu start {name}", "--format", "json"],
                    capture_output=True, text=True, timeout=60
                )
                if cmd_result.returncode == 0:
                    restarted.append(name)

            # Handle unhealthy - restart
            elif ep_status in ("unhealthy", "failed"):
                print(f"  Restarting unhealthy endpoint: {name}")
                cmd_result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", f"/gpu restart {name}", "--format", "json"],
                    capture_output=True, text=True, timeout=60
                )
                if cmd_result.returncode == 0:
                    restarted.append(name)
                else:
                    print(f"    Failed: {cmd_result.stderr[:100]}")

        # If no specific issues found, report status
        if not restarted and not stopped:
            healthy_count = sum(1 for ep in endpoints if ep.get("status") == "healthy")
            stopped_count = sum(1 for ep in endpoints if ep.get("status") == "stopped")
            if healthy_count + stopped_count == len(endpoints):
                print("  All endpoints in stable state.")
            elif healthy_count < len(endpoints):
                print("  Some endpoints may need manual attention.")

        print(f"\\nRestarted: {len(restarted)}, Stopped: {len(stopped)}")

except Exception as e:
    print(f"Error restarting endpoints: {e}")

print("Restart remediation complete.")
''',
                safety=SafetyLevel.CAUTION,
                timeout=120,
            )
        )

        # Step 4: Verify health via CLI
        actions.append(
            RemediationAction(
                name="Verify endpoint health",
                description="Confirm endpoints are now healthy",
                code='''
import subprocess
import json
import time

print("Waiting for endpoints to stabilize...")
time.sleep(5)

print("\\nVerifying endpoint health:")

try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])

        healthy = 0
        unhealthy = 0
        total = len(endpoints)

        for ep in endpoints:
            name = ep.get("name", "unknown")
            ep_status = ep.get("status", "unknown")
            if ep_status == "healthy":
                print(f"  OK {name}: healthy")
                healthy += 1
            elif ep_status == "stopped":
                print(f"  -- {name}: stopped")
                # Stopped is OK, not unhealthy
            else:
                print(f"  XX {name}: {ep_status}")
                unhealthy += 1

        print(f"\\nSummary: {healthy}/{total} healthy")
        if unhealthy > 0:
            print("Some endpoints still unhealthy. May need manual intervention.")
            print("Try: /health diagnose endpoints")
    else:
        print(f"Could not verify status: {result.stderr[:200]}")

except Exception as e:
    print(f"Error verifying health: {e}")

print("\\nVerification complete.")
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )

        return actions


class EvolutionFixStrategy(ServiceFixStrategy):
    """Fix strategy for evolution daemon.

    Note: The evolution daemon runs inside the engine process.
    The gRPC StartEvolution attempts to start it, but full
    orchestrated evolution (/evolve start) is more reliable.
    """

    def __init__(self):
        super().__init__("evolution")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to start evolution daemon."""
        actions = []

        # Check if engine is running first
        engine_strategy = EngineFixStrategy()
        if not engine_strategy._is_port_listening():
            # Engine not running - add engine start first
            actions.extend(engine_strategy.create_fix_actions())

        # Request evolution start via gRPC
        actions.append(
            RemediationAction(
                name="Request evolution start",
                description="Request evolution daemon start via gRPC",
                code="""
import asyncio
from gaius.client.engine_proxy import get_evolution_proxy

async def start_evolution():
    try:
        evo = await get_evolution_proxy()
        await evo.start()
        print("Evolution start requested via gRPC")
        # Check status
        status = await evo._get_status_async()
        if status.get("running"):
            print(f"Evolution daemon running: cycles={status.get('cycles_completed', 0)}")
        else:
            print("Note: Daemon may need /evolve start for full initialization")
        return status
    except Exception as e:
        print(f"Evolution start failed: {e}")
        raise

asyncio.run(start_evolution())
""",
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Provide manual instruction as fallback
        actions.append(
            RemediationAction(
                name="Manual alternative",
                description="For full orchestrated evolution, use /evolve start",
                command="echo 'For full orchestrated evolution with cleanup, run: /evolve start'",
                safety=SafetyLevel.SAFE,
                timeout=2,
            )
        )

        return actions


class DatasetFixStrategy(ServiceFixStrategy):
    """Fix strategy for DatasetService (NiFi SoM/ToM generation).

    Guru Meditation: #DS.00000001.SVCNOTINIT
    The DatasetService failed to initialize in the engine. This typically
    means the engine process is stale (running old code) or encountered
    an error during service initialization.
    """

    def __init__(self):
        super().__init__("dataset")
        self.port = int(os.getenv("GAIUS_ENGINE_PORT", "50051"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix DatasetService issues."""
        actions = []

        # Step 1: Check if there are multiple engine processes (common cause)
        actions.append(
            RemediationAction(
                name="Check for stale engine processes",
                description="Guru Meditation #DS.00000001.SVCNOTINIT - Identify stale processes",
                code='''
import subprocess
import os

print("Guru Meditation #DS.00000001.SVCNOTINIT")
print("Checking for stale gaius-engine processes...")

# Find all gaius-engine processes
result = subprocess.run(
    ["pgrep", "-af", "gaius-engine"],
    capture_output=True, text=True
)

if result.returncode == 0:
    lines = result.stdout.strip().split("\\n")
    print(f"Found {len(lines)} gaius-engine process(es):")
    for line in lines:
        print(f"  {line}")
    if len(lines) > 1:
        print("\\nWARNING: Multiple engine processes detected!")
        print("This is the likely cause of DatasetService not initialized.")
else:
    print("No gaius-engine processes found.")
    print("Engine needs to be started.")

# Check what's listening on port 50051
result = subprocess.run(
    ["ss", "-tlnp"],
    capture_output=True, text=True
)
if "50051" in result.stdout:
    for line in result.stdout.split("\\n"):
        if "50051" in line:
            print(f"\\nPort 50051: {line}")
''',
                safety=SafetyLevel.SAFE,
                timeout=10,
            )
        )

        # Step 2: Kill all engine processes and verify port is free
        actions.append(
            RemediationAction(
                name="Clean up stale engine processes",
                description="Kill all gaius-engine processes to ensure clean state",
                command="pkill -9 -f gaius-engine; sleep 2; ss -tlnp | grep 50051 || echo 'Port 50051 is free'",
                safety=SafetyLevel.CAUTION,
                timeout=15,
            )
        )

        # Step 3: Restart engine via process-compose (preferred)
        actions.append(
            RemediationAction(
                name="Restart engine via process-compose",
                description="Start fresh engine with DatasetService initialized",
                command="process-compose process restart gaius-engine",
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Step 4: Wait for engine and DatasetService to initialize
        actions.append(
            RemediationAction(
                name="Wait for DatasetService initialization",
                description="Verify DatasetService is responding",
                code='''
import time
import subprocess

print("Waiting for engine startup...")
time.sleep(8)

print("Verifying DatasetService...")
result = subprocess.run(
    ["uv", "run", "python", "-c", """
import grpc
from gaius.engine.generated import gaius_service_pb2_grpc, GetDatasetJobRequest
channel = grpc.insecure_channel('localhost:50051')
stub = gaius_service_pb2_grpc.GaiusServiceStub(channel)
try:
    stub.GetDatasetJobStatus(GetDatasetJobRequest(job_id='health-check'))
    print('DatasetService: READY')
except grpc.RpcError as e:
    if 'not initialized' in str(e.details()):
        print('DatasetService: NOT INITIALIZED (fix may need retry)')
    elif 'NOT_FOUND' in str(e.code()):
        print('DatasetService: READY (job not found is expected)')
    else:
        print(f'DatasetService: ERROR - {e.code()}')
"""],
    capture_output=True, text=True, timeout=30
)
print(result.stdout)
if result.stderr:
    print(result.stderr)
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )

        return actions


class NiFiFixStrategy(ServiceFixStrategy):
    """Fix strategy for NiFi (screenshot capture backend).

    Guru Meditation: #NF.00000001.UNREACHABLE
    NiFi is required for capturing real screenshots of the NiFi canvas.
    """

    def __init__(self):
        super().__init__("nifi")
        self.port = int(os.getenv("NIFI_WEB_HTTP_PORT", "8450"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix NiFi issues."""
        actions = []

        # Restart NiFi via process-compose
        actions.append(
            RemediationAction(
                name="Restart NiFi",
                description="Guru Meditation #NF.00000001.UNREACHABLE - Start NiFi service",
                command="process-compose process restart nifi",
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Wait for NiFi to be ready
        actions.append(
            RemediationAction(
                name="Wait for NiFi startup",
                description="NiFi takes time to initialize (30-60 seconds)",
                code=f'''
import time
import subprocess

print("Waiting for NiFi to start (up to 60 seconds)...")
for i in range(12):
    result = subprocess.run(
        ["curl", "-s", f"http://localhost:{self.port}/nifi-api/flow/cluster/summary"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0 and "clusterSummary" in result.stdout:
        print(f"NiFi ready after {{(i+1)*5}} seconds")
        break
    time.sleep(5)
    print(f"  Waiting... {{(i+1)*5}}s")
else:
    print("NiFi did not start within 60 seconds")
    print("Check: process-compose process logs nifi")
''',
                safety=SafetyLevel.SAFE,
                timeout=70,
            )
        )

        return actions


class PipelineFixStrategy(ServiceFixStrategy):
    """Fix strategy for content pipeline stalls.

    Handles issues with:
    - Task queue stalls (stuck/stale scheduled tasks)
    - Pipeline backlogs at each stage
    - Content processing failures

    Guru Meditation: #PIPE.00000001.STALLED
    """

    def __init__(self):
        super().__init__("pipeline")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix content pipeline issues."""
        actions = []

        # Step 1: Diagnose - Check task queue and pipeline status
        actions.append(
            RemediationAction(
                name="Diagnose pipeline status",
                description="Check pipeline stage backlogs and stuck tasks",
                code='''
import asyncio
import os
import asyncpg

async def diagnose():
    db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

    try:
        conn = await asyncpg.connect(db_url)

        print("=== Pipeline Status ===")

        # Check for stuck tasks
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

        print(f"Stale pending tasks: {stale}")
        print(f"Stuck running tasks: {stuck}")

        # Check content pipeline stages
        needs_heuristic = await conn.fetchval("""
            SELECT COUNT(*) FROM content_items
            WHERE heuristic_score IS NULL
        """)
        needs_llm = await conn.fetchval("""
            SELECT COUNT(*) FROM content_items
            WHERE heuristic_score >= 30
              AND llm_quality_score IS NULL
              AND NOT COALESCE(summary_excluded, false)
        """)
        needs_kb = await conn.fetchval("""
            SELECT COUNT(*) FROM content_items
            WHERE llm_quality_score >= 50
              AND processed_at IS NULL
              AND NOT COALESCE(summary_excluded, false)
        """)

        print(f"\\nPending heuristic triage: {needs_heuristic}")
        print(f"Pending LLM triage: {needs_llm}")
        print(f"Pending KB write: {needs_kb}")

        await conn.close()
        return {"stale": stale, "stuck": stuck}

    except Exception as e:
        print(f"Diagnosis failed: {e}")
        return {"error": str(e)}

result = asyncio.run(diagnose())
print(f"\\nDiagnosis: {result}")
''',
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Step 2: Reset stuck tasks
        actions.append(
            RemediationAction(
                name="Reset stuck tasks",
                description="Reset tasks that have been running too long",
                code='''
import asyncio
import os
import asyncpg

async def reset_stuck():
    db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

    try:
        conn = await asyncpg.connect(db_url)

        # Reset stuck running tasks
        stuck_result = await conn.execute("""
            UPDATE scheduled_tasks
            SET picked_up_at = NULL,
                error = 'reset by pipeline fix: stuck running'
            WHERE picked_up_at IS NOT NULL
              AND completed_at IS NULL
              AND picked_up_at < NOW() - interval '10 minutes'
        """)
        stuck_count = int(stuck_result.split()[-1]) if stuck_result else 0
        print(f"Reset {stuck_count} stuck running tasks")

        # Reset stale pending tasks that may have stale metadata
        stale_result = await conn.execute("""
            UPDATE scheduled_tasks
            SET scheduled_for = NOW()
            WHERE picked_up_at IS NULL
              AND scheduled_for < NOW() - interval '1 hour'
              AND completed_at IS NULL
        """)
        stale_count = int(stale_result.split()[-1]) if stale_result else 0
        print(f"Rescheduled {stale_count} stale pending tasks")

        await conn.close()
        return stuck_count + stale_count

    except Exception as e:
        print(f"Reset failed: {e}")
        return 0

count = asyncio.run(reset_stuck())
print(f"Total tasks reset: {count}")
''',
                safety=SafetyLevel.CAUTION,
                timeout=15,
            )
        )

        # Step 3: Schedule immediate triage if backlog exists
        actions.append(
            RemediationAction(
                name="Schedule triage tasks",
                description="Schedule immediate triage if content backlog exists",
                code='''
import asyncio
import os
import asyncpg
import json

async def schedule_triage():
    db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

    try:
        conn = await asyncpg.connect(db_url)
        scheduled = []

        # Check if heuristic triage is needed
        needs_heuristic = await conn.fetchval("""
            SELECT COUNT(*) FROM content_items
            WHERE heuristic_score IS NULL
        """)
        if needs_heuristic > 0:
            await conn.execute("""
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                VALUES ('heuristic_triage', $1, 'pipeline_fix', NOW())
            """, json.dumps({"limit": min(needs_heuristic, 200)}))
            scheduled.append(f"heuristic_triage ({needs_heuristic} pending)")

        # Check if LLM triage is needed
        needs_llm = await conn.fetchval("""
            SELECT COUNT(*) FROM content_items
            WHERE heuristic_score >= 30
              AND llm_quality_score IS NULL
              AND NOT COALESCE(summary_excluded, false)
        """)
        if needs_llm > 0:
            await conn.execute("""
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                VALUES ('llm_triage', $1, 'pipeline_fix', NOW())
            """, json.dumps({"limit": min(needs_llm, 100)}))
            scheduled.append(f"llm_triage ({needs_llm} pending)")

        # Check if content processing is needed
        needs_kb = await conn.fetchval("""
            SELECT COUNT(*) FROM content_items
            WHERE llm_quality_score >= 50
              AND processed_at IS NULL
              AND NOT COALESCE(summary_excluded, false)
        """)
        if needs_kb > 0:
            await conn.execute("""
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                VALUES ('content_processing', $1, 'pipeline_fix', NOW())
            """, json.dumps({"limit": min(needs_kb, 50)}))
            scheduled.append(f"content_processing ({needs_kb} pending)")

        await conn.close()

        if scheduled:
            print("Scheduled tasks:")
            for task in scheduled:
                print(f"  - {task}")
        else:
            print("No triage tasks needed (pipeline is clear)")

        return len(scheduled)

    except Exception as e:
        print(f"Scheduling failed: {e}")
        return 0

count = asyncio.run(schedule_triage())
print(f"\\nScheduled {count} task(s)")
''',
                safety=SafetyLevel.SAFE,
                timeout=15,
            )
        )

        # Step 4: Verify cognition daemon is processing
        actions.append(
            RemediationAction(
                name="Verify cognition daemon",
                description="Check that cognition daemon is processing tasks",
                code='''
import asyncio
import os
import asyncpg

async def verify():
    db_url = os.environ.get("GAIUS_DATABASE_URL", "postgres://localhost:5438/zndx_gaius")

    try:
        conn = await asyncpg.connect(db_url)

        # Check recent task completions
        completed = await conn.fetchval("""
            SELECT COUNT(*) FROM scheduled_tasks
            WHERE completed_at > NOW() - interval '1 hour'
        """)
        pending = await conn.fetchval("""
            SELECT COUNT(*) FROM scheduled_tasks
            WHERE picked_up_at IS NULL
              AND completed_at IS NULL
        """)
        running = await conn.fetchval("""
            SELECT COUNT(*) FROM scheduled_tasks
            WHERE picked_up_at IS NOT NULL
              AND completed_at IS NULL
        """)

        await conn.close()

        print(f"Tasks in last hour: {completed} completed")
        print(f"Pending tasks: {pending}")
        print(f"Currently running: {running}")

        if completed == 0 and pending > 0:
            print("\\n[WARN] Tasks pending but none completed - cognition daemon may not be running")
            print("  Try: /health fix engine (daemon runs in engine)")
        elif running > 5:
            print("\\n[WARN] Many tasks running - may be backlogged")
        else:
            print("\\n[OK] Task processing appears healthy")

    except Exception as e:
        print(f"Verification failed: {e}")

asyncio.run(verify())
''',
                safety=SafetyLevel.SAFE,
                timeout=15,
            )
        )

        return actions


class RASEFixStrategy(ServiceFixStrategy):
    """Fix strategy for RASE intrinsic verification components.

    Handles issues with:
    - KB Oracle state and objective loading
    - Evidence capture to HX Iceberg storage
    - Calibration loop with Cerebras/XAI
    - Daemon Oracle scoring

    Guru Meditation: #RASE.0000000X
    """

    def __init__(self):
        super().__init__("rase")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix RASE component issues."""
        actions = []

        # Step 1: Validate KB objectives directory exists
        actions.append(
            RemediationAction(
                name="Validate KB objectives",
                description="Check objectives directory and validate objective files",
                code='''
import os
from pathlib import Path

kb_root = os.getenv("GAIUS_KB_ROOT", "build/dev")
objectives_dir = Path(kb_root) / "current" / "objectives"

print(f"Checking objectives directory: {objectives_dir}")

if not objectives_dir.exists():
    print(f"Creating objectives directory: {objectives_dir}")
    objectives_dir.mkdir(parents=True, exist_ok=True)
    print("[OK] Directory created")
else:
    print(f"[OK] Directory exists")

# List objectives
objectives = list(objectives_dir.glob("*.md"))
print(f"Found {len(objectives)} objective files:")
for obj in objectives:
    print(f"  - {obj.name}")

if not objectives:
    print("[WARN] No objectives found. Create objectives in current/objectives/")
''',
                safety=SafetyLevel.SAFE,
                timeout=10,
            )
        )

        # Step 2: Test KB Oracle initialization
        actions.append(
            RemediationAction(
                name="Test KB Oracle",
                description="Initialize and test KBOracle functionality",
                code='''
import asyncio
import os

async def test_oracle():
    from gaius.rase.domains.kb import KBOracle, KBState

    kb_root = os.getenv("GAIUS_KB_ROOT", "build/dev")
    print(f"Testing KBOracle with kb_root={kb_root}")

    # Test state capture
    try:
        state = KBState.capture(kb_root)
        print(f"[OK] KBState captured: {len(state.documents)} documents")
        if state.is_stale():
            print("[WARN] State is stale, will refresh on next verification")
    except Exception as e:
        print(f"[FAIL] KBState capture failed: {e}")
        return False

    # Test oracle creation
    try:
        oracle = KBOracle(kb_root=kb_root)
        print(f"[OK] KBOracle created")
    except Exception as e:
        print(f"[FAIL] KBOracle creation failed: {e}")
        return False

    return True

result = asyncio.run(test_oracle())
print(f"\\nOracle test: {'PASS' if result else 'FAIL'}")
''',
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Step 3: Test HX evidence capture
        actions.append(
            RemediationAction(
                name="Test evidence capture",
                description="Verify HX Iceberg evidence storage is accessible",
                code='''
import asyncio

async def test_evidence():
    try:
        from gaius.hx import get_evidence_capture

        capture = get_evidence_capture()
        status = capture.get_status()
        print(f"[OK] EvidenceCapture singleton: {type(capture).__name__}")
        print(f"  - enabled: {status['enabled']}")
        print(f"  - namespace: {status['namespace']}")
        print(f"  - table: {status['table_name']}")
        print(f"  - kb_root: {status['kb_root']}")

        # Test MinIO connectivity
        from gaius.storage.minio_client import get_minio_client
        try:
            client = get_minio_client()
            buckets = client.list_buckets()
            print(f"[OK] MinIO connected: {len(buckets)} buckets")
        except Exception as e:
            print(f"[WARN] MinIO check failed (may not be critical): {e}")

        return True
    except Exception as e:
        print(f"[FAIL] Evidence capture test failed: {e}")
        return False

result = asyncio.run(test_evidence())
print(f"\\nEvidence test: {'PASS' if result else 'FAIL'}")
''',
                safety=SafetyLevel.SAFE,
                timeout=15,
            )
        )

        # Step 4: Reset RASE singletons
        actions.append(
            RemediationAction(
                name="Reset RASE singletons",
                description="Clear cached RASE component instances",
                code='''
print("Resetting RASE singletons...")

# Reset daemon oracle
try:
    from gaius.agents.evolution import daemon_oracle
    daemon_oracle._daemon_oracle = None
    print("[OK] DaemonOracle singleton reset")
except Exception as e:
    print(f"[WARN] DaemonOracle reset: {e}")

# Reset objective generator
try:
    from gaius.agents.evolution import objective_generator
    objective_generator._generator = None
    print("[OK] ObjectiveTaskGenerator singleton reset")
except Exception as e:
    print(f"[WARN] ObjectiveTaskGenerator reset: {e}")

# Reset calibration oracle
try:
    from gaius.agents.evolution import calibration
    calibration._calibration_oracle = None
    print("[OK] CalibrationOracle singleton reset")
except Exception as e:
    print(f"[WARN] CalibrationOracle reset: {e}")

# Reset KB oracle (in domains)
try:
    from gaius.rase.domains.kb import oracle
    if hasattr(oracle, '_kb_oracle'):
        oracle._kb_oracle = None
        print("[OK] KBOracle singleton reset")
except Exception as e:
    print(f"[WARN] KBOracle reset: {e}")

print("\\nRASE singletons reset complete")
''',
                safety=SafetyLevel.SAFE,
                timeout=10,
            )
        )

        # Step 5: Verify calibration providers
        actions.append(
            RemediationAction(
                name="Check calibration providers",
                description="Verify Cerebras and XAI API keys are configured",
                code='''
import os

print("Checking calibration provider configuration...")

cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
xai_key = os.environ.get("XAI_API_KEY", "")

if cerebras_key:
    print(f"[OK] CEREBRAS_API_KEY configured ({len(cerebras_key)} chars)")
else:
    print("[WARN] CEREBRAS_API_KEY not set (calibration will fall back to XAI)")

if xai_key:
    print(f"[OK] XAI_API_KEY configured ({len(xai_key)} chars)")
else:
    print("[WARN] XAI_API_KEY not set (calibration may not work)")

if not cerebras_key and not xai_key:
    print("\\n[FAIL] No calibration providers configured!")
    print("  Set CEREBRAS_API_KEY or XAI_API_KEY in environment")
else:
    print("\\n[OK] At least one calibration provider available")
''',
                safety=SafetyLevel.SAFE,
                timeout=5,
            )
        )

        return actions


# Service registry - maps service names to strategies
#
# NOTE: With Engine Federation architecture, most remediation should go through
# the engine's HealthObserverService via gRPC. The strategies here are for
# client-side remediation when the engine is not available.
#
# Deprecated: "singletons" - use "engine" which includes gRPC singleton reset
SERVICE_STRATEGIES: dict[str, ServiceFixStrategy] = {
    "engine": EngineFixStrategy(),
    "grpc": EngineFixStrategy(),  # Alias
    "postgres": PostgresFixStrategy(),
    "postgresql": PostgresFixStrategy(),  # Alias
    "database": PostgresFixStrategy(),  # Alias
    "qdrant": QdrantFixStrategy(),
    "minio": MinioFixStrategy(),
    "s3": MinioFixStrategy(),  # Alias
    # "singletons" removed - deprecated, use "engine" instead
    "all": AllServicesFixStrategy(),
    "endpoints": EndpointFixStrategy(),
    "inference": EndpointFixStrategy(),  # Alias
    "evolution": EvolutionFixStrategy(),
    "evolve": EvolutionFixStrategy(),  # Alias
    "dataset": DatasetFixStrategy(),
    "datasetservice": DatasetFixStrategy(),  # Alias
    "nifi": NiFiFixStrategy(),
    "rase": RASEFixStrategy(),
    "kb_oracle": RASEFixStrategy(),  # Alias
    "intrinsic": RASEFixStrategy(),  # Alias
    "objectives": RASEFixStrategy(),  # Alias
    "pipeline": PipelineFixStrategy(),
    "triage": PipelineFixStrategy(),  # Alias
    "content": PipelineFixStrategy(),  # Alias
}


def get_strategy(service: str) -> ServiceFixStrategy | None:
    """Get the fix strategy for a service.

    Args:
        service: Service name (case-insensitive)

    Returns:
        ServiceFixStrategy or None if not found
    """
    return SERVICE_STRATEGIES.get(service.lower())


def list_services() -> list[str]:
    """List available service names."""
    # Return unique strategy names (not aliases)
    seen = set()
    services = []
    for name, strategy in SERVICE_STRATEGIES.items():
        if strategy.service_name not in seen:
            services.append(strategy.service_name)
            seen.add(strategy.service_name)
    return sorted(services)
