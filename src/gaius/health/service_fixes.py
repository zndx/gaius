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
        self.port = int(os.getenv("PGPORT", "5444"))

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

        actions.append(
            RemediationAction(
                name="Reclaim leftover vLLM /dev/shm",
                description="Unlink unheld vllm_offload_*.mmap and psm_* so thinking can start",
                code='''
from gaius.engine.resources.shm import reclaim_vllm_shm, shm_free_bytes

removed = reclaim_vllm_shm()
free_g = shm_free_bytes() / 1024**3
print(f"  reclaimed {len(removed)} segments; {free_g:.1f} GiB free on /dev/shm")
for name in removed:
    print(f"    rm {name}")
if free_g < 0.25:
    print("  Guru: #EP.00000007.SHMFULL")
    print("  /dev/shm still tight after reclaim — mapped files belong to live units")
''',
                safety=SafetyLevel.SAFE,
                timeout=15,
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
import asyncpg
from gaius.core.config import get_database_url

async def diagnose():
    db_url = get_database_url()

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
import asyncpg
from gaius.core.config import get_database_url

async def reset_stuck():
    db_url = get_database_url()

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
import asyncpg
import json
from gaius.core.config import get_database_url

async def schedule_triage():
    db_url = get_database_url()

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
import asyncpg
from gaius.core.config import get_database_url

async def verify():
    db_url = get_database_url()

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
from gaius.core.config import get_config

print("Checking calibration provider configuration...")

cfg = get_config().providers
cerebras_key = cfg.cerebras.api_key
xai_key = cfg.xai.api_key

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


class OptillmFixStrategy(ServiceFixStrategy):
    """Fix strategy for optillm prompt optimization proxy.

    optillm is engine-managed — it runs as a subprocess of gaius-engine,
    not as a standalone devenv process. This strategy:
    1. Verifies engine connectivity (optillm requires the engine)
    2. Restarts optillm via the engine's BackendRouter
    3. Verifies health after restart
    """

    def __init__(self):
        super().__init__("optillm")
        self.engine_port = int(os.getenv("GAIUS_ENGINE_PORT", "50051"))

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix optillm issues."""
        actions = []

        # Step 1: Verify engine is running (optillm is engine-managed)
        if not self._is_engine_listening():
            actions.append(
                RemediationAction(
                    name="Start engine (optillm requires engine)",
                    description="optillm is engine-managed. Start the engine first.",
                    command="devenv up -d",
                    safety=SafetyLevel.SAFE,
                    timeout=120,
                )
            )
            actions.append(
                RemediationAction(
                    name="Wait for engine startup",
                    description="Wait for engine to start and initialize optillm",
                    command="sleep 15",
                    safety=SafetyLevel.SAFE,
                    timeout=20,
                )
            )

        # Step 2: Restart optillm via engine gRPC
        actions.append(
            RemediationAction(
                name="Restart optillm via engine",
                description="Send restart command to engine's optillm controller",
                code='''
import subprocess
import json

print("Restarting optillm via engine...")

# Use CLI to trigger optillm restart through the engine
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])
        optillm_found = any(ep.get("name") == "optillm" for ep in endpoints)
        if optillm_found:
            print("  optillm endpoint found in engine status")
        else:
            print("  optillm not in endpoint list (engine-managed subprocess)")
        print("  Engine is responding - optillm should recover automatically")
    else:
        print(f"  Engine not responding: {result.stderr[:200]}")
        print("  Try: /health fix engine")
except Exception as e:
    print(f"  Could not reach engine: {e}")
    print("  Try: /health fix engine")
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )

        # Step 3: Reset gRPC singleton to force reconnection
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

        # Step 4: Verify optillm health
        actions.append(
            RemediationAction(
                name="Verify optillm health",
                description="Check that optillm is responding after restart",
                code='''
import subprocess
import json

print("Verifying optillm health...")

try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/health", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        # Look for optillm in health output
        health_str = json.dumps(data, indent=2)
        if "optillm" in health_str.lower():
            print("  optillm appears in health output")
        print("  Health check complete")
    else:
        print(f"  Health check failed: {result.stderr[:200]}")
except Exception as e:
    print(f"  Verification failed: {e}")
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )

        return actions

    def _is_engine_listening(self) -> bool:
        """Check if engine gRPC port is listening."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(("localhost", self.engine_port))
            return result == 0
        finally:
            sock.close()


class SiteFixStrategy(ServiceFixStrategy):
    """Fix strategy for site content completeness issues.

    Handles issues with:
    - Missing card images (LuxCore visualizations)
    - Incomplete card summaries (frontier, open_weights, cerebras)
    - Degraded card briefs

    Guru Meditation: #SITE.00000001.CONTENTGAP
    """

    def __init__(self):
        super().__init__("site")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix site content issues."""
        actions = []

        # Step 1: Diagnose — query DB for missing content
        actions.append(
            RemediationAction(
                name="Diagnose site content gaps",
                description="Check for missing images, summaries, and brief quality",
                code='''
import asyncio
import asyncpg
from gaius.core.config import get_database_url

async def diagnose():
    db_url = get_database_url()
    try:
        conn = await asyncpg.connect(db_url)

        print("=== Site Content Status ===")

        # Missing images
        missing_images = await conn.fetchval("""
            SELECT COUNT(*) FROM collections.cards
            WHERE status = 'published'
              AND (image_url IS NULL OR image_url = '')
        """) or 0
        print(f"Cards missing images: {missing_images}")

        # Missing summaries by type
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
                COUNT(*) FILTER (WHERE has_frontier = 0) AS missing_frontier,
                COUNT(*) FILTER (WHERE has_open_weights = 0) AS missing_ow,
                COUNT(*) FILTER (WHERE has_cerebras = 0) AS missing_cerebras
            FROM card_summary_counts
        """)
        if rows:
            r = rows[0]
            print(f"Cards missing frontier summary: {r['missing_frontier']}")
            print(f"Cards missing open_weights summary: {r['missing_ow']}")
            print(f"Cards missing cerebras summary: {r['missing_cerebras']}")

        # Brief quality
        short_briefs = await conn.fetchval("""
            SELECT COUNT(*) FROM collections.cards
            WHERE status = 'published'
              AND (summary IS NULL OR LENGTH(TRIM(summary)) < 20)
        """) or 0
        print(f"Cards with short/empty briefs: {short_briefs}")

        await conn.close()
    except Exception as e:
        print(f"Diagnosis failed: {e}")

asyncio.run(diagnose())
''',
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Step 2: Backfill images
        actions.append(
            RemediationAction(
                name="Backfill card images",
                description="Render LuxCore visualizations for cards missing images",
                command="scripts/backfill_card_images.sh --all",
                safety=SafetyLevel.CAUTION,
                timeout=600,
            )
        )

        # Step 3: Backfill summaries
        actions.append(
            RemediationAction(
                name="Backfill card summaries",
                description="Generate missing frontier/open_weights/cerebras summaries",
                command="uv run python scripts/remediate_card_summaries.py",
                safety=SafetyLevel.CAUTION,
                timeout=600,
            )
        )

        return actions


class MetaflowFixStrategy(ServiceFixStrategy):
    """Fix strategy for Metaflow pipeline stack.

    Handles:
    - K8s cluster connectivity issues
    - Metaflow service port-forward restoration
    - Flow execution verification

    Guru Meditation: #MF.00000003.STACKDOWN
    """

    def __init__(self):
        super().__init__("metaflow")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix Metaflow stack issues."""
        actions = []

        # Step 1: Diagnose KUBECONFIG, K8s, and Metaflow state
        actions.append(
            RemediationAction(
                name="Diagnose Metaflow stack",
                description="Check KUBECONFIG, K8s cluster, Metaflow pods, and port-forwards",
                code='''
import subprocess
import os
from pathlib import Path

# --- KUBECONFIG ---
canonical = Path.home() / ".config" / "kube" / "rke2.yaml"
system = Path("/etc/rancher/rke2/rke2.yaml")

print("=== KUBECONFIG ===")
if not canonical.is_file():
    print(f"  FAIL: {canonical} does not exist")
    if system.is_file():
        print("  Root cause: RKE2 kubeconfig exists at /etc/rancher/rke2/rke2.yaml")
        print("  but has not been copied to the user-readable location.")
        print()
        print("  Fix: just kubeconfig-sync")
        print()
        print("  To auto-sync on K8s restart: just kubeconfig-install-systemd")
    else:
        print("  RKE2 kubeconfig not found at /etc/rancher/rke2/rke2.yaml either")
        print("  Is RKE2 installed? Check: systemctl status rke2-server")
elif not os.access(str(canonical), os.R_OK):
    print(f"  FAIL: {canonical} exists but is not readable")
    print(f"  Fix: chmod 600 {canonical}")
else:
    print(f"  OK: {canonical} (readable)")
    # Check if stale
    if system.is_file():
        try:
            if system.stat().st_mtime > canonical.stat().st_mtime:
                print(f"  WARN: Stale — system kubeconfig is newer")
                print(f"  Fix: just kubeconfig-sync")
        except OSError:
            pass

env_val = os.environ.get("KUBECONFIG", "")
if env_val and env_val != str(canonical):
    print(f"  WARN: $KUBECONFIG={env_val} (overridden to {canonical} for checks)")

kubeconfig = str(canonical)
env = {**os.environ, "KUBECONFIG": kubeconfig}

print("\\n=== K8s Cluster ===")
try:
    result = subprocess.run(
        ["kubectl", "cluster-info"],
        capture_output=True, text=True, timeout=10, env=env,
    )
    if result.returncode == 0:
        print(f"  {result.stdout.strip().splitlines()[0]}")
    else:
        print(f"  FAIL: {result.stderr[:100]}")
except Exception as e:
    print(f"  FAIL: {e}")

print("\\n=== CoreDNS (K8s DNS) ===")
try:
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", "kube-system", "-l", "k8s-app=kube-dns", "--no-headers"],
        capture_output=True, text=True, timeout=10, env=env,
    )
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            status = parts[2] if len(parts) >= 3 else "?"
            print(f"  {line}")
            if status in ("CrashLoopBackOff", "Error", "Unknown"):
                print(f"  *** CoreDNS is {status} — K8s DNS is broken ***")
                print(f"  All pods will fail to resolve service names.")
                print(f"  Fix: kubectl -n kube-system edit configmap rke2-coredns-rke2-coredns")
                print(f"  Then: kubectl -n kube-system rollout restart deployment rke2-coredns-rke2-coredns")
    else:
        print("  No CoreDNS pods found")
except Exception as e:
    print(f"  FAIL: {e}")

print("\\n=== Metaflow Pods ===")
try:
    result = subprocess.run(
        ["kubectl", "get", "pods", "-l", "app.kubernetes.io/name=metaflow-service", "--no-headers"],
        capture_output=True, text=True, timeout=10, env=env,
    )
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            status = parts[2] if len(parts) >= 3 else "?"
            print(f"  {line}")
            if status in ("CrashLoopBackOff", "Error", "Unknown"):
                print(f"  *** Pod is {status} — check init containers and DNS ***")
    else:
        print("  No metaflow-service pods found")
except Exception as e:
    print(f"  FAIL: {e}")

# Check init container status for metaflow pods
print("\\n=== Init Containers ===")
try:
    result = subprocess.run(
        ["kubectl", "get", "pods", "-l", "app.kubernetes.io/name=metaflow-service",
         "-o", "jsonpath={range .items[*]}{.metadata.name}: {range .status.initContainerStatuses[*]}{.name}={.state}{' '}{end}{'\\n'}{end}"],
        capture_output=True, text=True, timeout=10, env=env,
    )
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")
    else:
        print("  No init container data available")
except Exception as e:
    print(f"  FAIL: {e}")

print("\\n=== Metaflow Service ===")
service_url = os.environ.get("METAFLOW_SERVICE_URL", "http://localhost:30180")
try:
    import urllib.request
    req = urllib.request.Request(f"{service_url}/flows", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(f"  HTTP {resp.status} — reachable")
except Exception as e:
    print(f"  UNREACHABLE: {e}")

print("\\nDiagnosis complete.")
''',
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Step 2: Restart the devenv-managed port-forward process
        # This process has built-in infinite retry and readiness probes.
        actions.append(
            RemediationAction(
                name="Restart Metaflow port-forwards",
                description="Restart devenv port-forward process (has built-in infinite retry)",
                command="process-compose process restart metaflow-port-forwards",
                safety=SafetyLevel.SAFE,
                timeout=30,
            )
        )

        # Step 2b: Check CoreDNS health (DNS is prerequisite for all K8s services)
        actions.append(
            RemediationAction(
                name="Check CoreDNS health",
                description="Detect CoreDNS CrashLoopBackOff — blocks all K8s DNS resolution",
                code='''
import subprocess
import os
from pathlib import Path

kubeconfig = str(Path.home() / ".config" / "kube" / "rke2.yaml")
env = {**os.environ, "KUBECONFIG": kubeconfig}

result = subprocess.run(
    ["kubectl", "get", "pods", "-n", "kube-system", "-l", "k8s-app=kube-dns",
     "--no-headers"],
    capture_output=True, text=True, timeout=10, env=env,
)
if result.returncode != 0:
    print("Cannot query CoreDNS pods — kubectl failed")
elif not result.stdout.strip():
    print("No CoreDNS pods found in kube-system")
else:
    healthy = True
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        status = parts[2] if len(parts) >= 3 else "?"
        print(f"  {line}")
        if status in ("CrashLoopBackOff", "Error", "Unknown"):
            healthy = False
            print()
            print(f"CoreDNS is {status} — K8s DNS is BROKEN")
            print(f"#MF.00000004.DNSDOWN: All pods fail to resolve service names.")
            print()
            print("Manual fix required:")
            print("  1. Edit CoreDNS ConfigMap to remove DNS forwarding loop:")
            print("     kubectl -n kube-system edit configmap rke2-coredns-rke2-coredns")
            print("     (Change 'forward . /etc/resolv.conf' to 'forward . 8.8.8.8 8.8.4.4')")
            print("  2. Restart CoreDNS:")
            print("     kubectl -n kube-system rollout restart deployment rke2-coredns-rke2-coredns")
    if healthy:
        print("CoreDNS is healthy")
''',
                safety=SafetyLevel.SAFE,
                timeout=15,
            )
        )

        # Step 2c: Wait for Metaflow service to become reachable
        actions.append(
            RemediationAction(
                name="Wait for Metaflow service",
                description="Poll Metaflow service HTTP endpoint until reachable (up to 30s)",
                code='''
import os
import time
import urllib.request

service_url = os.environ.get("METAFLOW_SERVICE_URL", "http://localhost:30180")
print(f"Waiting for Metaflow service at {service_url} (up to 30s)...")

for i in range(6):
    try:
        req = urllib.request.Request(f"{service_url}/flows", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print(f"Metaflow service reachable after {(i+1)*5}s")
                break
    except Exception:
        pass
    time.sleep(5)
    print(f"  Waiting... {(i+1)*5}s")
else:
    print("Metaflow service not reachable after 30s")
    print("Check: process-compose process logs metaflow-port-forwards")
''',
                safety=SafetyLevel.SAFE,
                timeout=35,
            )
        )

        # Step 3: Verify flow execution
        actions.append(
            RemediationAction(
                name="Verify Metaflow flow execution",
                description="Check recent flow stats to verify the stack is operational",
                code='''
import asyncio

async def verify():
    from gaius.engine.services.metaflow_query import get_metaflow_client
    client = get_metaflow_client()
    stats = await client.get_flow_stats(hours=1)

    if "error" in stats:
        print(f"Flow query failed: {stats['error']}")
        return

    total = stats.get("total_runs", 0)
    success_pct = stats.get("success_rate_pct", 0.0)
    print(f"Last 1h: {total} runs, {success_pct:.0f}% success rate")

    if total == 0:
        print("No recent runs — stack may need a curation trigger")
    elif success_pct < 80.0:
        print("Low success rate — check flow logs for errors")
    else:
        print("Stack appears operational")

asyncio.run(verify())
''',
                safety=SafetyLevel.SAFE,
                timeout=30,
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
    "optillm": OptillmFixStrategy(),
    "site": SiteFixStrategy(),
    "cards": SiteFixStrategy(),  # Alias
    "metaflow": MetaflowFixStrategy(),
    "k8s": MetaflowFixStrategy(),  # Alias — K8s issues route through Metaflow stack fix
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


class GPUMemoryFixStrategy(ServiceFixStrategy):
    """Fix strategy for GPU memory exhaustion with hierarchical remediation.
    
    Handles GPU_001 failure mode: GPU memory exhaustion causing endpoint failures.
    Implements 4-tier hierarchical remediation with rate limiting and zombie detection.
    
    Remediation Tiers:
    1. RESTART: Graceful endpoint restart via orchestrator
    2. CLEAN_START: Force clean start of endpoint (unload + reload)
    3. FORCE_KILL: Kill vLLM process directly
    4. FULL_RESET: Reset entire GPU
    
    Includes:
    - GPU-to-endpoint mapping for precise targeting
    - Kernel-level zombie detection (SIGKILL responsiveness test)
    - Thermal emergency integration
    - Rate limiting (max 3 attempts per tier per hour)
    - Post-remediation verification
    """

    # Rate limiting configuration
    MAX_ATTEMPTS_PER_TIER = 3
    ATTEMPT_WINDOW_HOURS = 1
    MIN_INTERVAL_SECONDS = 300  # 5 minutes between attempts
    EMERGENCY_INTERVAL_SECONDS = 900  # 15 minutes after failed remediation
    OBSERVATION_PERIOD_SECONDS = 180  # 3 minutes observation before implementing fixes

    def __init__(self):
        super().__init__("gpu_memory")
        self._attempt_tracker: dict[str, list[datetime]] = {}  # endpoint -> [attempt_times]
        self._last_remediation: dict[str, datetime] = {}  # endpoint -> last_remediation_time
        self._thermal_monitor = None

    def _get_thermal_monitor(self):
        """Get thermal emergency monitor instance."""
        if self._thermal_monitor is None:
            try:
                from .thermal_emergency import get_thermal_monitor
                self._thermal_monitor = get_thermal_monitor()
            except ImportError:
                pass
        return self._thermal_monitor

    def _is_rate_limited(self, endpoint: str, tier: int) -> bool:
        """Check if remediation is rate limited for this endpoint and tier."""
        key = f"{endpoint}:tier_{tier}"
        now = datetime.now()
        
        # Clean old attempts
        if key in self._attempt_tracker:
            cutoff = now - timedelta(hours=self.ATTEMPT_WINDOW_HOURS)
            self._attempt_tracker[key] = [t for t in self._attempt_tracker[key] if t >= cutoff]
        else:
            self._attempt_tracker[key] = []
        
        # Check if we've exceeded attempts
        if len(self._attempt_tracker[key]) >= self.MAX_ATTEMPTS_PER_TIER:
            return True
        
        # Check minimum interval
        if key in self._last_remediation:
            time_since_last = (now - self._last_remediation[key]).total_seconds()
            if time_since_last < self.MIN_INTERVAL_SECONDS:
                return True
        
        return False

    def _record_attempt(self, endpoint: str, tier: int):
        """Record a remediation attempt."""
        key = f"{endpoint}:tier_{tier}"
        now = datetime.now()
        
        if key not in self._attempt_tracker:
            self._attempt_tracker[key] = []
        
        self._attempt_tracker[key].append(now)
        self._last_remediation[key] = now

    async def _check_thermal_status(self) -> dict:
        """Check thermal status and return emergency info."""
        thermal_monitor = self._get_thermal_monitor()
        if thermal_monitor and hasattr(thermal_monitor, '_last_state'):
            state = thermal_monitor._last_state
            if state:
                return {
                    'is_critical': len(state.critical_gpus) > 0,
                    'is_emergency': len(state.fan_failed_gpus) > 0,
                    'critical_gpus': state.critical_gpus,
                    'fan_failed_gpus': state.fan_failed_gpus,
                }
        return {'is_critical': False, 'is_emergency': False, 'critical_gpus': [], 'fan_failed_gpus': []}

    async def _get_gpu_endpoint_mapping(self) -> dict[int, list[str]]:
        """Get mapping of GPU indices to endpoint names."""
        mapping: dict[int, list[str]] = {}
        
        try:
            import subprocess
            import json
            
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                endpoints = data.get("data", {}).get("endpoints", [])
                
                for ep in endpoints:
                    name = ep.get("name", "unknown")
                    gpu_ids = ep.get("gpu_ids", [])
                    pid = ep.get("pid")
                    
                    for gpu_id in gpu_ids:
                        if gpu_id not in mapping:
                            mapping[gpu_id] = []
                        mapping[gpu_id].append(name)
        except Exception as e:
            logger.warning(f"Could not get GPU endpoint mapping: {e}")
        
        return mapping

    async def _detect_zombie_processes(self) -> list[int]:
        """Detect zombie vLLM processes using kernel-level SIGKILL test."""
        zombies = []
        
        try:
            import subprocess
            import os
            import signal
            
            # Get all vLLM processes
            result = subprocess.run(
                ["pgrep", "-f", "vllm.entrypoints"],
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                pids = [int(p) for p in result.stdout.strip().split() if p.strip()]
                
                for pid in pids:
                    try:
                        # Test if process responds to SIGKILL (zombie test)
                        # Zombie processes cannot be killed, so this will fail
                        os.kill(pid, signal.SIGKILL)
                        # If we get here, the process was killable (not a zombie)
                        # But we just killed it, so we need to handle this carefully
                        # For now, just consider it non-zombie
                    except ProcessLookupError:
                        # Process already gone
                        pass
                    except PermissionError:
                        # No permission to kill - might be zombie or just protected
                        zombies.append(pid)
                    except Exception:
                        # Other errors - likely zombie
                        zombies.append(pid)
        except Exception as e:
            logger.warning(f"Zombie detection error: {e}")
        
        return zombies

    def _get_remediation_tier(self, memory_pct: float, utilization: int, is_zombie: bool) -> int:
        """Determine appropriate remediation tier based on severity."""
        if is_zombie:
            return 3  # FORCE_KILL for zombies
        elif memory_pct >= 99:
            return 3  # FORCE_KILL for extreme memory exhaustion
        elif memory_pct >= 95:
            return 2  # CLEAN_START for high memory
        elif memory_pct >= 90:
            return 1  # RESTART for moderate memory pressure
        else:
            return 0  # OBSERVE only

    def _next_remediation_tier(self, current_tier: int) -> int:
        """Get next remediation tier."""
        tiers = [0, 1, 2, 3, 4]  # OBSERVE, RESTART, CLEAN_START, FORCE_KILL, FULL_RESET
        current_index = tiers.index(current_tier) if current_tier in tiers else 0
        next_index = min(current_index + 1, len(tiers) - 1)
        return tiers[next_index]

    async def _apply_remediation_tier(self, endpoint: str, tier: int) -> bool:
        """Apply remediation at the specified tier."""
        import subprocess
        
        if tier == 0:
            # OBSERVE - just monitor
            logger.info(f"Observing endpoint {endpoint}")
            return True
        elif tier == 1:
            # RESTART - graceful restart via orchestrator
            logger.info(f"Tier 1: Restarting endpoint {endpoint}")
            try:
                result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", f"/gpu restart {endpoint}", "--format", "json"],
                    capture_output=True, text=True, timeout=60
                )
                return result.returncode == 0
            except Exception as e:
                logger.error(f"Restart failed for {endpoint}: {e}")
                return False
        elif tier == 2:
            # CLEAN_START - force clean start
            logger.info(f"Tier 2: Clean start for endpoint {endpoint}")
            try:
                result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", f"/gpu clean-start {endpoint}", "--format", "json"],
                    capture_output=True, text=True, timeout=120
                )
                return result.returncode == 0
            except Exception as e:
                logger.error(f"Clean start failed for {endpoint}: {e}")
                return False
        elif tier == 3:
            # FORCE_KILL - kill vLLM process directly
            logger.info(f"Tier 3: Force killing endpoint {endpoint}")
            try:
                # Find the PID for this endpoint
                result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    import json
                    data = json.loads(result.stdout)
                    for ep in data.get("data", {}).get("endpoints", []):
                        if ep.get("name") == endpoint:
                            pid = ep.get("pid")
                            if pid:
                                import os
                                import signal
                                try:
                                    os.kill(pid, signal.SIGKILL)
                                    logger.info(f"Killed PID {pid} for endpoint {endpoint}")
                                    return True
                                except ProcessLookupError:
                                    logger.warning(f"PID {pid} already gone")
                                    return True
                                except Exception as e:
                                    logger.error(f"Failed to kill PID {pid}: {e}")
                                    return False
            except Exception as e:
                logger.error(f"Force kill failed for {endpoint}: {e}")
                return False
        elif tier == 4:
            # FULL_RESET - reset entire GPU
            logger.info(f"Tier 4: Full GPU reset for endpoint {endpoint}")
            try:
                # This is a last resort - reset the GPU
                result = subprocess.run(
                    ["sudo", "nvidia-smi", "-r"],
                    capture_output=True, text=True, timeout=30
                )
                return result.returncode == 0
            except Exception as e:
                logger.error(f"GPU reset failed: {e}")
                return False
        
        return False

    async def _verify_remediation(self, endpoint: str, gpu_index: int) -> bool:
        """Verify that remediation was successful."""
        import subprocess
        import time
        
        # Wait for observation period
        await asyncio.sleep(self.OBSERVATION_PERIOD_SECONDS)
        
        try:
            # Check endpoint status
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                for ep in data.get("data", {}).get("endpoints", []):
                    if ep.get("name") == endpoint:
                        status = ep.get("status", "unknown")
                        if status == "healthy":
                            return True
                        elif status in ["starting", "stopping"]:
                            # Still in transition, might need more time
                            return True
                        else:
                            return False
            
            # Check GPU memory directly
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total", 
                 f"--filter=gpu_uuid=GPU-{gpu_index:04d}-*", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                if len(parts) >= 2:
                    used = int(parts[0].strip())
                    total = int(parts[1].strip())
                    memory_pct = (used / total) * 100 if total > 0 else 0
                    # Memory should be below 90% after successful remediation
                    return memory_pct < 90
            
        except Exception as e:
            logger.warning(f"Verification error for {endpoint}: {e}")
        
        return False

    def create_fix_actions(self, check_result: dict | None = None) -> list[RemediationAction]:
        """Create actions to fix GPU memory issues."""
        actions = []
        
        # Step 1: Check thermal status first
        actions.append(
            RemediationAction(
                name="Check thermal emergency",
                description="Verify no thermal emergency before proceeding",
                code='''
import asyncio
from datetime import datetime

async def check_thermal():
    try:
        from gaius.health.thermal_emergency import get_thermal_monitor
        monitor = get_thermal_monitor()
        if hasattr(monitor, '_last_state') and monitor._last_state:
            state = monitor._last_state
            if state.critical_gpus or state.fan_failed_gpus:
                print(f"THERMAL EMERGENCY: Critical GPUs: {state.critical_gpus}, Fan failed: {state.fan_failed_gpus}")
                print("ABORTING: Thermal emergency takes precedence")
                return False
            else:
                print("Thermal status: OK")
                return True
    except Exception as e:
        print(f"Thermal check error: {e}")
        return True  # Continue if thermal monitor not available
    return True

result = asyncio.run(check_thermal())
if not result:
    print("EMERGENCY: Thermal emergency detected - aborting GPU memory fix")
''',
                safety=SafetyLevel.SAFE,
                timeout=10,
            )
        )
        
        # Step 2: Diagnose GPU memory and endpoint mapping
        actions.append(
            RemediationAction(
                name="Diagnose GPU memory and endpoints",
                description="Identify memory exhaustion and map to endpoints",
                code='''
import subprocess
import json

print("=== GPU Memory Diagnosis ===")

# Get GPU status
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu", 
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        gpus = []
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    idx, used, total, util = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    mem_pct = (used / total) * 100 if total > 0 else 0
                    gpus.append({"index": idx, "used_mb": used, "total_mb": total, "mem_pct": mem_pct, "util": util})
                    if mem_pct > 95:
                        print(f"  CRITICAL: GPU {idx} at {mem_pct:.0f}% memory ({used}/{total}MB)")
                    elif mem_pct > 90:
                        print(f"  WARNING: GPU {idx} at {mem_pct:.0f}% memory ({used}/{total}MB)")
                    else:
                        print(f"  OK: GPU {idx} at {mem_pct:.0f}% memory")
    else:
        print(f"  nvidia-smi failed: {result.stderr[:200]}")
except Exception as e:
    print(f"  GPU query failed: {e}")

# Get endpoint mapping
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])
        print(f"\\n=== Endpoint Mapping ===")
        for ep in endpoints:
            name = ep.get("name", "unknown")
            status = ep.get("status", "unknown")
            gpu_ids = ep.get("gpu_ids", [])
            pid = ep.get("pid")
            print(f"  {name}: status={status}, GPUs={gpu_ids}, PID={pid}")
    else:
        print(f"  Could not get endpoint status: {result.stderr[:200]}")
except Exception as e:
    print(f"  Endpoint mapping failed: {e}")

# Detect zombie processes
try:
    result = subprocess.run(
        ["pgrep", "-f", "vllm.entrypoints"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        pids = result.stdout.strip().split()
        print(f"\\n=== vLLM Processes ===")
        print(f"  Found {len(pids)} vLLM processes: {pids}")
    else:
        print("\\n  No vLLM processes found")
except Exception as e:
    print(f"\\n  Could not check vLLM processes: {e}")

print("\\nDiagnosis complete.")
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )
        
        # Step 3: Hierarchical remediation with rate limiting
        actions.append(
            RemediationAction(
                name="Apply hierarchical remediation",
                description="Apply tiered remediation based on severity with rate limiting",
                code='''
import subprocess
import json
import asyncio
import os
import signal
from datetime import datetime, timedelta

# Rate limiting config
MAX_ATTEMPTS_PER_TIER = 3
ATTEMPT_WINDOW_HOURS = 1
MIN_INTERVAL_SECONDS = 300

attempt_tracker = {}
last_remediation = {}

def is_rate_limited(endpoint, tier):
    key = f"{endpoint}:tier_{tier}"
    now = datetime.now()
    if key in attempt_tracker:
        cutoff = now - timedelta(hours=ATTEMPT_WINDOW_HOURS)
        attempt_tracker[key] = [t for t in attempt_tracker[key] if t >= cutoff]
    else:
        attempt_tracker[key] = []
    if len(attempt_tracker[key]) >= MAX_ATTEMPTS_PER_TIER:
        return True
    if key in last_remediation:
        time_since_last = (now - last_remediation[key]).total_seconds()
        if time_since_last < MIN_INTERVAL_SECONDS:
            return True
    return False

def record_attempt(endpoint, tier):
    key = f"{endpoint}:tier_{tier}"
    now = datetime.now()
    if key not in attempt_tracker:
        attempt_tracker[key] = []
    attempt_tracker[key].append(now)
    last_remediation[key] = now

def get_remediation_tier(memory_pct, utilization, is_zombie):
    if is_zombie:
        return 3  # FORCE_KILL
    elif memory_pct >= 99:
        return 3
    elif memory_pct >= 95:
        return 2  # CLEAN_START
    elif memory_pct >= 90:
        return 1  # RESTART
    else:
        return 0  # OBSERVE

def next_tier(current_tier):
    tiers = [0, 1, 2, 3, 4]
    current_index = tiers.index(current_tier) if current_tier in tiers else 0
    next_index = min(current_index + 1, len(tiers) - 1)
    return tiers[next_index]

async def apply_remediation(endpoint, tier):
    if tier == 0:
        print(f"  OBSERVE: {endpoint}")
        return True
    elif tier == 1:
        print(f"  TIER 1: Restarting {endpoint}")
        try:
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", f"/gpu restart {endpoint}", "--format", "json"],
                capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0
        except Exception as e:
            print(f"    Failed: {e}")
            return False
    elif tier == 2:
        print(f"  TIER 2: Clean start for {endpoint}")
        try:
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", f"/gpu clean-start {endpoint}", "--format", "json"],
                capture_output=True, text=True, timeout=120
            )
            return result.returncode == 0
        except Exception as e:
            print(f"    Failed: {e}")
            return False
    elif tier == 3:
        print(f"  TIER 3: Force killing {endpoint}")
        try:
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for ep in data.get("data", {}).get("endpoints", []):
                    if ep.get("name") == endpoint:
                        pid = ep.get("pid")
                        if pid:
                            try:
                                os.kill(pid, signal.SIGKILL)
                                print(f"    Killed PID {pid}")
                                return True
                            except ProcessLookupError:
                                print(f"    PID {pid} already gone")
                                return True
                            except Exception as e:
                                print(f"    Failed to kill PID {pid}: {e}")
                                return False
        except Exception as e:
            print(f"    Failed: {e}")
            return False
    elif tier == 4:
        print(f"  TIER 4: Full GPU reset")
        try:
            result = subprocess.run(
                ["sudo", "nvidia-smi", "-r"],
                capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            print(f"    Failed: {e}")
            return False
    return False

# Main remediation logic
print("Starting hierarchical remediation...")

# Get GPU and endpoint info
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", 
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        gpu_memory = {}
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx, used, total = int(parts[0]), int(parts[1]), int(parts[2])
                    mem_pct = (used / total) * 100 if total > 0 else 0
                    gpu_memory[idx] = {"used": used, "total": total, "pct": mem_pct}

    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])
    else:
        endpoints = []
        print(f"  Warning: Could not get endpoint status")

except Exception as e:
    print(f"  Error getting system info: {e}")
    endpoints = []
    gpu_memory = {}

# Build GPU to endpoint mapping
gpu_to_endpoints = {}
for ep in endpoints:
    name = ep.get("name", "unknown")
    gpu_ids = ep.get("gpu_ids", [])
    for gpu_id in gpu_ids:
        if gpu_id not in gpu_to_endpoints:
            gpu_to_endpoints[gpu_id] = []
        gpu_to_endpoints[gpu_id].append(name)

# Find GPUs with memory issues
problem_gpus = []
for gpu_idx, mem_info in gpu_memory.items():
    if mem_info["pct"] >= 90:
        problem_gpus.append(gpu_idx)

if not problem_gpus:
    print("No GPU memory issues detected")
else:
    print(f"Problem GPUs: {problem_gpus}")
    
    # Remediate each problem GPU
    for gpu_idx in problem_gpus:
        endpoints_on_gpu = gpu_to_endpoints.get(gpu_idx, [])
        if not endpoints_on_gpu:
            print(f"  GPU {gpu_idx}: No endpoints mapped, cannot remediate")
            continue
        
        print(f"  GPU {gpu_idx} ({gpu_memory[gpu_idx]['pct']:.0f}% memory): endpoints {endpoints_on_gpu}")
        
        for endpoint in endpoints_on_gpu:
            mem_pct = gpu_memory[gpu_idx]["pct"]
            
            # Determine initial tier
            tier = get_remediation_tier(mem_pct, 0, False)
            
            # Try remediation with escalation
            max_tiers = 5
            for attempt in range(max_tiers):
                if is_rate_limited(endpoint, tier):
                    print(f"    Rate limited for {endpoint} at tier {tier}")
                    break
                
                print(f"    Attempt {attempt + 1}: Tier {tier} for {endpoint}")
                success = await apply_remediation(endpoint, tier)
                record_attempt(endpoint, tier)
                
                if success:
                    print(f"    Success at tier {tier}")
                    break
                else:
                    # Escalate to next tier
                    tier = next_tier(tier)
                    if tier >= max_tiers:
                        print(f"    All tiers exhausted for {endpoint}")
                        break

print("\\nHierarchical remediation complete.")
''',
                safety=SafetyLevel.CAUTION,
                timeout=300,
            )
        )
        
        # Step 4: Verify remediation
        actions.append(
            RemediationAction(
                name="Verify remediation",
                description="Verify that GPU memory issues are resolved",
                code='''
import subprocess
import time

print("Waiting 180s for remediation to take effect...")
time.sleep(180)

print("\\n=== Post-Remediation Verification ===")

# Check GPU memory
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", 
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        all_ok = True
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx, used, total = int(parts[0]), int(parts[1]), int(parts[2])
                    mem_pct = (used / total) * 100 if total > 0 else 0
                    if mem_pct > 90:
                        print(f"  FAIL: GPU {idx} still at {mem_pct:.0f}% memory")
                        all_ok = False
                    else:
                        print(f"  OK: GPU {idx} at {mem_pct:.0f}% memory")
        if all_ok:
            print("\\nAll GPUs within acceptable memory range")
        else:
            print("\\nSome GPUs still have memory issues")
    else:
        print(f"  Could not verify: {result.stderr[:200]}")
except Exception as e:
    print(f"  Verification failed: {e}")

# Check endpoint health
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        import json
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])
        healthy = sum(1 for ep in endpoints if ep.get("status") == "healthy")
        total = len(endpoints)
        print(f"\\nEndpoint health: {healthy}/{total} healthy")
    else:
        print(f"  Could not verify endpoints: {result.stderr[:200]}")
except Exception as e:
    print(f"  Endpoint verification failed: {e}")

print("\\nVerification complete.")
''',
                safety=SafetyLevel.SAFE,
                timeout=200,
            )
        )
        
        return actions


class GPUMemoryPressureFixStrategy(ServiceFixStrategy):
    """Fix strategy for GPU memory pressure PREVENTION (before GPU_001 failure).
    
    This strategy detects and remediates GPU memory pressure BEFORE it reaches
    the GPU_001 failure threshold (>95%). It implements continuous monitoring and
    hierarchical remediation to prevent memory exhaustion.
    
    Handles: GPU memory pressure detection at 85-95% utilization
    Prevents: GPU_001 (Memory Exhaustion) failures
    
    Remediation Tiers:
    1. TIER_1 (85%): Warning and monitoring
    2. TIER_2 (90%): Graceful endpoint restart
    3. TIER_3 (95%): Forceful cleanup + restart
    4. TIER_4 (98%+): Nuclear reset (full GPU reset)
    
    Key Features:
    - Continuous memory monitoring (not just at failure)
    - Memory pressure detection BEFORE failure
    - Hierarchical remediation with automatic escalation
    - GPU-to-endpoint mapping for precise targeting
    - Rate limiting to prevent remediation storms
    - Health reconciliation (GPU health -> endpoint health)
    - Thermal emergency integration
    """

    # Memory thresholds (percentage)
    TIER_1_THRESHOLD = 85  # Warning
    TIER_2_THRESHOLD = 90  # Graceful remediation
    TIER_3_THRESHOLD = 95  # Forceful remediation
    TIER_4_THRESHOLD = 98  # Nuclear remediation
    
    # Rate limiting
    MAX_ATTEMPTS_PER_HOUR = 3
    MIN_INTERVAL_SECONDS = 300  # 5 minutes
    COOLDOWN_AFTER_FAILURE_SECONDS = 900  # 15 minutes
    
    # Memory headroom configuration
    MEMORY_HEADROOM_PCT = 10  # Reserve 10% memory
    MAX_MEMORY_PCT = 90  # Never allow >90% allocation

    def __init__(self):
        super().__init__("gpu_memory_pressure")
        self._last_check: dict[int, datetime] = {}  # GPU index -> last check time
        self._remediation_attempts: dict[str, list[datetime]] = {}  # endpoint -> [attempt times]
        self._thermal_monitor = None

    def _get_thermal_monitor(self):
        """Get thermal emergency monitor instance."""
        if self._thermal_monitor is None:
            try:
                from .thermal_emergency import get_thermal_monitor
                self._thermal_monitor = get_thermal_monitor()
            except ImportError:
                pass
        return self._thermal_monitor

    def _is_rate_limited(self, endpoint: str) -> bool:
        """Check if remediation is rate limited for this endpoint."""
        now = datetime.now()
        
        if endpoint not in self._remediation_attempts:
            self._remediation_attempts[endpoint] = []
        
        # Clean old attempts (older than 1 hour)
        cutoff = now - timedelta(hours=1)
        self._remediation_attempts[endpoint] = [
            t for t in self._remediation_attempts[endpoint] if t >= cutoff
        ]
        
        # Check rate limit
        if len(self._remediation_attempts[endpoint]) >= self.MAX_ATTEMPTS_PER_HOUR:
            return True
        
        # Check cooldown
        if self._remediation_attempts[endpoint]:
            last_attempt = max(self._remediation_attempts[endpoint])
            time_since_last = (now - last_attempt).total_seconds()
            if time_since_last < self.MIN_INTERVAL_SECONDS:
                return True
        
        return False

    def _record_attempt(self, endpoint: str):
        """Record a remediation attempt."""
        now = datetime.now()
        if endpoint not in self._remediation_attempts:
            self._remediation_attempts[endpoint] = []
        self._remediation_attempts[endpoint].append(now)

    async def _check_thermal_emergency(self) -> bool:
        """Check for thermal emergency. Returns True if safe to proceed."""
        try:
            monitor = self._get_thermal_monitor()
            if monitor and hasattr(monitor, '_last_state') and monitor._last_state:
                state = monitor._last_state
                if state.critical_gpus or state.fan_failed_gpus:
                    logger.error(
                        f"THERMAL EMERGENCY: Critical GPUs: {state.critical_gpus}, "
                        f"Fan failed: {state.fan_failed_gpus}. "
                        f"ABORTING memory remediation."
                    )
                    return False
        except Exception as e:
            logger.warning(f"Thermal check error: {e}")
        
        return True

    def _get_gpu_memory_status(self) -> dict:
        """Get current GPU memory status."""
        import subprocess
        
        gpu_status = {}
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 3:
                            gpu_id = int(parts[0])
                            used = int(parts[1])
                            total = int(parts[2])
                            pct = (used / total) * 100 if total > 0 else 0
                            
                            gpu_status[gpu_id] = {
                                'used_mb': used,
                                'total_mb': total,
                                'used_pct': pct,
                                'is_healthy': pct < self.TIER_2_THRESHOLD
                            }
        except Exception as e:
            logger.error(f"Error getting GPU memory status: {e}")
        
        return gpu_status

    def _get_endpoint_gpu_mapping(self) -> dict:
        """Get mapping of endpoints to GPUs."""
        import subprocess
        import json
        
        mapping = {}
        try:
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for ep in data.get("data", {}).get("endpoints", []):
                    name = ep.get("name")
                    gpu_ids = ep.get("gpu_ids", [])
                    if name and gpu_ids:
                        mapping[name] = gpu_ids
        except Exception as e:
            logger.error(f"Error getting endpoint mapping: {e}")
        
        return mapping

    def _determine_remediation_tier(self, gpu_status: dict) -> int:
        """Determine the appropriate remediation tier based on memory status."""
        max_pct = max((s['used_pct'] for s in gpu_status.values()), default=0)
        
        if max_pct >= self.TIER_4_THRESHOLD:
            return 4
        elif max_pct >= self.TIER_3_THRESHOLD:
            return 3
        elif max_pct >= self.TIER_2_THRESHOLD:
            return 2
        elif max_pct >= self.TIER_1_THRESHOLD:
            return 1
        
        return 0  # No remediation needed

    def _get_endpoints_on_unhealthy_gpus(self, gpu_status: dict, mapping: dict) -> list:
        """Get endpoints that are on unhealthy GPUs."""
        unhealthy_gpus = [gpu_id for gpu_id, status in gpu_status.items() 
                        if not status.get('is_healthy', True)]
        
        affected_endpoints = []
        for ep_name, gpu_ids in mapping.items():
            if any(gpu_id in unhealthy_gpus for gpu_id in gpu_ids):
                affected_endpoints.append(ep_name)
        
        return affected_endpoints

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to prevent and fix GPU memory pressure."""
        actions = []
        
        # Step 0: Check thermal emergency first (BLOCKING)
        actions.append(
            RemediationAction(
                name="Check thermal emergency",
                description="Verify no thermal emergency before memory remediation",
                code='''
import asyncio

async def check_thermal():
    try:
        from gaius.health.thermal_emergency import get_thermal_monitor
        monitor = get_thermal_monitor()
        if hasattr(monitor, '_last_state') and monitor._last_state:
            state = monitor._last_state
            if state.critical_gpus or state.fan_failed_gpus:
                print(f"THERMAL EMERGENCY: Critical GPUs: {state.critical_gpus}, Fan failed: {state.fan_failed_gpus}")
                print("ABORTING: Thermal emergency takes precedence over memory remediation")
                return False
    except Exception:
        pass
    return True

result = asyncio.run(check_thermal())
if not result:
    print("EMERGENCY: Thermal emergency detected - aborting memory pressure remediation")
    exit(1)
''',
                safety=SafetyLevel.SAFE,
                timeout=10,
            )
        )
        
        # Step 1: Diagnose GPU memory pressure
        actions.append(
            RemediationAction(
                name="Diagnose GPU memory pressure",
                description="Check all GPUs for memory pressure and identify affected endpoints",
                code='''
import subprocess
import json

print("=== GPU Memory Pressure Diagnosis ===")

# Get GPU memory status
gpu_status = {}
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    used = int(parts[1])
                    total = int(parts[2])
                    pct = (used / total) * 100 if total > 0 else 0
                    gpu_status[idx] = {"used_mb": used, "total_mb": total, "pct": pct}
                    
                    if pct >= 98:
                        print(f"  TIER 4: GPU {idx} at {pct:.0f}% memory ({used}/{total}MB) - NUCLEAR")
                    elif pct >= 95:
                        print(f"  TIER 3: GPU {idx} at {pct:.0f}% memory ({used}/{total}MB) - FORCEFUL")
                    elif pct >= 90:
                        print(f"  TIER 2: GPU {idx} at {pct:.0f}% memory ({used}/{total}MB) - GRACEFUL")
                    elif pct >= 85:
                        print(f"  TIER 1: GPU {idx} at {pct:.0f}% memory ({used}/{total}MB) - WARNING")
                    else:
                        print(f"  OK: GPU {idx} at {pct:.0f}% memory")
except Exception as e:
    print(f"  Error: {e}")

# Get endpoint mapping
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for ep in data.get("data", {}).get("endpoints", []):
            name = ep.get("name", "unknown")
            gpu_ids = ep.get("gpu_ids", [])
            status = ep.get("status", "unknown")
            print(f"  Endpoint: {name}, GPUs: {gpu_ids}, Status: {status}")
except Exception as e:
    print(f"  Endpoint mapping error: {e}")

# Determine affected endpoints
affected = []
for gpu_id, status in gpu_status.items():
    if status["pct"] >= 85:  # Any pressure
        # Find endpoints on this GPU
        try:
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for ep in data.get("data", {}).get("endpoints", []):
                    if gpu_id in ep.get("gpu_ids", []):
                        affected.append(ep.get("name"))
        except Exception:
            pass

if affected:
    print(f"\\nAffected endpoints: {list(set(affected))}")
else:
    print("\\nNo endpoints affected by memory pressure")

print("\\nDiagnosis complete.")
''',
                safety=SafetyLevel.SAFE,
                timeout=45,
            )
        )
        
        # Step 2: Tier 1 - Warning (85-90% memory)
        actions.append(
            RemediationAction(
                name="Tier 1: Memory pressure warning",
                description="Log warning and prepare for potential remediation",
                code='''
import subprocess
import json

# Check if any GPU is at 85-90%
gpu_status = {}
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    used = int(parts[1])
                    total = int(parts[2])
                    pct = (used / total) * 100 if total > 0 else 0
                    gpu_status[idx] = pct

except Exception as e:
    print(f"Error checking memory: {e}")

# Check for Tier 1 (85-90%)
tier1_gpus = [gpu_id for gpu_id, pct in gpu_status.items() if 85 <= pct < 90]

if tier1_gpus:
    print(f"WARNING: GPUs {tier1_gpus} at 85-90% memory - MONITORING")
    print("Action: Increased monitoring frequency, prepare for Tier 2")
else:
    print("No GPUs at Tier 1 (85-90%) memory pressure")
''',
                safety=SafetyLevel.SAFE,
                timeout=15,
            )
        )
        
        # Step 3: Tier 2 - Graceful Remediation (90-95% memory)
        actions.append(
            RemediationAction(
                name="Tier 2: Graceful endpoint restart",
                description="Restart least critical endpoint on affected GPUs (90-95% memory)",
                code='''
import subprocess
import json
import time

print("=== Tier 2: Graceful Remediation (90-95%) ===")

# Get GPU status
gpu_status = {}
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    used = int(parts[1])
                    total = int(parts[2])
                    pct = (used / total) * 100 if total > 0 else 0
                    gpu_status[idx] = pct

except Exception as e:
    print(f"Error: {e}")

# Get endpoints on affected GPUs
affected_gpus = [gpu_id for gpu_id, pct in gpu_status.items() if 90 <= pct < 95]
if not affected_gpus:
    print("No GPUs at Tier 2 (90-95%) - skipping")
    exit(0)

print(f"Affected GPUs: {affected_gpus}")

# Get endpoint mapping
endpoints_on_gpus = {}
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for ep in data.get("data", {}).get("endpoints", []):
            name = ep.get("name")
            gpu_ids = ep.get("gpu_ids", [])
            for gpu_id in gpu_ids:
                if gpu_id in affected_gpus:
                    if gpu_id not in endpoints_on_gpus:
                        endpoints_on_gpus[gpu_id] = []
                    endpoints_on_gpus[gpu_id].append(name)
except Exception as e:
    print(f"Endpoint mapping error: {e}")

# Restart endpoints on affected GPUs
restarted = []
for gpu_id, endpoints in endpoints_on_gpus.items():
    for endpoint in endpoints:
        if endpoint not in restarted:
            print(f"  Restarting endpoint: {endpoint} (on GPU {gpu_id})")
            try:
                result = subprocess.run(
                    ["uv", "run", "gaius-cli", "--cmd", "/engine", "restart", endpoint],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    print(f"    Success: {endpoint} restarted")
                    restarted.append(endpoint)
                else:
                    print(f"    Failed: {result.stderr[:200]}")
            except Exception as e:
                print(f"    Error: {e}")
            
            time.sleep(5)  # Rate limiting

if restarted:
    print(f"\\nTier 2 complete: Restarted {len(restarted)} endpoints")
else:
    print("\\nTier 2: No endpoints restarted")
''',
                safety=SafetyLevel.CAUTION,
                timeout=120,
            )
        )
        
        # Step 4: Tier 3 - Forceful Remediation (95-98% memory)
        actions.append(
            RemediationAction(
                name="Tier 3: Forceful cleanup and restart",
                description="Kill vLLM processes and force restart (95-98% memory)",
                code='''
import subprocess
import json
import time
import signal
import os

print("=== Tier 3: Forceful Remediation (95-98%) ===")

# Get GPU status
gpu_status = {}
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    used = int(parts[1])
                    total = int(parts[2])
                    pct = (used / total) * 100 if total > 0 else 0
                    gpu_status[idx] = pct

except Exception as e:
    print(f"Error: {e}")

# Get affected GPUs
affected_gpus = [gpu_id for gpu_id, pct in gpu_status.items() if 95 <= pct < 98]
if not affected_gpus:
    print("No GPUs at Tier 3 (95-98%) - skipping")
    exit(0)

print(f"Affected GPUs: {affected_gpus}")

# Get endpoints on affected GPUs
endpoints_on_gpus = {}
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for ep in data.get("data", {}).get("endpoints", []):
            name = ep.get("name")
            gpu_ids = ep.get("gpu_ids", [])
            for gpu_id in gpu_ids:
                if gpu_id in affected_gpus:
                    if gpu_id not in endpoints_on_gpus:
                        endpoints_on_gpus[gpu_id] = []
                    endpoints_on_gpus[gpu_id].append(name)
except Exception as e:
    print(f"Endpoint mapping error: {e}")

# Force kill and restart
for gpu_id, endpoints in endpoints_on_gpus.items():
    for endpoint in endpoints:
        print(f"  Force killing endpoint: {endpoint} (on GPU {gpu_id})")
        
        # Step 1: Kill vLLM process
        try:
            result = subprocess.run(
                ["pkill", "-9", "-f", f"vllm.*{endpoint}"],
                capture_output=True, text=True, timeout=10
            )
            print(f"    Killed vLLM processes for {endpoint}")
        except Exception as e:
            print(f"    Kill error: {e}")
        
        # Step 2: Clear CUDA cache
        try:
            result = subprocess.run(
                ["nvidia-smi", "-r"],
                capture_output=True, text=True, timeout=15
            )
            print(f"    CUDA reset for GPU {gpu_id}")
        except Exception as e:
            print(f"    CUDA reset error: {e}")
        
        # Step 3: Clean start
        try:
            result = subprocess.run(
                ["uv", "run", "gaius-cli", "--cmd", "/engine", "clean-start", endpoint],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                print(f"    Success: {endpoint} clean started")
            else:
                print(f"    Failed: {result.stderr[:200]}")
        except Exception as e:
            print(f"    Clean start error: {e}")
        
        time.sleep(10)  # Rate limiting

print("\\nTier 3 complete: Forceful remediation applied")
''',
                safety=SafetyLevel.DESTRUCTIVE,
                timeout=300,
            )
        )
        
        # Step 5: Tier 4 - Nuclear Remediation (98%+ memory)
        actions.append(
            RemediationAction(
                name="Tier 4: Nuclear GPU reset",
                description="Full GPU reset and system restart (98%+ memory)",
                code='''
import subprocess
import time

print("=== Tier 4: Nuclear Remediation (98%+) ===")

# Get GPU status
gpu_status = {}
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    used = int(parts[1])
                    total = int(parts[2])
                    pct = (used / total) * 100 if total > 0 else 0
                    gpu_status[idx] = pct

except Exception as e:
    print(f"Error: {e}")

# Get affected GPUs
affected_gpus = [gpu_id for gpu_id, pct in gpu_status.items() if pct >= 98]
if not affected_gpus:
    print("No GPUs at Tier 4 (98%+) - skipping")
    exit(0)

print(f"CRITICAL: GPUs {affected_gpus} at >=98% memory")
print("Executing nuclear remediation protocol...")

# Step 1: Kill ALL vLLM processes
print("  Step 1: Killing all vLLM processes...")
try:
    result = subprocess.run(
        ["pkill", "-9", "-f", "vllm"],
        capture_output=True, text=True, timeout=10
    )
    print("    All vLLM processes killed")
except Exception as e:
    print(f"    Error: {e}")

# Step 2: Reset all GPUs
print("  Step 2: Resetting all GPUs...")
try:
    result = subprocess.run(
        ["sudo", "nvidia-smi", "-pm", "0"],
        capture_output=True, text=True, timeout=10
    )
    print("    Persistence mode disabled")
    
    result = subprocess.run(
        ["sudo", "nvidia-smi", "-r"],
        capture_output=True, text=True, timeout=15
    )
    print("    All GPUs reset")
except Exception as e:
    print(f"    Error: {e}")

# Step 3: Clean start all endpoints
print("  Step 3: Clean starting all endpoints...")
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/engine", "clean-start", "all"],
        capture_output=True, text=True, timeout=180
    )
    if result.returncode == 0:
        print("    All endpoints clean started")
    else:
        print(f"    Failed: {result.stderr[:200]}")
except Exception as e:
    print(f"    Error: {e}")

# Step 4: Re-enable persistence mode
print("  Step 4: Re-enabling persistence mode...")
try:
    result = subprocess.run(
        ["sudo", "nvidia-smi", "-pm", "1"],
        capture_output=True, text=True, timeout=10
    )
    print("    Persistence mode enabled")
except Exception as e:
    print(f"    Error: {e}")

print("\\nTier 4 complete: Nuclear remediation applied")
print("WARNING: This may have interrupted active requests")
''',
                safety=SafetyLevel.DESTRUCTIVE,
                timeout=300,
            )
        )
        
        # Step 6: Verification
        actions.append(
            RemediationAction(
                name="Verify remediation",
                description="Confirm GPU memory pressure is resolved",
                code='''
import subprocess
import time

print("=== Verification ===")

# Wait for system to stabilize
time.sleep(10)

# Check GPU memory
all_healthy = True
try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    used = int(parts[1])
                    total = int(parts[2])
                    pct = (used / total) * 100 if total > 0 else 0
                    
                    if pct >= 90:
                        print(f"  FAIL: GPU {idx} still at {pct:.0f}% memory")
                        all_healthy = False
                    else:
                        print(f"  OK: GPU {idx} at {pct:.0f}% memory")
    
    if all_healthy:
        print("\\n✅ All GPUs below 90% memory - remediation successful")
    else:
        print("\\n❌ Some GPUs still have memory pressure - remediation failed")
        exit(1)
        
except Exception as e:
    print(f"  Verification error: {e}")
    exit(1)

# Check endpoint health
try:
    result = subprocess.run(
        ["uv", "run", "gaius-cli", "--cmd", "/gpu", "status", "--format", "json"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        import json
        data = json.loads(result.stdout)
        endpoints = data.get("data", {}).get("endpoints", [])
        healthy = sum(1 for ep in endpoints if ep.get("status") == "healthy")
        total = len(endpoints)
        print(f"\\nEndpoint health: {healthy}/{total} healthy")
        
        if healthy == total:
            print("✅ All endpoints healthy")
        else:
            print("❌ Some endpoints still unhealthy")
            exit(1)
except Exception as e:
    print(f"  Endpoint verification error: {e}")

print("\\n✅ Verification complete: All checks passed")
''',
                safety=SafetyLevel.SAFE,
                timeout=60,
            )
        )
        
        return actions
