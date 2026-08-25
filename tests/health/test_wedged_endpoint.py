"""A wedged endpoint is alive, bound, and serving nothing.

Reproduced here with a black-hole server: it completes the TCP handshake and
then never writes a byte, which is exactly what thinking :8081 did on
2026-08-25 while holding four GPUs at 0% utilisation for seven hours.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from gaius.health.wedged_endpoint import (
    DEFAULT_MIN_UPTIME_S,
    GURU_WEDGED,
    EndpointProbe,
    EndpointVerdict,
    _model_from_argv,
    _port_from_argv,
    probe_endpoint,
    remediate_wedged,
    summarize,
)


class BlackHole:
    """Accepts connections, answers nothing. A wedged server in miniature."""

    def __init__(self) -> None:
        self._server: asyncio.AbstractServer | None = None
        self._stop = asyncio.Event()
        self._live: set[asyncio.Task] = set()
        self.port = 0

    async def __aenter__(self) -> "BlackHole":
        async def _swallow(reader, writer):
            # Hold the connection open until teardown. Waiting on an event
            # (not sleep) keeps wait_closed() from blocking for an hour.
            task = asyncio.current_task()
            if task is not None:
                self._live.add(task)
            try:
                await self._stop.wait()
            finally:
                writer.close()
                if task is not None:
                    self._live.discard(task)

        self._server = await asyncio.start_server(_swallow, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        self._stop.set()
        for task in list(self._live):
            task.cancel()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


class Responder:
    """Answers a minimal HTTP 200 — a healthy endpoint in miniature."""

    def __init__(self) -> None:
        self._server: asyncio.AbstractServer | None = None
        self.port = 0

    async def __aenter__(self) -> "Responder":
        async def _reply(reader, writer):
            try:
                await reader.readline()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                await writer.drain()
            except Exception:
                pass
            finally:
                writer.close()

        self._server = await asyncio.start_server(_reply, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestVerdicts:
    @pytest.mark.asyncio
    async def test_a_responding_endpoint_is_healthy(self):
        async with Responder() as srv:
            p = await probe_endpoint(
                srv.port, pid=os.getpid(), probes=2, timeout_s=2.0, gap_s=0.01
            )
        assert p.verdict is EndpointVerdict.HEALTHY
        assert p.responded and not p.is_wedged
        assert p.attempts == 1, "a healthy endpoint should not need a retry"

    @pytest.mark.asyncio
    async def test_black_hole_past_the_floor_is_wedged(self):
        """The real failure: handshake succeeds, nothing ever comes back."""
        async with BlackHole() as srv:
            p = await probe_endpoint(
                srv.port,
                pid=os.getpid(),
                model="Qwen/Qwen3.8-27B",
                probes=2,
                timeout_s=0.4,
                gap_s=0.01,
                min_uptime_s=0.0,
            )
        assert p.verdict is EndpointVerdict.WEDGED
        assert p.is_wedged
        assert p.attempts == 2, "must miss repeatedly before calling it wedged"
        assert not p.responded

    @pytest.mark.asyncio
    async def test_no_process_is_down_not_wedged(self):
        p = await probe_endpoint(_free_port(), pid=None, probes=1, timeout_s=0.3)
        assert p.verdict is EndpointVerdict.DOWN
        assert not p.is_wedged


class TestStartupGuard:
    """The guard that makes this safe to automate.

    A cold start holds the process alive and unresponsive for up to
    VLLMController._startup_timeout (900s). Killing a loading endpoint would
    be far worse than waiting out a hung one, so anything younger than the
    floor is STARTING and is never remediated.
    """

    @pytest.mark.asyncio
    async def test_young_unresponsive_endpoint_is_starting(self):
        async with BlackHole() as srv:
            p = await probe_endpoint(
                srv.port,
                pid=os.getpid(),  # this test process is seconds old
                probes=1,
                timeout_s=0.3,
                min_uptime_s=DEFAULT_MIN_UPTIME_S,
            )
        assert p.verdict is EndpointVerdict.STARTING
        assert not p.is_wedged
        assert "cold start" in p.detail

    def test_the_floor_matches_the_controller_startup_timeout(self):
        """If the controller's budget grows, the floor must grow with it."""
        import re
        from pathlib import Path

        src = Path("src/gaius/engine/backends/vllm_controller.py").read_text()
        m = re.search(r"self\._startup_timeout\s*=\s*(\d+)", src)
        assert m, "could not read _startup_timeout"
        assert DEFAULT_MIN_UPTIME_S >= float(m.group(1)), (
            "the wedged floor must not be shorter than a legal cold start"
        )

    @pytest.mark.asyncio
    async def test_remediation_refuses_anything_not_wedged(self):
        for verdict in (
            EndpointVerdict.HEALTHY,
            EndpointVerdict.STARTING,
            EndpointVerdict.DOWN,
            EndpointVerdict.UNKNOWN,
        ):
            probe = EndpointProbe(port=1, pid=os.getpid(), verdict=verdict)
            out = await remediate_wedged(probe)
            assert not out.success
            assert "refusing" in out.error
            assert out.signalled == [], "must not signal a non-wedged endpoint"


class TestRemediation:
    @pytest.mark.asyncio
    async def test_sigterm_ends_a_cooperative_process(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(300)"
        )
        probe = EndpointProbe(
            port=1, pid=proc.pid, verdict=EndpointVerdict.WEDGED, uptime_s=99999
        )
        out = await remediate_wedged(probe, term_grace_s=5.0, poll_s=0.2)
        await proc.wait()
        assert out.success
        assert out.signalled == ["SIGTERM"], "SIGKILL was not needed"

    @pytest.mark.asyncio
    async def test_escalates_to_sigkill_when_sigterm_is_ignored(self):
        """A futex-blocked engine core routinely ignores SIGTERM."""
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import signal,time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(300)",
        )
        await asyncio.sleep(0.5)  # let the handler install
        probe = EndpointProbe(
            port=1, pid=proc.pid, verdict=EndpointVerdict.WEDGED, uptime_s=99999
        )
        out = await remediate_wedged(probe, term_grace_s=1.0, poll_s=0.2)
        await proc.wait()
        assert out.success
        assert out.signalled == ["SIGTERM", "SIGKILL"]

    @pytest.mark.asyncio
    async def test_already_gone_is_success(self):
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        await proc.wait()
        probe = EndpointProbe(
            port=1, pid=proc.pid, verdict=EndpointVerdict.WEDGED, uptime_s=99999
        )
        out = await remediate_wedged(probe, term_grace_s=0.5, poll_s=0.1)
        # The pid may be reaped or reused-safe; either way we must not error.
        assert out.error == "" or "cannot signal" in out.error

    @pytest.mark.asyncio
    async def test_no_pid_is_refused(self):
        probe = EndpointProbe(port=1, pid=None, verdict=EndpointVerdict.WEDGED)
        out = await remediate_wedged(probe)
        assert not out.success
        assert "no pid" in out.error


class TestArgvParsing:
    """Endpoints are discovered from argv so a blocked engine cannot hide one."""

    def test_reads_port_and_model_from_a_real_serve_line(self):
        argv = [
            "/venv/bin/python3",
            "/venv/bin/vllm",
            "serve",
            "Qwen/Qwen3.8-27B",
            "--port",
            "8081",
            "--tensor-parallel-size",
            "4",
        ]
        assert _port_from_argv(argv) == 8081
        assert _model_from_argv(argv) == "Qwen/Qwen3.8-27B"

    def test_reads_the_equals_form(self):
        assert _port_from_argv(["vllm", "serve", "m", "--port=8090"]) == 8090

    def test_missing_or_bad_port_is_none(self):
        assert _port_from_argv(["vllm", "serve", "m"]) is None
        assert _port_from_argv(["vllm", "serve", "m", "--port", "auto"]) is None

    def test_model_absent_when_serve_is_last(self):
        assert _model_from_argv(["vllm", "serve"]) == ""
        assert _model_from_argv(["vllm", "--port", "1"]) == ""


class TestReporting:
    def test_summary_names_the_guru_only_when_wedged(self):
        healthy = [EndpointProbe(port=8081, verdict=EndpointVerdict.HEALTHY)]
        assert summarize(healthy)["guru_meditation"] is None
        assert summarize(healthy)["remediation"] is None

        wedged = [
            EndpointProbe(
                port=8081, pid=42, verdict=EndpointVerdict.WEDGED, uptime_s=27000
            )
        ]
        s = summarize(wedged)
        assert s["guru_meditation"] == GURU_WEDGED
        assert s["wedged"] == 1
        assert s["remediation"] == "/health fix endpoints"

    def test_guru_report_is_actionable(self):
        p = EndpointProbe(
            port=8081,
            pid=1328077,
            model="Qwen/Qwen3.8-27B",
            uptime_s=27000,
            attempts=3,
            verdict=EndpointVerdict.WEDGED,
            detail="3 probes timed out",
            close_wait=18,
        )
        text = p.guru_report()
        assert GURU_WEDGED in text
        assert "8081" in text and "1328077" in text
        assert "/health fix endpoints" in text
        assert "7.5h" in text
