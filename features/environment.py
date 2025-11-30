"""Behave environment configuration for Gaius BDD tests.

This module provides the test fixtures and hooks for running
Behave tests against the Gaius TUI application.
"""

import asyncio
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


def before_scenario(context, scenario):
    """Set up each test scenario."""
    # Reset any stateful test data
    context.app = None
    context.pilot = None
    context.last_result = None

    # Create fresh test event loop
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)


def after_scenario(context, scenario):
    """Clean up after each scenario."""
    # Close any open app
    if context.pilot:
        try:
            context.loop.run_until_complete(context.pilot.exit_app())
        except Exception:
            pass

    # Clean up event loop
    if context.loop:
        context.loop.close()


def before_feature(context, feature):
    """Set up each feature."""
    pass


def after_feature(context, feature):
    """Clean up after each feature."""
    pass


async def start_app(context):
    """Start the Gaius TUI app for testing.

    Returns a Pilot instance for interacting with the app.
    """
    from gaius.app import GaiusApp

    app = GaiusApp()
    context.app = app
    context.pilot = Pilot(app)
    await context.pilot.__aenter__()
    return context.pilot


def run_async(context, coro):
    """Run an async coroutine in the test context."""
    return context.loop.run_until_complete(coro)
