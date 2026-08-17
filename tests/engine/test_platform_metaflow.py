"""Signals-present vs standalone Metaflow profile resolution."""

from __future__ import annotations

import pytest

from gaius.flows.platform_metaflow import (
    GURU_NOPLATFORM,
    GURU_NOSCHED,
    PlatformMetaflowError,
    resolve_metaflow_mode,
)


def test_standalone_when_signals_unreachable() -> None:
    d = resolve_metaflow_mode(
        environ={},
        status_probe=lambda addr, t: None,
        ping_probe=lambda url, t: False,
    )
    assert d.mode == "local"
    assert "unreachable" in d.reason


def test_platform_when_scheduler_healthy_and_ping_ok() -> None:
    d = resolve_metaflow_mode(
        environ={},
        status_probe=lambda addr, t: ("signals", [("scheduler", True)]),
        ping_probe=lambda url, t: True,
    )
    assert d.mode == "platform"
    assert d.signals_project == "signals"
    assert d.metaflow_ping_ok


def test_prefers_metaflow_capability_when_advertised() -> None:
    d = resolve_metaflow_mode(
        environ={},
        status_probe=lambda addr, t: (
            "signals",
            [("scheduler", True), ("metaflow", True)],
        ),
        ping_probe=lambda url, t: True,
    )
    assert d.mode == "platform"
    assert "metaflow" in d.reason


def test_fail_fast_when_scheduler_unhealthy() -> None:
    with pytest.raises(PlatformMetaflowError, match=GURU_NOSCHED):
        resolve_metaflow_mode(
            environ={},
            status_probe=lambda addr, t: ("signals", [("scheduler", False)]),
            ping_probe=lambda url, t: True,
        )


def test_fail_fast_when_metaflow_cap_unhealthy() -> None:
    with pytest.raises(PlatformMetaflowError, match=GURU_NOPLATFORM):
        resolve_metaflow_mode(
            environ={},
            status_probe=lambda addr, t: (
                "signals",
                [("scheduler", True), ("metaflow", False)],
            ),
            ping_probe=lambda url, t: True,
        )


def test_fail_fast_when_federated_but_ping_down() -> None:
    with pytest.raises(PlatformMetaflowError, match=GURU_NOPLATFORM):
        resolve_metaflow_mode(
            environ={},
            status_probe=lambda addr, t: ("signals", [("scheduler", True)]),
            ping_probe=lambda url, t: False,
        )


def test_override_local_skips_lattice() -> None:
    d = resolve_metaflow_mode(
        environ={"GAIUS_METAFLOW_MODE": "local"},
        status_probe=lambda addr, t: ("signals", [("scheduler", True)]),
        ping_probe=lambda url, t: False,
    )
    assert d.mode == "local"


def test_override_platform_still_requires_ping() -> None:
    with pytest.raises(PlatformMetaflowError, match=GURU_NOPLATFORM):
        resolve_metaflow_mode(
            environ={"GAIUS_METAFLOW_MODE": "platform"},
            status_probe=lambda addr, t: None,
            ping_probe=lambda url, t: False,
        )


def test_child_env_forces_platform_datastore(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.flows.config import metaflow_child_env

    monkeypatch.setenv("GAIUS_METAFLOW_MODE", "platform")
    monkeypatch.setenv("GAIUS_METAFLOW_SKIP_PING", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "minioadmin")
    monkeypatch.setenv("METAFLOW_DEFAULT_DATASTORE", "local")
    env = metaflow_child_env()
    assert env["GAIUS_METAFLOW_MODE"] == "platform"
    assert env["METAFLOW_DEFAULT_DATASTORE"] == "s3"
    assert env["AWS_ACCESS_KEY_ID"] == "rustfsadmin"
    assert "metaflow/metaflow" in env["METAFLOW_DATASTORE_SYSROOT_S3"]
