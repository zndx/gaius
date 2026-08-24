"""10 Hz cognition strip from registered real-measure drivers.

Crossing the view is 60 s = one 1 hr Kumo minute-tick. Channels are named
sources (DCGM, vLLM, CLT tape, Ricci). Absent sources flatline at 0.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from gaius.engine.services.waterfall_drivers import (
    all_channel_names,
    onset_envelope,
    reset_for_tests as reset_drivers_for_tests,
    sample_column,
)

HZ = 10
DEFAULT_WINDOW_S = 60
LIVE_WINDOW_S = 60
MAX_WINDOW_S = 3600
CHANNEL_NAMES: tuple[str, ...] = all_channel_names()
N_CHANNELS = len(CHANNEL_NAMES)

GURU_WINDOW = (
    "Cognition waterfall window_s must be in 1..3600.\n"
    "  Guru: #COG.00000030.BADWFWIN"
)
GURU_WAREHOUSE = (
    "Cognition waterfall window_s > 60 requires Signals warehouse "
    "via devenv Postgres impala_fdw (gpu_metrics).\n"
    "  Guru: #COG.00000031.NOWHFDW\n"
    "  Try: kinit; psql -h 127.0.0.1 -p 5455 -d signals "
    "-c 'SELECT count(*) FROM gpu_metrics'\n"
    "  Engine writes that table (impala_fdw INSERT). Guru: #EN.00000031.FDWINGEST\n"
    "  Or:  /health fix engine"
)


@dataclass
class WaterfallState:
    window_s: int
    epoch_unix_ms: int
    channel_names: tuple[str, ...]
    matrix: list[list[float]]
    driver: str
    hn_tokens: int = 0
    fmp_tokens: int = 0
    hz: int = HZ
    salience: float = 0.0

    def column_newest(self) -> list[float]:
        return [row[-1] for row in self.matrix]


_LOCK = threading.Lock()
_RING: list[list[float]] = []
_LAST_MS = 0
_CTX: dict[str, Any] = {}
_LIVE_NAMES: tuple[str, ...] = CHANNEL_NAMES
_LIVE_ENV = 0.0


def reset_for_tests() -> None:
    global _RING, _LAST_MS, _CTX, _LIVE_NAMES, _LIVE_ENV
    reset_drivers_for_tests()
    with _LOCK:
        _RING = []
        _LAST_MS = 0
        _CTX = {}
        _LIVE_NAMES = CHANNEL_NAMES
        _LIVE_ENV = 0.0


def _column(ctx: dict[str, Any]) -> tuple[list[float], tuple[str, ...], float]:
    names = all_channel_names()
    samples = sample_column(ctx)
    by = {s.name: s.value if s.present else 0.0 for s in samples}
    col = [float(by.get(n, 0.0)) for n in names]
    return col, names, onset_envelope(samples)


def _append_locked(
    col: list[float], names: tuple[str, ...], now_ms: int, n_cols: int, hz: int
) -> None:
    global _RING, _LAST_MS, _LIVE_NAMES
    n_ch = len(names)
    step_ms = max(1, 1000 // max(1, hz))
    if not _RING or len(_RING[0]) != n_cols or len(_RING) != n_ch:
        _RING = [[0.0] * n_cols for _ in range(n_ch)]
        for i, v in enumerate(col):
            _RING[i][-1] = v
        _LAST_MS = now_ms
        _LIVE_NAMES = names
        return
    if now_ms - _LAST_MS < step_ms:
        for i, v in enumerate(col):
            if i < len(_RING):
                _RING[i][-1] = v
        _LIVE_NAMES = names
        return
    n_new = max(1, min(hz, (now_ms - _LAST_MS) // step_ms))
    for _ in range(n_new):
        for i, v in enumerate(col):
            _RING[i].pop(0)
            _RING[i].append(v)
    _LAST_MS = now_ms
    _LIVE_NAMES = names


def ingest_fast_column() -> None:
    """Poller hook: advance the shared 10 Hz ring without a gRPC client."""
    from gaius.engine.services import waterfall_drivers as wd

    if wd._TESTING:
        return
    now_ms = int(time.time() * 1000)
    col, names, envelope = _column({})
    global _LIVE_ENV
    _LIVE_ENV = envelope
    try:
        from gaius.engine.metrics import EngineMetrics

        EngineMetrics.get_instance().set_cognition_tremor(envelope)
    except Exception:
        pass
    with _LOCK:
        _append_locked(col, names, now_ms, DEFAULT_WINDOW_S * HZ, HZ)


def start_strip() -> None:
    """Boot the poller so the ring fills even with no Discover clients."""
    from gaius.engine.services.waterfall_drivers import ensure_poller

    ensure_poller()


def tick(
    window_s: int = DEFAULT_WINDOW_S,
    services: Any | None = None,
    *,
    hz: int = HZ,
    salience: float = 0.0,
    ctx: dict[str, Any] | None = None,
    warehouse_rows: list[dict[str, Any]] | None = None,
) -> WaterfallState:
    if window_s < 1 or window_s > MAX_WINDOW_S:
        raise ValueError(GURU_WINDOW)
    if warehouse_rows is not None:
        return tick_from_gpu_rows(warehouse_rows, window_s)
    if window_s > LIVE_WINDOW_S:
        raise ValueError(GURU_WAREHOUSE)
    hz = max(1, min(50, int(hz)))
    n_cols = window_s * hz
    now_ms = int(time.time() * 1000)
    sample_ctx = dict(ctx or {})
    sample_ctx.setdefault("tape_n", 0)
    sample_ctx.setdefault("tape_peak", 0.0)
    from gaius.engine.services.waterfall_drivers import ensure_poller
    from gaius.engine.services import waterfall_drivers as wd

    global _RING, _LAST_MS, _CTX, _LIVE_NAMES

    if wd._TESTING:
        col, names, envelope = _column(sample_ctx)
        try:
            from gaius.engine.metrics import EngineMetrics

            EngineMetrics.get_instance().set_cognition_tremor(envelope)
        except Exception:
            pass
        with _LOCK:
            _append_locked(col, names, now_ms, n_cols, hz)
            matrix = [list(r) for r in _RING]
            epoch = _LAST_MS or now_ms
            env = envelope
            live_names = names
    else:
        ensure_poller()
        with _LOCK:
            _CTX = sample_ctx
        from gaius.engine.services.waterfall_drivers import sample_column as _sc

        _sc(sample_ctx)
        with _LOCK:
            names = _LIVE_NAMES or all_channel_names()
            n_ch = len(names)
            live_cols = DEFAULT_WINDOW_S * HZ
            if not _RING or len(_RING) != n_ch or len(_RING[0]) != live_cols:
                _RING = [[0.0] * live_cols for _ in range(n_ch)]
            take = min(n_cols, len(_RING[0]) if _RING else 0)
            matrix = [list(r[-take:]) for r in _RING] if take else []
            epoch = _LAST_MS or now_ms
            env = _LIVE_ENV
            live_names = names
    return WaterfallState(
        window_s=window_s,
        epoch_unix_ms=epoch,
        channel_names=live_names,
        matrix=matrix,
        driver="measures",
        hz=hz,
        salience=env,
    )


def tick_from_gpu_rows(
    rows: list[dict[str, Any]], window_s: int
) -> WaterfallState:
    """Build a 1 Hz strip from warehouse GPU rows (Kudu ∪ Iceberg via FDW)."""
    from gaius.engine.services.waterfall_color import pack_gpu
    from gaius.engine.services.waterfall_drivers import _IDLE_W, _BUSY_W, _clip

    names = all_channel_names()
    n_ch = len(names)
    n_cols = max(1, int(window_s))
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - n_cols * 1000
    matrix = [[0.0] * n_cols for _ in range(n_ch)]
    name_i = {n: i for i, n in enumerate(names)}
    if not rows:
        raise ValueError(
            GURU_WAREHOUSE + "\n  warehouse query returned 0 rows for this window"
        )
    for r in rows:
        raw_ts = r.get("ts_ns")
        raw_gi = r.get("gpu_index")
        if raw_ts is None or raw_gi is None:
            raise ValueError(
                GURU_WAREHOUSE
                + "\n  gpu_metrics row missing ts_ns/gpu_index "
                "(NULL — do not use the Postgres kudu_scan∪Iceberg VIEW)"
            )
        ts_ns = int(raw_ts)
        col = int((ts_ns // 1_000_000 - start_ms) // 1000)
        if col < 0:
            continue
        if col >= n_cols:
            col = n_cols - 1
        gi = int(r["gpu_index"])
        watts = float(r["power_w"] or 0.0)
        util = float(r["util_pct"] or 0.0) / 100.0
        p = _clip((watts - _IDLE_W) / (_BUSY_W - _IDLE_W))
        packed = pack_gpu(p, util)
        gk = f"gpu-{gi}"
        uk = f"util-{gi}"
        if gk in name_i:
            matrix[name_i[gk]][col] = packed
        if uk in name_i:
            matrix[name_i[uk]][col] = _clip(util)
    last_ts = max(int(r["ts_ns"]) for r in rows)
    return WaterfallState(
        window_s=window_s,
        epoch_unix_ms=last_ts // 1_000_000,
        channel_names=tuple(names),
        matrix=matrix,
        driver="warehouse",
        hz=1,
    )


async def fetch_gpu_metrics(window_s: int) -> list[dict[str, Any]]:
    """SELECT gpu_metrics through devenv Postgres impala_fdw. Fail-fast."""
    import os

    dsn = os.environ.get(
        "SIGNALS_WAREHOUSE_DSN",
        "postgresql://signals@127.0.0.1:5455/signals",
    )
    try:
        import asyncpg
    except ImportError as e:
        raise RuntimeError(GURU_WAREHOUSE) from e
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - int(window_s) * 1_000_000_000
    try:
        conn = await asyncpg.connect(dsn, timeout=60)
    except Exception as e:
        raise RuntimeError(f"{GURU_WAREHOUSE}\n  connect: {e}") from e
    try:
        recs = await conn.fetch(
            """
            SELECT ts_ns, gpu_index, power_w, util_pct
              FROM gpu_metrics
             WHERE ts_ns >= $1 AND ts_ns < $2
             ORDER BY ts_ns, gpu_index
            """,
            start_ns,
            end_ns,
        )
    except Exception as e:
        raise RuntimeError(f"{GURU_WAREHOUSE}\n  query: {e}") from e
    finally:
        await conn.close()
    out = [dict(r) for r in recs]
    for r in out:
        if r.get("ts_ns") is None or r.get("gpu_index") is None:
            raise RuntimeError(
                f"{GURU_WAREHOUSE}\n  NULL ts_ns/gpu_index from gpu_metrics"
            )
    return out


async def recent_tape_energy(pool: Any) -> tuple[int, float]:
    if pool is None:
        return 0, 0.0
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*)::int AS n,
                   coalesce(max(abs(activation)), 0)::float AS peak
              FROM feature_tape
             WHERE ts > NOW() - interval '8 seconds'
            """
        )
    if not row:
        return 0, 0.0
    return int(row["n"] or 0), float(row["peak"] or 0.0)


def holoviews_image(state: WaterfallState, *, mode: str = "dark") -> Any:
    """RGB raster — bivariate gpu-n + theme-safe signed rows (no RdBu white)."""
    import numpy as np

    import holoviews as hv

    from gaius.engine.services.waterfall_color import rgb_raster

    hv.extension("bokeh", logo=False)
    cells = rgb_raster(state.matrix, state.channel_names)
    rgb = np.asarray(cells, dtype=np.uint8)
    n_t = rgb.shape[1]
    xs = np.arange(-(n_t - 1), 1) / max(1, state.hz)
    ys = np.arange(rgb.shape[0])
    r = rgb[:, :, 0] / 255.0
    g = rgb[:, :, 1] / 255.0
    b = rgb[:, :, 2] / 255.0
    bg = "#090b0e" if mode != "light" else "#eef1f4"
    return hv.RGB(
        (xs, ys, r, g, b),
        kdims=["epoch_s", "channel"],
        vdims=["R", "G", "B"],
    ).opts(
        invert_yaxis=True,
        toolbar=None,
        width=920,
        height=200,
        yticks=[(i, n) for i, n in enumerate(state.channel_names)],
        xlabel="",
        ylabel="",
        title="",
        bgcolor=bg,
    )


def holoviews_bokeh_item(
    state: WaterfallState, element_id: str = "discover-waterfall-plot"
) -> str:
    from bokeh.embed import json_item
    import json
    import holoviews as hv

    hv.extension("bokeh", logo=False)
    renderer = hv.renderer("bokeh")
    plot = renderer.get_plot(holoviews_image(state))
    return json.dumps(json_item(plot.state, element_id))
