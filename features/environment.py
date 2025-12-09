"""Behave environment configuration for Gaius BDD tests.

This module provides the test fixtures and hooks for running
Behave tests against the Gaius TUI application.

Test Tier Architecture:
- Tier 0: CLI Pure (no external dependencies)
- Tier 1: CLI + DB (PostgreSQL)
- Tier 2: CLI + Engine (gaius-engine gRPC)
- Tier 3: MCP Pure (FastMCP in-process)
- Tier 4: MCP + Engine (gaius-engine proxy)
- Tier 5: TUI (Textual Pilot)
- Tier 6: Full Integration (all services)
"""

import asyncio
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

# Textual testing utilities
from textual.pilot import Pilot


def before_all(context):
    """Set up global test configuration."""
    context.project_root = Path(__file__).parent.parent
    context.kb_root = context.project_root / "build" / "test"
    context.config_path = context.project_root / "config" / "test.conf"

    # Ensure test KB directory exists
    context.kb_root.mkdir(parents=True, exist_ok=True)

    # Create standard KB structure
    for subdir in ["current", "scratch", "archive"]:
        (context.kb_root / subdir).mkdir(exist_ok=True)


def before_scenario(context, scenario):
    """Set up each test scenario."""
    # Reset any stateful test data
    context.app = None
    context.pilot = None
    context._app_cm = None  # TUI context manager for proper lifecycle
    context.cli = None  # CLI instance for @cli tagged tests
    context.last_result = None
    context.cli_results = []  # Track CLI results for workflow tests
    context._env_vars_to_restore = {}  # Track env vars modified by tests
    context._created_kb_files = []  # Track KB files created for cleanup

    # Create fresh test event loop
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)

    # Generate scenario ID for isolation
    context.scenario_id = str(uuid.uuid4())[:8]

    # Get scenario tags (might be a set or list)
    # In Behave, scenario.effective_tags includes inherited feature tags
    tags = set()
    if hasattr(scenario, 'effective_tags'):
        tags = set(scenario.effective_tags)
    elif hasattr(scenario, 'tags'):
        tags = set(scenario.tags)
    context.scenario_tags = tags

    # Skip @db-required tests when database isn't available
    if "db-required" in tags:
        db_url = os.environ.get("GAIUS_DATABASE_URL", "")
        if not db_url or not _check_db_available(db_url):
            scenario.skip(
                "Skipping @db-required test - no database available. "
                "Set GAIUS_DATABASE_URL to run database-dependent tests."
            )
            return

    # @engine-integration tests will start the engine if needed.
    # The "gaius-engine is running" step handles starting the engine.
    # We don't skip these tests - they should fail if engine can't start.

    # Clean up known MCP test files before @mcp scenarios
    if "mcp" in tags:
        _cleanup_mcp_test_files(context)

    # Skip @grpc-integration tests when gRPC server isn't available
    if "grpc-integration" in tags:
        if not _check_grpc_available():
            scenario.skip(
                "Skipping @grpc-integration test - gRPC server not running. "
                "Set GAIUS_RUN_GRPC_TESTS=true and start gaius-engine."
            )
            return

    # Per-scenario KB isolation for tests that need it
    # Creates: build/test/scratch/{date}/{scenario-id}/
    if "isolated-kb" in tags or "mcp" in tags:
        today = datetime.now().strftime("%Y-%m-%d")
        context.scenario_kb_root = (
            context.kb_root / "scratch" / today / context.scenario_id
        )
        context.scenario_kb_root.mkdir(parents=True, exist_ok=True)

        # Create standard structure in isolated KB
        for subdir in ["current", "scratch", "archive"]:
            (context.scenario_kb_root / subdir).mkdir(exist_ok=True)

        # Set environment to use isolated KB
        context._env_vars_to_restore["GAIUS_KB_ROOT"] = os.environ.get("GAIUS_KB_ROOT")
        os.environ["GAIUS_KB_ROOT"] = str(context.scenario_kb_root)
    else:
        context.scenario_kb_root = None


def _cleanup_mcp_test_files(context):
    """Clean up known test files from previous MCP test runs.

    This ensures test isolation by removing files that MCP tests
    expect to create fresh each run.
    """
    test_files = [
        "scratch/mcp_test.md",
        "scratch/read_test.md",
        "scratch/update_test.md",
        "scratch/delete_test.md",
        "scratch/search_test.md",
    ]

    kb_root = getattr(context, 'kb_root', Path("build/test"))

    for rel_path in test_files:
        full_path = kb_root / rel_path
        if full_path.exists():
            try:
                full_path.unlink()
            except Exception:
                pass  # Ignore cleanup failures


def _check_db_available(db_url: str) -> bool:
    """Check if database is available."""
    try:
        # Quick check - just test if we can import asyncpg
        import asyncpg
        # Don't actually connect - too slow for before_scenario
        # Just check if URL looks valid
        return db_url.startswith("postgres")
    except ImportError:
        return False


def _check_engine_available() -> bool:
    """Check if gaius-engine is available via gRPC.

    Returns True if the gRPC server is reachable on port 50051.
    """
    return _check_grpc_available()


def _check_grpc_available() -> bool:
    """Check if gRPC server is available.

    Returns True if the gRPC server is reachable on the configured host/port.
    """
    import socket
    host = os.environ.get("GAIUS_GRPC_HOST", "localhost")
    port = int(os.environ.get("GAIUS_GRPC_PORT", "50051"))

    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (socket.error, socket.timeout):
        return False


def _cleanup_gpu_processes(context) -> None:
    """Aggressively cleanup vLLM processes and GPU memory.

    This is critical for tier-4+ tests where tensor-parallel vLLM instances
    can leave orphaned workers that hold GPU memory.
    """
    import subprocess
    import time

    # Kill all vLLM processes aggressively
    # Using multiple patterns to catch all variants
    patterns = ["vllm", "VLLM"]
    for pattern in patterns:
        try:
            subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

    # Wait for processes to die and GPU memory to be released
    time.sleep(2)

    # Verify GPU memory is free (with timeout)
    for attempt in range(10):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                mem_values = []
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        try:
                            mem_values.append(float(line.strip()))
                        except ValueError:
                            pass
                # Check if all GPUs have less than 500 MiB in use
                if mem_values and all(m < 500 for m in mem_values):
                    break
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        time.sleep(2)


def after_scenario(context, scenario):
    """Clean up after each scenario."""
    # Close TUI app properly using context manager if available
    if hasattr(context, '_app_cm') and context._app_cm is not None:
        try:
            context.loop.run_until_complete(context._app_cm.__aexit__(None, None, None))
        except Exception:
            pass
    elif context.pilot:
        try:
            context.loop.run_until_complete(context.pilot.exit_app())
        except Exception:
            pass

    # Content pipeline cleanup
    if hasattr(context, 'service_manager') and context.service_manager:
        try:
            context.loop.run_until_complete(context.service_manager.stop_all())
        except Exception:
            pass

    if hasattr(context, 'db_manager') and context.db_manager:
        try:
            context.loop.run_until_complete(context.db_manager.cleanup())
            context.loop.run_until_complete(context.db_manager.disconnect())
        except Exception:
            pass

    if hasattr(context, 'inference_manager') and context.inference_manager:
        try:
            context.loop.run_until_complete(context.inference_manager.close())
        except Exception:
            pass

    if hasattr(context, 'kb_manager') and context.kb_manager:
        try:
            context.kb_manager.cleanup()
        except Exception:
            pass

    # GPU-intensive test cleanup (tier-4, tier-5, QwQ tests)
    # This ensures vLLM tensor-parallel workers are killed and GPU memory is freed
    gpu_tags = {'tier-4', 'tier-5', 'qwq', 'llm-reflection', 'engine-integration'}
    if context.scenario_tags & gpu_tags:
        _cleanup_gpu_processes(context)

    # Note: We don't stop infrastructure_manager here to allow
    # postgres to keep running between test scenarios

    # Clean up gRPC clients (must be before loop close)
    if context.loop and not context.loop.is_closed():
        if hasattr(context, 'grpc_client') and context.grpc_client:
            try:
                context.loop.run_until_complete(context.grpc_client.disconnect())
            except Exception:
                pass

        if hasattr(context, 'test_client') and context.test_client:
            try:
                context.loop.run_until_complete(context.test_client.disconnect())
            except Exception:
                pass

    # Clean up event loop (after all async operations)
    if context.loop:
        context.loop.close()

    # Clean up MCP server singleton
    if hasattr(context, 'mcp_server'):
        try:
            from gaius.storage.factory import reset_storage
            reset_storage()
        except ImportError:
            pass

    # Clean up created KB files (for non-isolated scenarios)
    if hasattr(context, '_created_kb_files'):
        for file_path in context._created_kb_files:
            try:
                if file_path.exists():
                    file_path.unlink()
            except Exception:
                pass

    # Restore all modified environment variables
    if hasattr(context, '_env_vars_to_restore'):
        for var, original_value in context._env_vars_to_restore.items():
            if original_value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = original_value

    # Legacy environment backups (for backwards compatibility)
    if hasattr(context, '_env_backup_fallbacks'):
        if context._env_backup_fallbacks is None:
            os.environ.pop("GAIUS_ALLOW_FALLBACKS", None)
        else:
            os.environ["GAIUS_ALLOW_FALLBACKS"] = context._env_backup_fallbacks

    if hasattr(context, '_env_backup_transport'):
        if context._env_backup_transport is None:
            os.environ.pop("GAIUS_TRANSPORT", None)
        else:
            os.environ["GAIUS_TRANSPORT"] = context._env_backup_transport


def before_feature(context, feature):
    """Set up each feature."""
    pass


def after_feature(context, feature):
    """Clean up after each feature."""
    pass


async def start_app(context):
    """Start the Gaius TUI app for testing.

    Returns a Pilot instance for interacting with the app.
    Uses manual context manager control to keep pilot alive across steps.

    The pilot lifecycle is managed via context._app_cm which is cleaned up
    in after_scenario. This allows the pilot to persist across multiple
    step definitions within a scenario.
    """
    from gaius.app import GaiusApp

    app = GaiusApp()
    context.app = app

    # Use manual context manager control to keep pilot alive across steps
    # The __aexit__ will be called in after_scenario
    context._app_cm = app.run_test()
    context.pilot = await context._app_cm.__aenter__()
    return context.pilot


def run_async(context, coro):
    """Run an async coroutine in the test context."""
    return context.loop.run_until_complete(coro)
