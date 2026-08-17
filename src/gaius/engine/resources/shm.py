"""Reclaim leftover vLLM /dev/shm segments.

`--kv-offloading-size N` leaves `/dev/shm/vllm_offload_*.mmap` (N GiB)
after an unclean stop. A handful fill a 63 GiB tmpfs and thinking fails
with "Insufficient space in /dev/shm". Tensor-parallel rings leave
`/dev/shm/psm_*`. Only unlink files with no live `/proc/*/maps` holder.
Never touch PostgreSQL*, gaius-aeron, or other units' files.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

GURU_SHMFULL = "#EP.00000007.SHMFULL"
_RING_SLACK = 512 * 1024 * 1024


def shm_free_bytes(root: Path | None = None) -> int:
    return shutil.disk_usage(str(root or Path("/dev/shm"))).free


def _mapped_basenames() -> set[str]:
    held: set[str] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return held
    for maps in proc.glob("[0-9]*/maps"):
        try:
            text = maps.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if "/dev/shm/" not in line:
                continue
            held.add(Path(line.split()[-1]).name)
    return held


def reclaim_vllm_shm(root: Path | None = None) -> list[str]:
    """Unlink unheld vllm_offload_*.mmap and psm_* under root.

    Returns names removed.
    """
    root = Path(root or "/dev/shm")
    if not root.is_dir():
        return []
    held = _mapped_basenames()
    removed: list[str] = []
    for path in sorted(root.glob("vllm_offload_*.mmap")) + sorted(root.glob("psm_*")):
        if path.name in held:
            logger.info("keep /dev/shm/%s (mapped)", path.name)
            continue
        try:
            path.unlink()
        except OSError as e:
            logger.warning("could not unlink %s: %s", path, e)
            continue
        removed.append(path.name)
    if removed:
        logger.info("reclaimed %d vLLM shm segments; %.1f GiB free",
                    len(removed), shm_free_bytes(root) / 1024**3)
    return removed


def require_shm_for_offload(swap_gib: float | int | None, root: Path | None = None) -> None:
    """Reclaim orphans, then fail-fast if tmpfs cannot hold this endpoint."""
    root = Path(root or "/dev/shm")
    reclaim_vllm_shm(root)
    need = _RING_SLACK
    if swap_gib:
        need += int(float(swap_gib) * 1024**3)
    free = shm_free_bytes(root)
    if free >= need:
        return
    raise RuntimeError(
        f"/dev/shm has {free / 1024**3:.1f} GiB free; need {need / 1024**3:.1f} GiB "
        f"for vLLM offload.\n"
        f"  Guru: {GURU_SHMFULL}\n"
        f"  Try: /health fix endpoints\n"
        f"  Or:  just gpu-cleanup"
    )
