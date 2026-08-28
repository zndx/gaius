"""Regression guard: the engine must never fork-and-inherit itself.

2026-08-28 outage: GraphRicciCurvature defaulted to a fork-based
multiprocessing.Pool(proc=64), forking the whole gaius engine. Each worker
inherited the :50051 listen socket and the live thinking connections; a
deadlocked worker became a rogue duplicate engine that jammed thinking's vLLM
frontend for hours. Two defenses close the class; this locks them so a future
edit cannot silently reopen the door:

  1. Every OllivierRicci() call pins proc=1 (no multiprocessing.Pool at all).
  2. The engine main() forces the 'spawn' start method, so ANY raw
     multiprocessing.Pool re-imports instead of inheriting the engine.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "gaius"


def _ollivier_calls(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "OllivierRicci":
                yield node


def test_ricci_calls_pin_proc_1() -> None:
    """No OllivierRicci may spawn a Pool (proc must be the literal 1)."""
    checked = 0
    for rel in ("core/geometry.py", "engine/services/waterfall_drivers.py"):
        path = SRC / rel
        calls = list(_ollivier_calls(path))
        assert calls, f"no OllivierRicci call in {rel} — is this test stale?"
        for call in calls:
            proc_kw = [k for k in call.keywords if k.arg == "proc"]
            assert proc_kw, (
                f"OllivierRicci at {rel}:{call.lineno} omits proc= — it will fork "
                f"a Pool of cpu_count and inherit the engine (2026-08-28 fork bomb)"
            )
            val = proc_kw[0].value
            assert isinstance(val, ast.Constant) and val.value == 1, (
                f"OllivierRicci at {rel}:{call.lineno} must pass proc=1, not "
                f"{ast.dump(val)}"
            )
            checked += 1
    assert checked >= 2


def test_engine_main_forces_spawn() -> None:
    """The engine process must default multiprocessing to spawn (fork-safety net)."""
    txt = (SRC / "engine" / "server.py").read_text()
    assert 'set_start_method("spawn", force=True)' in txt, (
        "engine main() must force the 'spawn' start method so a raw "
        "multiprocessing.Pool cannot fork-and-inherit the engine"
    )
