"""A missing thinking lane fails the health report.

An empty endpoint list used to be a warning ("no endpoints configured")
while /var/lib/gaius/defer-gpu held preload. That verdict stayed green
on the counts that matter and left the primary lane offline.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest

from gaius.health.checker import CheckStatus, HealthCheck, HealthChecker


class _Health:
    def __init__(self, endpoints: dict):
        self._endpoints = endpoints

    async def check(self):
        return {"endpoints": self._endpoints}


class _DownClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url):
        raise httpx.ConnectError(f"down: {url}")


def _checker(tmp_path):
    return HealthChecker(kb_root=tmp_path)


def test_defer_marker_fails(tmp_path, monkeypatch):
    marker = tmp_path / "defer-gpu"
    marker.write_text("")
    monkeypatch.setenv("GAIUS_DEFER_MARKER", str(marker))
    result = asyncio.run(_checker(tmp_path)._check_gpu_defer())
    assert result.status is CheckStatus.FAIL
    assert "#EP.00000019.GPUDEFER" in result.message
    assert result.suggestion == "just resume-gpu"


def test_defer_marker_absent_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_DEFER_MARKER", str(tmp_path / "missing"))
    result = asyncio.run(_checker(tmp_path)._check_gpu_defer())
    assert result.status is CheckStatus.PASS


def test_empty_endpoints_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_DEFER_MARKER", str(tmp_path / "missing"))

    async def proxy():
        return _Health({})

    monkeypatch.setattr("gaius.client.engine_proxy.get_health_proxy", proxy)
    result = asyncio.run(_checker(tmp_path)._check_endpoints())
    assert result.status is CheckStatus.FAIL
    assert "#EP.00000016.NOTREADY" in result.message
    assert result.fix_service is None
    assert result.suggestion == "/gpu start thinking"


def test_empty_endpoints_under_defer_do_not_autofix(tmp_path, monkeypatch):
    marker = tmp_path / "defer-gpu"
    marker.write_text("")
    monkeypatch.setenv("GAIUS_DEFER_MARKER", str(marker))

    async def proxy():
        return _Health({})

    monkeypatch.setattr("gaius.client.engine_proxy.get_health_proxy", proxy)
    checker = _checker(tmp_path)
    check = next(c for c in checker._checks if c.id == "engine_endpoints")
    result = asyncio.run(checker._run_check(check))
    assert result.status is CheckStatus.FAIL
    assert result.fix_service is None
    assert result.suggestion == "just resume-gpu"


def test_thinking_http_down_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_DEFER_MARKER", str(tmp_path / "missing"))
    monkeypatch.setattr(httpx, "AsyncClient", _DownClient)
    result = asyncio.run(_checker(tmp_path)._check_vllm_direct())
    assert result.status is CheckStatus.FAIL
    assert "thinking" in result.message


def test_explicit_suggestion_is_kept(tmp_path):
    checker = _checker(tmp_path)

    async def named():
        from gaius.health.checker import CheckResult

        return CheckResult(
            name="GPU Workload Hold",
            status=CheckStatus.FAIL,
            message="held",
            suggestion="just resume-gpu",
            fix_service="",
        )

    checker._check_gpu_defer = named  # type: ignore[method-assign]
    check = HealthCheck(
        id="gpu_workload_hold",
        name="GPU Workload Hold",
        category="engine",
        description="",
        check_fn="_check_gpu_defer",
        heuristic_id="inference/gpu_workload_deferred",
        fix_service="endpoints",
    )
    result = asyncio.run(checker._run_check(check))
    assert result.suggestion == "just resume-gpu"
    assert result.fix_service is None


@pytest.mark.parametrize("status", ["healthy", "PROCESS_STATUS_HEALTHY"])
def test_healthy_endpoint_still_passes(tmp_path, monkeypatch, status):
    monkeypatch.setenv("GAIUS_DEFER_MARKER", str(tmp_path / "missing"))

    async def proxy():
        return _Health({"thinking": {"status": status, "port": 0}})

    monkeypatch.setattr("gaius.client.engine_proxy.get_health_proxy", proxy)
    result = asyncio.run(_checker(tmp_path)._check_endpoints())
    assert result.status is CheckStatus.PASS
    assert result.name == "Engine Endpoints"
