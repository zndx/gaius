"""Engine process management fixtures for BDD testing.

This module provides fixtures for starting and stopping the gaius-engine
daemon during tests, enabling integration testing of engine-dependent features.

The engine uses gRPC transport on port 50051.
"""

import asyncio
import os
import socket
import subprocess
import time
from typing import Optional


class EngineProcessManager:
    """Manages gaius-engine process lifecycle for testing.

    Provides methods to start, stop, and check status of the engine daemon.
    Uses gRPC transport exclusively.
    """

    # Default gRPC settings
    DEFAULT_GRPC_PORT = 50051
    DEFAULT_GRPC_HOST = "localhost"

    # Startup timeout in seconds
    STARTUP_TIMEOUT = 30.0

    # Health check interval
    HEALTH_CHECK_INTERVAL = 0.5

    def __init__(
        self,
        grpc_host: Optional[str] = None,
        grpc_port: Optional[int] = None,
    ):
        """Initialize engine process manager.

        Args:
            grpc_host: gRPC server host
            grpc_port: gRPC server port
        """
        self.grpc_host = grpc_host or os.environ.get("GAIUS_GRPC_HOST", self.DEFAULT_GRPC_HOST)
        self.grpc_port = grpc_port or int(os.environ.get("GAIUS_GRPC_PORT", self.DEFAULT_GRPC_PORT))
        self._process: Optional[subprocess.Popen] = None
        self._started_by_us = False

    def is_grpc_running(self) -> bool:
        """Check if gRPC server is running and accepting connections.

        Returns:
            True if gRPC server is reachable
        """
        try:
            with socket.create_connection((self.grpc_host, self.grpc_port), timeout=2):
                return True
        except (socket.error, socket.timeout):
            return False

    def is_running(self) -> bool:
        """Check if gaius-engine is running via gRPC.

        Returns:
            True if engine is running and accepting connections
        """
        if self.is_grpc_running():
            return True

        # Check if our managed process is running
        if self._process is not None:
            return self._process.poll() is None

        return False

    def start(self) -> bool:
        """Start gaius-engine if not already running.

        Starts the engine with gRPC enabled for proper integration testing.

        Returns:
            True if engine was started successfully or was already running
        """
        if self.is_running():
            return True

        # Prepare environment
        env = os.environ.copy()
        env["GAIUS_GRPC_PORT"] = str(self.grpc_port)
        env["GAIUS_GRPC_HOST"] = self.grpc_host

        # Start gaius-engine
        cmd = ["uv", "run", "gaius-engine"]

        try:
            # Start the engine process
            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,  # Create new process group
            )
            self._started_by_us = True

            # Wait for engine to be ready
            return self._wait_for_ready()

        except FileNotFoundError:
            print("gaius-engine not found - ensure it's in PATH or use 'devenv up'")
            return False
        except Exception as e:
            print(f"Failed to start gaius-engine: {e}")
            return False

    def _wait_for_ready(self) -> bool:
        """Wait for engine to be ready to accept connections.

        Returns:
            True if engine became ready within timeout
        """
        start_time = time.time()

        while time.time() - start_time < self.STARTUP_TIMEOUT:
            if self.is_grpc_running():
                return True
            time.sleep(self.HEALTH_CHECK_INTERVAL)

            # Check if process died
            if self._process is not None and self._process.poll() is not None:
                stdout, stderr = self._process.communicate()
                print(f"Engine process died: {stderr.decode()}")
                return False

        return False

    def stop(self) -> bool:
        """Stop gaius-engine if we started it.

        Returns:
            True if engine was stopped or wasn't running
        """
        if not self._started_by_us or self._process is None:
            return True

        try:
            # Send SIGTERM for graceful shutdown
            self._process.terminate()

            # Wait for graceful shutdown
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown failed
                self._process.kill()
                self._process.wait()

            self._process = None
            self._started_by_us = False

            return True

        except Exception as e:
            print(f"Failed to stop gaius-engine: {e}")
            return False

    def restart(self) -> bool:
        """Restart gaius-engine.

        Returns:
            True if engine was restarted successfully
        """
        self.stop()
        time.sleep(0.5)  # Allow cleanup
        return self.start()

    def get_health(self) -> dict:
        """Get engine health status via gRPC.

        Returns:
            Dict with health information or error
        """
        if not self.is_running():
            return {"status": "not_running", "error": "Engine not running"}

        try:
            from gaius.client.grpc_client import GrpcEngineClient, GrpcClientConfig

            config = GrpcClientConfig(host=self.grpc_host, port=self.grpc_port)
            client = GrpcEngineClient(config)

            async def _get_health():
                if await client.connect():
                    try:
                        return await client.call("Health", "status", {})
                    finally:
                        await client.disconnect()
                return {"status": "error", "error": "Could not connect"}

            return asyncio.get_event_loop().run_until_complete(_get_health())

        except Exception as e:
            return {"status": "error", "error": str(e)}


# Singleton instance for test sharing
_engine_manager: Optional[EngineProcessManager] = None


def get_engine_manager() -> EngineProcessManager:
    """Get or create the engine manager singleton."""
    global _engine_manager
    if _engine_manager is None:
        _engine_manager = EngineProcessManager()
    return _engine_manager


def reset_engine_manager() -> None:
    """Reset the engine manager (for test cleanup)."""
    global _engine_manager
    if _engine_manager is not None:
        _engine_manager.stop()
        _engine_manager = None
