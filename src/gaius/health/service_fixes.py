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
    """Fix strategy for inference endpoints (via orchestrator)."""

    def __init__(self):
        super().__init__("endpoints")

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create actions to fix inference endpoint issues."""
        actions = []

        # This requires gRPC engine to be running
        # If engine is down, we can't restart endpoints via orchestrator
        actions.append(
            RemediationAction(
                name="Restart unhealthy endpoints",
                description="Restart inference endpoints via orchestrator",
                code="""
import asyncio
from gaius.client.engine_proxy import get_orchestrator_proxy

async def restart_endpoints():
    try:
        orch = await get_orchestrator_proxy()
        result = await orch.reconcile_state()
        print(f"Endpoints reconciled: {result}")
        return result
    except Exception as e:
        print(f"Failed to restart endpoints: {e}")
        raise

asyncio.run(restart_endpoints())
""",
                safety=SafetyLevel.CAUTION,
                timeout=60,
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
