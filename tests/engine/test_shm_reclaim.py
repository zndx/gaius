"""Unheld vLLM shm segments are reclaimed; mapped names are kept."""

from __future__ import annotations

from pathlib import Path

from gaius.engine.resources.shm import (
    GURU_SHMFULL,
    reclaim_vllm_shm,
    require_shm_for_offload,
    shm_free_bytes,
)


def test_reclaim_removes_unheld_offload_and_psm(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "vllm_offload_dead.mmap").write_bytes(b"x")
    (tmp_path / "psm_dead").write_bytes(b"y")
    (tmp_path / "PostgreSQL.1").write_bytes(b"pg")
    monkeypatch.setattr(
        "gaius.engine.resources.shm._mapped_basenames",
        lambda: set(),
    )
    removed = reclaim_vllm_shm(tmp_path)
    assert sorted(removed) == ["psm_dead", "vllm_offload_dead.mmap"]
    assert (tmp_path / "PostgreSQL.1").is_file()
    assert not (tmp_path / "vllm_offload_dead.mmap").exists()


def test_reclaim_keeps_mapped(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "vllm_offload_live.mmap").write_bytes(b"x")
    monkeypatch.setattr(
        "gaius.engine.resources.shm._mapped_basenames",
        lambda: {"vllm_offload_live.mmap"},
    )
    assert reclaim_vllm_shm(tmp_path) == []
    assert (tmp_path / "vllm_offload_live.mmap").is_file()


def test_require_shm_fail_fast(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.resources.shm.shm_free_bytes",
        lambda root=None: 1024,
    )
    monkeypatch.setattr(
        "gaius.engine.resources.shm.reclaim_vllm_shm",
        lambda root=None: [],
    )
    try:
        require_shm_for_offload(8, tmp_path)
        raise AssertionError("expected SHMFULL")
    except RuntimeError as e:
        assert GURU_SHMFULL in str(e)


def test_shm_free_bytes_positive() -> None:
    assert shm_free_bytes() > 0
