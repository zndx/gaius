"""Tests for cross-project GPU lease awareness (engine/resources/gpu_leases.py)."""

import json
import os
import subprocess

from gaius.engine.resources.gpu_leases import (
    _ppid_of,
    lease_holder_protecting,
    live_lease_holder_pids,
)


def _write_lease(directory, name, pid):
    (directory / f"{name}.owner.json").write_text(
        json.dumps({"pid": pid, "project": "test", "gpus": [0]})
    )


class TestLiveLeaseHolderPids:
    def test_live_holder_detected(self, tmp_path):
        _write_lease(tmp_path, "gpu-0", os.getpid())
        assert live_lease_holder_pids(tmp_path) == {os.getpid()}

    def test_stale_lease_ignored(self, tmp_path):
        _write_lease(tmp_path, "gpu-0", 4194000)  # beyond pid_max default
        assert live_lease_holder_pids(tmp_path) == set()

    def test_malformed_lease_ignored(self, tmp_path):
        (tmp_path / "gpu-0.owner.json").write_text("not json {")
        _write_lease(tmp_path, "gpu-1", os.getpid())
        assert live_lease_holder_pids(tmp_path) == {os.getpid()}

    def test_missing_dir_empty(self, tmp_path):
        assert live_lease_holder_pids(tmp_path / "nope") == set()


class TestAncestry:
    def test_ppid_of_self(self):
        assert _ppid_of(os.getpid()) == os.getppid()

    def test_holder_itself_protected(self):
        pid = os.getpid()
        assert lease_holder_protecting(pid, {pid}) == pid

    def test_child_process_protected(self):
        # A real child of this process must be protected by our pid
        proc = subprocess.Popen(["sleep", "30"])
        try:
            assert lease_holder_protecting(proc.pid, {os.getpid()}) == os.getpid()
        finally:
            proc.kill()
            proc.wait()

    def test_unrelated_pid_not_protected(self):
        # pid 1 is never our descendant
        assert lease_holder_protecting(1, {os.getpid()}) is None

    def test_no_holders_short_circuits(self):
        assert lease_holder_protecting(os.getpid(), set()) is None
