"""Shared pytest fixtures for Gaius tests.

This module provides fixtures for:
- CI mode detection and model selection
- llama.cpp server management for inference tests
- Database connections for integration tests
- Engine client for gRPC tests
"""

import os
import subprocess
import time
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# HOCON Config Validation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def validate_hocon_config():
    """Validate HOCON config loads and all sections are present."""
    from gaius.core.config import load_config

    config = load_config()
    # Structural checks — all sections present
    assert hasattr(config, "cloudflare"), "Missing cloudflare config section"
    assert hasattr(config.cloudflare, "r2"), "Missing cloudflare.r2 config section"
    assert hasattr(config.providers, "brave"), "Missing providers.brave config section"
    assert hasattr(config.providers.xai, "management_key"), "Missing providers.xai.management_key"
    # Note: values may be empty in CI — we check structure, not secrets


# ─────────────────────────────────────────────────────────────────────────────
# CI Mode Detection
# ─────────────────────────────────────────────────────────────────────────────


def is_ci_mode() -> bool:
    """Check if running in CI environment."""
    return os.environ.get("GAIUS_CI_MODE") == "1" or os.environ.get("CI") == "true"


@pytest.fixture(scope="session")
def ci_mode() -> bool:
    """Fixture indicating if we're in CI mode."""
    return is_ci_mode()


# ─────────────────────────────────────────────────────────────────────────────
# CI Model Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def ci_model_dir(tmp_path_factory) -> Path:
    """Directory for CI model files.

    Uses /tmp/ci-models if it exists (cached in CI), otherwise creates temp dir.
    """
    cached_dir = Path("/tmp/ci-models")
    if cached_dir.exists():
        return cached_dir
    return tmp_path_factory.mktemp("ci-models")


@pytest.fixture(scope="session")
def ci_qwen_model(ci_model_dir):
    """Download and provide path to CI Qwen model.

    This is the smallest model (~400MB) suitable for most tests.
    """
    from gaius.models import CI_QWEN_TINY

    cfg = CI_QWEN_TINY.llamacpp_config
    if cfg is None:
        pytest.skip("CI_QWEN_TINY has no llamacpp_config")
        return None  # Unreachable, but helps type narrowing

    model_path = ci_model_dir / cfg.gguf_file

    if not model_path.exists():
        # Download model
        cmd = cfg.download_command(str(ci_model_dir))
        subprocess.run(cmd.split(), check=True, timeout=300)

    return model_path


# ─────────────────────────────────────────────────────────────────────────────
# llama.cpp Server Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def llama_server(ci_qwen_model, ci_model_dir):
    """Start llama.cpp server with CI model.

    Yields the server URL. Server is stopped after all tests complete.

    Usage:
        @pytest.mark.inference
        def test_completion(llama_server):
            response = requests.post(
                f"{llama_server}/completion",
                json={"prompt": "Hello", "n_predict": 10}
            )
            assert response.ok
    """
    from gaius.models import CI_QWEN_TINY

    cfg = CI_QWEN_TINY.llamacpp_config
    if cfg is None:
        pytest.skip("CI_QWEN_TINY has no llamacpp_config")
        return  # Unreachable, but helps type narrowing

    # Check if llama-server is available
    try:
        result = subprocess.run(
            ["llama-server", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            pytest.skip("llama-server not available")
    except FileNotFoundError:
        pytest.skip("llama-server not installed")

    # Start server
    cmd = cfg.serve_command(str(ci_model_dir)).split()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready
    server_url = f"http://localhost:{cfg.port}"
    ready = False

    for _ in range(30):
        try:
            import urllib.request

            with urllib.request.urlopen(f"{server_url}/health", timeout=2) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(1)

    if not ready:
        proc.terminate()
        pytest.fail("llama-server failed to start")

    yield server_url

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ─────────────────────────────────────────────────────────────────────────────
# Database Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def database_url():
    """Get database URL from environment or skip test."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Try default devenv configuration
        url = "postgres://postgres:postgres@localhost:5444/zndx_gaius?sslmode=disable"

    # Quick connectivity check
    try:
        import asyncio

        import asyncpg

        async def check():
            conn = await asyncpg.connect(url, timeout=5)
            await conn.close()

        asyncio.get_event_loop().run_until_complete(check())
    except Exception:
        pytest.skip("PostgreSQL not available")

    return url


@pytest.fixture
async def db_pool(database_url):
    """Async database connection pool for tests.

    Usage:
        @pytest.mark.db
        async def test_insert(db_pool):
            await db_pool.execute("INSERT INTO ...")
    """
    import asyncpg

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


# ─────────────────────────────────────────────────────────────────────────────
# Engine Client Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def engine_available():
    """Check if gRPC engine is available."""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("localhost", 50051))
        sock.close()
        return result == 0
    except Exception:
        return False


@pytest.fixture
async def engine_client(engine_available):
    """Async gRPC client for engine tests.

    Usage:
        @pytest.mark.engine
        async def test_status(engine_client):
            status = await engine_client.get_status()
            assert status is not None
    """
    if not engine_available:
        pytest.skip("gRPC engine not available on localhost:50051")

    from gaius.client.grpc_client import GaiusClient

    client = GaiusClient()
    await client.connect()
    yield client
    await client.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test Data Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_inference_request():
    """Sample inference request for testing."""
    return {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello."},
        ],
        "max_tokens": 32,
        "temperature": 0.7,
    }


@pytest.fixture
def sample_scheduling_task():
    """Sample scheduling task for algorithmic tests."""
    from gaius.engine.scheduling.types import SchedulingTask

    return SchedulingTask(
        task_id="test-task",
        endpoint_name="test",
        model_id="test-model",
        required_gpus=1,
    )
