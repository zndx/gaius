"""Read the project's zndx.supervision.v1 instance (config/supervision/*.textproto).

The instance is the DECLARED shape of the stack: processes, machines with
phases and gates, objectives, and — since 2026-09-04 — resource intents
(occupancy / floor / priority per phase or standing per process). The engine
consults it at the seams where a claim is made, so what is sent to the
federation's arbiter is what the spec declares, not what the admission code
happens to compute.

v1 emitter scope: intent lookup by (owner kind, workload). Phase awareness
arrives with position reporting; until then the lookup is conservative —
across an owner's phases it takes the intent with the highest floor (and that
intent's priority), so a run is never under-protected because the claim
happened before its protecting phase.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("gaius.engine.supervision_spec")

GURU_SPECLOAD = "#SV.00000001.SPECLOAD"


@dataclass(frozen=True)
class Intent:
    leaf: str
    workload: str
    occupancy: int
    floor: int
    priority: int
    owner: str          # process id or machine id that declared it
    phase: str = ""     # "" for standing intents
    rationale: str = ""


def _repo_root() -> Path:
    for key in ("GAIUS_ROOT", "GAIUS_REPO_ROOT", "DEVENV_ROOT"):
        v = os.environ.get(key)
        if v:
            return Path(v)
    return Path(__file__).resolve().parents[3]


def spec_path() -> Path:
    override = (os.environ.get("GAIUS_SUPERVISION_SPEC") or "").strip()
    return Path(override) if override else _repo_root() / "config" / "supervision" / "gaius.textproto"


def _kind_of_process_id(pid: str) -> str:
    """'task.prospects_update' -> 'prospects-update'; 'flow.X' -> 'flow.X'."""
    if pid.startswith("task."):
        return pid[len("task."):].replace("_", "-")
    return pid


class SupervisionSpec:
    """Parsed instance with an index of intents by (owner kind, workload)."""

    def __init__(self, supervisor: Any, path: Path):
        self.supervisor = supervisor
        self.path = path
        self._standing: dict[str, list[Intent]] = {}       # workload -> intents
        self._by_owner: dict[str, dict[str, list[Intent]]] = {}  # owner kind -> workload -> intents
        procs = {p.id: p for p in supervisor.processes}
        for p in supervisor.processes:
            for r in p.resources:
                it = Intent(r.leaf, r.workload, r.occupancy, r.floor, r.priority, p.id, "", r.rationale)
                self._standing.setdefault(r.workload, []).append(it)
        for m in supervisor.machines:
            owners = {m.id}
            proc = procs.get(m.process)
            if proc is not None:
                owners.add(_kind_of_process_id(proc.id))
                if proc.parent:
                    owners.add(_kind_of_process_id(proc.parent))
            owners.add(m.process)
            for ph in m.phases:
                for r in ph.resources:
                    it = Intent(r.leaf, r.workload, r.occupancy, r.floor, r.priority, m.id, ph.id, r.rationale)
                    for o in owners:
                        self._by_owner.setdefault(o, {}).setdefault(r.workload, []).append(it)

    def intent_for(self, owner: str, workload: str) -> Intent | None:
        """Most protective intent an owner declares for a workload, else the
        workload's standing intent, else None (legacy behaviour applies)."""
        owner = (owner or "").replace("_", "-")
        workload = (workload or "").replace("_", "-")
        cands = self._by_owner.get(owner, {}).get(workload) or []
        if not cands and owner.startswith("task."):
            cands = self._by_owner.get(_kind_of_process_id(owner), {}).get(workload) or []
        if cands:
            return max(cands, key=lambda i: (i.floor, i.priority))
        standing = self._standing.get(workload) or []
        if standing:
            return max(standing, key=lambda i: (i.floor, i.priority))
        return None

    def standing(self) -> list[Intent]:
        return [i for lst in self._standing.values() for i in lst]

    # ── phase lookup (for emission on phase transitions) ─────────────────
    def machine_for(self, owner: str) -> Any | None:
        """The Machine whose process (or its parent task) is this owner kind."""
        owner = (owner or "").replace("_", "-")
        procs = {p.id: p for p in self.supervisor.processes}
        for m in self.supervisor.machines:
            proc = procs.get(m.process)
            kinds = {m.id, m.process}
            if proc is not None:
                kinds.add(_kind_of_process_id(proc.id))
                if proc.parent:
                    kinds.add(_kind_of_process_id(proc.parent))
            if owner in kinds:
                return m
        return None

    def phase_for_step(self, owner: str, step: str) -> tuple[str, Any] | None:
        """(machine_id, Phase) whose `steps` include this source step name."""
        m = self.machine_for(owner)
        if m is None:
            return None
        for ph in m.phases:
            if step in ph.steps:
                return m.id, ph
        return None

    @staticmethod
    def phase_intents(phase: Any, machine_id: str) -> list[Intent]:
        return [
            Intent(r.leaf, r.workload, r.occupancy, r.floor, r.priority, machine_id, phase.id, r.rationale)
            for r in phase.resources
        ]


_LOCK = threading.Lock()
_CACHE: tuple[float, SupervisionSpec] | None = None


def load_spec(force: bool = False) -> SupervisionSpec | None:
    """Parse (and cache by mtime) the instance. Returns None, loudly, when the
    file is missing or unparseable — callers fall back to legacy admission
    behaviour rather than inventing intents."""
    global _CACHE
    path = spec_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        log.warning("%s supervision instance not found at %s — legacy admission floors", GURU_SPECLOAD, path)
        return None
    with _LOCK:
        if not force and _CACHE is not None and _CACHE[0] == mtime:
            return _CACHE[1]
        try:
            from google.protobuf import text_format
            from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as v

            sup = text_format.Parse(path.read_text(encoding="utf-8"), v.Supervisor())
            spec = SupervisionSpec(sup, path)
        except Exception as e:  # noqa: BLE001 — surfaced, never masked
            log.warning("%s supervision instance unparseable (%s): %s", GURU_SPECLOAD, path, e)
            return None
        _CACHE = (mtime, spec)
        log.info(
            "supervision instance loaded: %s (%d processes, %d machines, %d standing intents)",
            path.name, len(sup.processes), len(sup.machines), len(spec.standing()),
        )
        return spec


def intent_for(owner: str, workload: str) -> Intent | None:
    spec = load_spec()
    return spec.intent_for(owner, workload) if spec is not None else None
