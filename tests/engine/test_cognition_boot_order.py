"""Cognition must be registered before the thinking preload wait.

Preload blocks until the endpoint is HEALTHY, up to 900s. The Cognition
page calls CognitionSurface as soon as :50051 accepts. A service that
is created only after that wait returns #COG.00000024.NOSVC for the
whole model load (2026-11-11).
"""

from __future__ import annotations

import pathlib

SERVER = pathlib.Path(__file__).resolve().parents[2] / "src" / "gaius" / "engine" / "server.py"


def _start_body() -> str:
    text = SERVER.read_text()
    start = text.split("async def start(", 1)[1]
    return start.split("\n    async def ", 1)[0]


def test_cognition_is_created_before_preload() -> None:
    body = _start_body()
    cog = body.find("await self._autonomous_start_cognition()")
    preload = body.find("await self._autonomous_clean_start_with_progress()")
    assert cog >= 0 and preload >= 0
    assert cog < preload, (
        "cognition must start before the thinking preload wait "
        "(#COG.00000024.NOSVC while vLLM is still loading)"
    )
