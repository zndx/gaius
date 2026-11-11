"""Regression guard: the engine must never fork-and-inherit itself.

2026-08-28 outage: GraphRicciCurvature defaulted to a fork-based
multiprocessing.Pool(proc=64). Each worker inherited the :50051 listen
socket. 2026-11-07: proc=1 still builds get_context("fork").Pool, and a
bare joblib.parallel_config() does not leave the threading backend in
place. A card render forked one worker, the parent blocked in the pool
on the asyncio loop, and every UI RPC returned CANCELLED for four days.

Three defenses:

  1. Every OllivierRicci() call pins proc=1 (caps the pool; does not
     remove it — the library has no in-process switch).
  2. install_inprocess_ricci runs that pool on the calling thread.
  3. The engine main() forces the 'spawn' start method, and joblib's
     default backend is threading, so a raw Pool or n_jobs=-1 cannot
     fork-and-inherit the engine.
"""
from __future__ import annotations

import ast
import os
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "gaius"


def _child_pids() -> set[int]:
    me = os.getpid()
    found: set[int] = set()
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            stat = open(f"/proc/{name}/stat").read()
        except OSError:
            continue
        fields = stat[stat.rfind(")") + 2 :].split()
        if len(fields) > 1 and fields[1] == str(me):
            found.add(int(name))
    return found


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


def test_joblib_default_is_threading() -> None:
    """A bare parallel_config() call must not be the pin. The default is."""
    from gaius.core.fork_safety import pin_joblib_threading
    import joblib.parallel as parallel

    pin_joblib_threading()
    assert parallel.DEFAULT_BACKEND == "threading"
    assert parallel.DEFAULT_PROCESS_BACKEND == "threading"


def test_ricci_compute_does_not_fork() -> None:
    """OllivierRicci.compute_ricci_curvature must not spawn a child."""
    import networkx as nx
    from GraphRicciCurvature.OllivierRicci import OllivierRicci

    from gaius.core.fork_safety import install_inprocess_ricci

    install_inprocess_ricci()
    graph = nx.cycle_graph(6)
    for u, v in graph.edges():
        graph[u][v]["weight"] = 1.0
    before = _child_pids()
    orc = OllivierRicci(graph, alpha=0.5, method="OTD", verbose="ERROR", proc=1)
    orc.compute_ricci_curvature()
    after = _child_pids()
    assert after == before, f"ricci forked: {after - before}"
    curved = [
        data.get("ricciCurvature")
        for _u, _v, data in orc.G.edges(data=True)
    ]
    assert curved and all(isinstance(c, float) for c in curved)
