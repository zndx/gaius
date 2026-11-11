"""Stop the long-running engine from fork-inheriting itself.

Two doors, both open on 2026-11-07:

* ``joblib.parallel_config(...)`` without ``with`` builds a context manager
  and throws it away. The default backend stays ``loky``. ``n_jobs=-1`` then
  fork-execs workers that inherit :50051 and every locked thread.
* ``GraphRicciCurvature`` always does
  ``multiprocessing.get_context("fork").Pool``, even at ``proc=1``.
  The library says spawn hangs because the edge kernel reads process
  globals. Fork copies those globals, and also the listen socket.
  The worker deadlocks; the parent blocks in ``Pool.join`` on the
  asyncio loop; every new RPC returns CANCELLED.

``pin_joblib_threading`` sets the real default. ``install_inprocess_ricci``
runs that same edge kernel on the calling thread for the duration of the
call, then puts ``get_context`` back.
"""

from __future__ import annotations

import threading

_RICCI_LOCK = threading.Lock()
_RICCI_INSTALLED = False


class _InProcessPool:
    """Pool surface GraphRicci uses, with no child process."""

    def __init__(self, processes: int | None = None, *args: object, **kwargs: object) -> None:
        self._processes = processes

    def __enter__(self) -> _InProcessPool:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def imap_unordered(self, func, iterable, chunksize: int | None = None):
        return map(func, iterable)

    def map(self, func, iterable, chunksize: int | None = None):
        return list(map(func, iterable))

    def close(self) -> None:
        return None

    def join(self) -> None:
        return None

    def terminate(self) -> None:
        return None


class _InProcessContext:
    def Pool(self, processes: int | None = None, *args: object, **kwargs: object) -> _InProcessPool:
        return _InProcessPool(processes)


def pin_joblib_threading() -> None:
    """Make joblib's default backend threading for this process.

    A bare ``parallel_config(backend="threading")`` does not. It returns
    a context manager; nothing enters it, and ``DEFAULT_BACKEND`` stays
    ``loky``.
    """
    try:
        import joblib.parallel as parallel
    except ImportError:
        return
    parallel.DEFAULT_BACKEND = "threading"
    parallel.DEFAULT_PROCESS_BACKEND = "threading"
    parallel.DEFAULT_THREAD_BACKEND = "threading"


def install_inprocess_ricci() -> None:
    """Route GraphRicci's fork Pool through the calling thread.

    Safe to call more than once. No-op when the library is not installed;
    callers already fall back to the variance curvature in that case.
    """
    global _RICCI_INSTALLED
    if _RICCI_INSTALLED:
        return
    try:
        import GraphRicciCurvature.OllivierRicci as orc
    except ImportError:
        return

    real = orc._compute_ricci_curvature_edges

    def inprocess(*args: object, **kwargs: object):
        import multiprocessing as mp

        with _RICCI_LOCK:
            previous = mp.get_context

            def get_context(method: str | None = None):
                if method == "fork":
                    return _InProcessContext()
                return previous(method)

            mp.get_context = get_context  # type: ignore[method-assign]
            try:
                return real(*args, **kwargs)
            finally:
                mp.get_context = previous

    orc._compute_ricci_curvature_edges = inprocess
    _RICCI_INSTALLED = True
