"""Thinking stays on GPUs 0–3. A foreign lease must not slide it onto 4–5."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaius.engine.resources.allocations import ResourceUnavailable
from gaius.engine.resources.manager import LEFTOVER_GPUS, THINKING_GPUS, ResourceManager


def _manager(tmp_path, monkeypatch) -> ResourceManager:
    monkeypatch.setenv("ZNDX_GPU_LEASE_DIR", str(tmp_path))
    config = SimpleNamespace(
        gpus=SimpleNamespace(total=6, reserved=[]),
        scheduling=SimpleNamespace(prefer_contiguous=True, allocation_timeout=1),
    )
    return ResourceManager(config)


def _agent(gpus: int):
    return SimpleNamespace(model="m", resources=SimpleNamespace(gpus=gpus, vram_gb=20))


def test_thinking_is_pinned_to_0_3(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    alloc = mgr.allocate("thinking", _agent(4))
    assert alloc.gpu_ids == list(THINKING_GPUS)


def test_a_foreign_lease_does_not_slide_thinking_onto_the_leftover_pair(tmp_path, monkeypatch):
    (tmp_path / "aegir-gpu0.owner.json").write_text(
        '{"pid": 1, "project": "aegir", "gpus": [0]}'
    )
    # pid 1 is init and is alive, so the lease counts.
    mgr = _manager(tmp_path, monkeypatch)
    with pytest.raises(ResourceUnavailable, match="does not slide"):
        mgr.allocate("thinking", _agent(4))
    assert "thinking" not in mgr.allocations


def test_ask_sae_uses_the_leftover_pair(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    mgr.allocate("thinking", _agent(4))
    alloc = mgr.allocate("ask-sae", _agent(2))
    assert alloc.gpu_ids == list(LEFTOVER_GPUS)
