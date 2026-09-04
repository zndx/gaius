"""The supervision instance carries an Expectation for every cadenced process,
and the engine-side accessors read them (2026-09-04)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gaius.engine.supervision_spec import load_spec

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = ROOT / "config" / "supervision" / "gaius.textproto"


@pytest.fixture(scope="module")
def spec():
    s = load_spec(force=True)
    assert s is not None, "instance must parse under the current grammar"
    return s


def test_every_cadenced_process_declares_an_expectation(spec) -> None:
    assert spec.undeclared_expectations() == []
    assert len(spec.cadenced()) >= 29


def test_expectations_are_well_formed(spec) -> None:
    from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv

    for p in spec.cadenced():
        e = p.expectation
        assert e.category != sv.EXPECTATION_CATEGORY_UNSPECIFIED, p.id
        assert 0 <= e.horizon_slot <= 9, p.id
        assert e.channel != sv.CHANNEL_UNSPECIFIED, p.id
        assert e.rationale, f"{p.id}: rationale beside the number (rule 3)"
        if e.category == sv.EXPECTATION_CATEGORY_DAILY_DEPENDENT:
            assert spec.process(e.feeds) is not None, f"{p.id} feeds an unknown process {e.feeds!r}"
        if e.category == sv.EXPECTATION_CATEGORY_HOURLY_SETTLED:
            assert e.backfill_depth >= 1, p.id


def test_case_a_class_is_a_tick_with_agenda_horizon(spec) -> None:
    from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv

    e = spec.expectation_for("task.clt_skos_admit")
    assert e.category == sv.EXPECTATION_CATEGORY_TICK and e.horizon_slot == 3 and e.channel == sv.CHANNEL_AGENDA_EVENT


def test_instance_header_for_the_resident_supervisor(spec) -> None:
    assert spec.supervisor.supervisor_grpc == "127.0.0.1:50061"
    assert dict(spec.supervisor.attrs)["timezone"] == "UTC"
    assert dict(spec.supervisor.attrs)["directives"] == "observe"
    assert spec.process("task.objective_verify").cadence.net_seconds == 14400  # the watchdog's 4 h class
    assert spec.sha256 and len(spec.sha256) == 64


def test_rust_validator_accepts_when_present() -> None:
    binary = Path.home() / "local/src/zndx/nautilus/target/release/nautilus"
    if not binary.exists():
        binary = ROOT / "external" / "nautilus" / "target" / "release" / "nautilus"
    if not binary.exists() or shutil.which("true") is None:
        pytest.skip("nautilus validator binary not built")
    r = subprocess.run([str(binary), "validate", "--quiet", str(INSTANCE)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
