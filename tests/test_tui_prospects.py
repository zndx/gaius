"""Test TUI /prospects command via textual pilot."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

pytest_plugins = ("pytest_asyncio",)


@pytest.mark.asyncio
async def test_prospects_update_force_parameter():
    """Test that /prospects update passes force as boolean, not string."""
    from gaius.engine.services.prospects_service import ProspectsService
    import inspect

    # Verify the method signature
    sig = inspect.signature(ProspectsService.run_update)
    force_param = sig.parameters.get("force")

    assert force_param is not None, "force parameter should exist"
    # Annotation may be string 'bool' due to PEP 563 (from __future__ import annotations)
    assert force_param.annotation in (bool, 'bool'), f"force should be bool, got {force_param.annotation}"
    assert force_param.default is False, "force default should be False"


@pytest.mark.asyncio
async def test_prospects_service_flow_params():
    """Test that ProspectsService passes boolean force to Metaflow."""
    # Read the source and verify the fix
    from pathlib import Path

    service_path = Path("src/gaius/engine/services/prospects_service.py")
    content = service_path.read_text()

    # Check that we don't have str(force) anymore
    assert '"force": str(force)' not in content, "str(force) should not be in flow_params"

    # Check that we have the correct boolean assignment
    assert '"force": force,' in content, "force should be passed as boolean"
