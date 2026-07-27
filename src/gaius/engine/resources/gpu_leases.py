"""Cross-project GPU lease awareness.

Sibling zndx engines (aegir, atelier) register advisory GPU leases in a
shared directory (default ``/tmp/zndx-gpu-leases``): per-GPU-set lock files
beside ``*.owner.json`` payloads carrying the holder's pid and project.
Gaius cleanup paths must never kill a live lease holder or its descendants
— those are the sibling engines' vLLM workers, not stale gaius processes.

Bash twin: ``scripts/lib/gpu-helpers.sh`` (``_kill_unleased``) guards the
shell cleanup paths (engine startup, ``just gpu-cleanup``/``gpu-deep-cleanup``);
this module guards the engine-internal paths (``cleanup_stale_processes``).

A stale lease (holder pid no longer running) is ignored, so dead siblings
never block cleanup. If the lease dir is missing or unreadable, behavior
degrades to the historical kill-everything semantics.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LEASE_DIR = Path("/tmp/zndx-gpu-leases")


def _lease_dir(lease_dir: Path | None = None) -> Path:
    if lease_dir is not None:
        return lease_dir
    return Path(os.environ.get("ZNDX_GPU_LEASE_DIR", str(DEFAULT_LEASE_DIR)))


def live_lease_holder_pids(lease_dir: Path | None = None) -> set[int]:
    """Return pids of live cross-project lease holders.

    Reads every ``*.owner.json`` in the lease dir; entries whose pid is no
    longer running (stale leases) are ignored. Malformed files are logged
    and skipped — a broken lease must not block cleanup.
    """
    holders: set[int] = set()
    directory = _lease_dir(lease_dir)
    try:
        owner_files = sorted(directory.glob("*.owner.json"))
    except OSError:
        return holders

    for owner_file in owner_files:
        try:
            payload = json.loads(owner_file.read_text())
            pid = int(payload["pid"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning(f"Ignoring malformed GPU lease {owner_file}: {e}")
            continue
        if Path(f"/proc/{pid}").is_dir():
            holders.add(pid)
    return holders


def _ppid_of(pid: int) -> int | None:
    """Parent pid of ``pid`` via /proc, robust to spaces/parens in comm."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # Format: "pid (comm) state ppid ..." — comm may contain ') ' itself,
    # so split after the LAST closing paren.
    fields = stat.rpartition(")")[2].split()
    try:
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def lease_holder_protecting(pid: int, holders: set[int] | None = None) -> int | None:
    """Return the lease-holder pid protecting ``pid``, or None.

    A pid is protected when it *is* a live lease holder or is a descendant
    of one (vLLM workers are children of the sibling engine's supervisor).
    """
    if holders is None:
        holders = live_lease_holder_pids()
    if not holders:
        return None

    current: int | None = pid
    for _ in range(64):  # bounded ancestry walk
        if current is None or current <= 1:
            return None
        if current in holders:
            return current
        current = _ppid_of(current)
    return None
