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
    """Fix strategy for Python client singletons."""

    def __init__(self):
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


# Service registry - maps service names to strategies
SERVICE_STRATEGIES: dict[str, ServiceFixStrategy] = {
    "engine": EngineFixStrategy(),
    "grpc": EngineFixStrategy(),  # Alias
    "postgres": PostgresFixStrategy(),
    "postgresql": PostgresFixStrategy(),  # Alias
    "database": PostgresFixStrategy(),  # Alias
    "qdrant": QdrantFixStrategy(),
    "minio": MinioFixStrategy(),
    "s3": MinioFixStrategy(),  # Alias
    "singletons": SingletonFixStrategy(),
    "all": AllServicesFixStrategy(),
    "endpoints": EndpointFixStrategy(),
    "inference": EndpointFixStrategy(),  # Alias
    "evolution": EvolutionFixStrategy(),
    "evolve": EvolutionFixStrategy(),  # Alias
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
