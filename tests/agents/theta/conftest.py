"""Pytest configuration for ThetaAgent tests.

This conftest initializes the JVM BEFORE any test imports that might
trigger DeepOnto's interactive prompt for JVM memory.

DeepOnto's ontology.py does:
    if not jpype.isJVMStarted():
        memory = click.prompt("Please enter the maximum memory...", default="8g")
        init_jvm(memory)

This happens at import time, so we must initialize JVM before importing
deeponto.onto.Ontology.
"""

import os
import pytest

# Set JVM memory env var as early as possible
os.environ.setdefault("JVM_MEMORY", "4g")


@pytest.fixture(scope="session", autouse=True)
def ensure_jvm_initialized():
    """Initialize JVM before any tests run.

    This is a session-scoped fixture that runs automatically.
    It ensures the JVM is started before any test imports deeponto.onto.
    """
    import jpype

    if not jpype.isJVMStarted():
        from deeponto import init_jvm

        memory = os.environ.get("JVM_MEMORY", "4g")
        init_jvm(memory)

    yield

    # JVM cleanup is not needed - jpype handles this at process exit
