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
    ONSET_NAMES,
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
    "via devenv Postgres impala_fdw (signal_tier0).\n"
    "  Guru: #COG.00000031.NOWHFDW\n"
    "  Try: kinit; psql -h 127.0.0.1 -p 5455 -d signals "
    "-c 'SELECT count(*) FROM signal_tier0'\n"
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
    cognition_rows: list[dict[str, Any]] | None = None,
) -> WaterfallState:
    if window_s < 1 or window_s > MAX_WINDOW_S:
        raise ValueError(GURU_WINDOW)
    if warehouse_rows is not None:
        return tick_from_gpu_rows(warehouse_rows, window_s, cognition_rows)
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
    rows: list[dict[str, Any]],
    window_s: int,
    cognition_rows: list[dict[str, Any]] | None = None,
) -> WaterfallState:
    """Build a 1 Hz strip from signal_tier0 rows (Kudu via impala_fdw kudu_scan).

    ``rows`` are narrow series samples: ts_ns, series_id, gpu, val_i for the
    two DCGM series the strip paints (power_mw, gpu_util_pct). ``cognition_rows``
    are the same shape with val_d and the series name resolved to a channel.
    Every channel the strip advertises is sourced here — a channel with no rows
    in the window stays at zero honestly, it is not faked.
    """
    from gaius.engine.services.waterfall_color import pack_gpu
    from gaius.engine.services.waterfall_drivers import _IDLE_W, _BUSY_W, _clip
    from gaius.engine.services.warehouse_ingest import series_id_of

    names = all_channel_names()
    n_ch = len(names)
    n_cols = max(1, int(window_s))
    matrix = [[0.0] * n_cols for _ in range(n_ch)]
    # Whether each (channel, column) got a real sample. Used for sample-and-hold
    # below: a column with no sample is filled with the last known value rather
    # than left at 0, so the onset field never sees a phantom drop-to-zero.
    present = [[False] * n_cols for _ in range(n_ch)]
    name_i = {n: i for i, n in enumerate(names)}
    if not rows:
        raise ValueError(
            GURU_WAREHOUSE + "\n  warehouse query returned 0 rows for this window"
        )
    # The rightmost column is a whole second that every channel's fetch already
    # contains. Getting this exactly right was the whole battle:
    #
    #  - A wall-clock anchor (now, or now-1) can name a second a fetch has not
    #    returned yet: the GPU rows and cognition rows come from two separate
    #    queries with their own `now`. That column was then held at the previous
    #    value and corrected a frame later when the real (usually different)
    #    sample appeared — a transient wrong cell at the right edge that vanished
    #    instead of scrolling. Seen on the cognition channels (the later fetch).
    #  - min(newest GPU second, newest cognition second) over-corrects the other
    #    way: while a cognition source is stale (e.g. vLLM restarting) its old
    #    newest drags the whole anchor back, then the view jumps when it catches
    #    up.
    #
    # Anchor the rightmost column to the newest *fully settled* second, so the
    # edge value is final the instant it is painted and only ever scrolls left.
    #
    # "Settled" is the crux. A second's samples do not all land at once: the six
    # GPUs each INSERT their own row and the cognition metrics land in a separate
    # fetch, all with ~0.65 s of ingest lag and a little skew between them. So the
    # newest second that has *any* row (max ts over the GPU rows) is often still
    # filling — one GPU or one cognition channel has not written it yet. Anchor
    # there and that channel's edge cell is carried forward from the prior second,
    # then corrected a frame later when its real sample arrives: a right-edge cell
    # that changes value instead of scrolling — the "disappearing" flicker.
    #
    # Back off one whole second: min(now - 2, newest GPU second - 1). Once *any*
    # row for second S exists, S-1 is complete for every channel — all sources
    # sample at 1 Hz with sub-second lag, so none can still be mid-write on a
    # second a newer one already exists for. Cognition is the later fetch with a
    # newest >= GPU's, so it too has S-1 settled (its metrics land together per
    # tick). Costs ~1 s more edge latency, invisible on a 60 s view; buys a
    # right edge that is correct when it appears and identical as it slides left.
    # Stragglers newer than the anchor map past the edge and are dropped. epoch
    # below is this same second, so the client repaints once per second and
    # shifts left one column a frame.
    _gpu_newest = max(int(r["ts_ns"]) for r in rows) // 1_000_000_000
    anchor_sec = min(int(time.time()) - 2, _gpu_newest - 1)

    def _col_for(ts_ns: int) -> int:
        return n_cols - 1 - (anchor_sec - int(ts_ns) // 1_000_000_000)

    sid_w = series_id_of("dcgm.power_mw")
    sid_u = series_id_of("dcgm.gpu_util_pct")
    # Pair power and util per (gpu, column) so the packed gpu-N cell has both.
    cell: dict[tuple[int, int], list[float | None]] = {}
    for r in rows:
        raw_ts = r.get("ts_ns")
        raw_gi = r.get("gpu")
        if raw_ts is None or raw_gi is None:
            raise ValueError(GURU_WAREHOUSE + "\n  signal_tier0 row missing ts_ns/gpu")
        col = _col_for(raw_ts)
        if col < 0:
            continue
        if col >= n_cols:
            continue  # forming current second — not shown until complete
        gi = int(raw_gi)
        slot = cell.setdefault((gi, col), [None, None])
        sid = int(r["series_id"])
        if sid == sid_w:
            slot[0] = int(r["val_i"]) / 1000.0  # mW → W at the display boundary
        elif sid == sid_u:
            slot[1] = int(r["val_i"]) / 100.0
    for (gi, col), (watts, util) in cell.items():
        gk = f"gpu-{gi}"
        uk = f"util-{gi}"
        if watts is not None and gk in name_i:
            u = _clip(util if util is not None else 0.0)
            p = _clip((watts - _IDLE_W) / (_BUSY_W - _IDLE_W))
            matrix[name_i[gk]][col] = pack_gpu(p, u)
            present[name_i[gk]][col] = True
        if util is not None and uk in name_i:
            matrix[name_i[uk]][col] = _clip(util)
            present[name_i[uk]][col] = True
    envelope = 0.0
    for r in cognition_rows or []:
        ch = r.get("channel")
        if ch is None or ch not in name_i:
            continue  # a channel the strip does not show (probe rows, retired)
        raw_ts = r.get("ts_ns")
        if raw_ts is None or r.get("val_d") is None:
            continue
        col = _col_for(raw_ts)
        if col < 0:
            continue
        if col >= n_cols:
            continue  # forming current second — not shown until complete
        val = float(r["val_d"])
        matrix[name_i[ch]][col] = val
        present[name_i[ch]][col] = True
        if ch in ONSET_NAMES:
            envelope = max(envelope, abs(val))
    # Sample-and-hold across absent columns, for every channel. A second with
    # no sample is "same as last known", not a drop to zero: without this the
    # client's onset field sees a phantom drop-to-zero wherever a column is
    # empty — most often the current second, before its ~1 Hz sample lands —
    # and paints a false blue/red flash at the right edge that vanishes when
    # the sample arrives, instead of a real onset that scrolls across. Uses the
    # presence bitmap, not value==0, so a genuine zero reading is preserved and
    # a channel that never had data (e.g. a silent cognition source) stays 0.
    # Bridge only short gaps (the current second, an occasional dropped
    # sample). A channel silent longer than this goes dark honestly rather
    # than freezing a stale value across the whole view.
    max_hold = 3
    for ri in range(n_ch):
        row = matrix[ri]
        pres = present[ri]
        last: float | None = None
        held = 0
        for c in range(n_cols):
            if pres[c]:
                last = row[c]
                held = 0
            elif last is not None and held < max_hold:
                row[c] = last
                held += 1

    try:
        from gaius.engine.metrics import EngineMetrics

        EngineMetrics.get_instance().set_cognition_tremor(envelope)
    except Exception:
        pass
    return WaterfallState(
        window_s=window_s,
        # The wall-clock second the columns are anchored to (the last complete
        # second). Advances by 1 each wall second, so the client repaints once
        # per second and every frame scrolls left by exactly one column.
        epoch_unix_ms=anchor_sec * 1000,
        channel_names=tuple(names),
        matrix=matrix,
        driver="warehouse",
        hz=1,
        salience=envelope,
    )


# The strip reads signal_tier0 (Kudu, kudu_scan): its window is at most
# LIVE_WINDOW_S of wall clock, always inside the hot day, so the hierarchy view
# would add an HS2 round trip for rows that can only live in Kudu. The broad
# Kumo window is the one that spans tiers and it reads the `signal` view.
#
# One warehouse connection, reused. Opening a Postgres backend costs an
# impala_fdw session — Kerberos, Kudu client, table metadata — measured at
# 2.8-15.7s; warm, the same reads are ~10ms.
_CONN: Any = None
_CONN_LOCK: Any = None


def _conn_lock() -> Any:
    global _CONN_LOCK
    if _CONN_LOCK is None:
        import asyncio as _asyncio

        _CONN_LOCK = _asyncio.Lock()
    return _CONN_LOCK


async def _warehouse_conn() -> Any:
    """Live warehouse connection, reconnecting if the last one died."""
    global _CONN
    try:
        import asyncpg
    except ImportError as e:
        raise RuntimeError(GURU_WAREHOUSE) from e
    if _CONN is not None and not _CONN.is_closed():
        return _CONN
    try:
        _CONN = await asyncpg.connect(_warehouse_dsn(), timeout=60)
    except Exception as e:
        _CONN = None
        raise RuntimeError(f"{GURU_WAREHOUSE}\n  connect: {e}") from e
    return _CONN


async def _drop_warehouse_conn() -> None:
    """Discard the cached connection so the next read reconnects."""
    global _CONN
    conn, _CONN = _CONN, None
    if conn is not None and not conn.is_closed():
        try:
            await conn.close()
        except Exception:
            pass


def reset_warehouse_conn_for_tests() -> None:
    global _CONN
    _CONN = None


def _warehouse_dsn() -> str:
    import os

    return os.environ.get(
        "SIGNALS_WAREHOUSE_DSN",
        "postgresql://signals@127.0.0.1:5455/signals",
    )


async def fetch_cognition_metrics(window_s: int) -> list[dict[str, Any]]:
    """Cognition channels from signal_tier0 (series cog.<channel>, DECIMAL).

    Same transport as the GPU strip. Returns [] when the window has no
    cognition rows — a quiet cognition surface is not a warehouse fault, and
    the GPU strip must still render.
    """
    from gaius.engine.services.warehouse_ingest import series_id_of
    from gaius.engine.services.waterfall_drivers import cognition_channel_names

    names = cognition_channel_names()
    if not names:
        return []
    by_sid = {series_id_of(f"cog.{n}"): n for n in names}
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - int(window_s) * 1_000_000_000
    hour = end_ns // 1_000_000_000 // 3600
    async with _conn_lock():
        conn = await _warehouse_conn()
        try:
            recs = await conn.fetch(
                """
                SELECT ts_ns, series_id, val_d
                  FROM signal_tier0
                 WHERE epoch_hour >= $1 AND ts_ns >= $2 AND ts_ns < $3
                   AND series_id = ANY($4::bigint[])
                """,
                hour - 1, start_ns, end_ns, list(by_sid),
            )
        except Exception as e:
            await _drop_warehouse_conn()
            raise RuntimeError(f"{GURU_WAREHOUSE}\n  cognition query: {e}") from e
    return [
        {"ts_ns": int(r["ts_ns"]), "channel": by_sid[int(r["series_id"])], "val_d": r["val_d"]}
        for r in recs
    ]


async def fetch_gpu_metrics(window_s: int) -> list[dict[str, Any]]:
    """Power/util series from signal_tier0 through impala_fdw kudu_scan. Fail-fast."""
    from gaius.engine.services.warehouse_ingest import series_id_of

    sids = [series_id_of("dcgm.power_mw"), series_id_of("dcgm.gpu_util_pct")]
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - int(window_s) * 1_000_000_000
    hour = end_ns // 1_000_000_000 // 3600
    async with _conn_lock():
        conn = await _warehouse_conn()
        try:
            recs = await conn.fetch(
                """
                SELECT ts_ns, gpu, series_id, val_i
                  FROM signal_tier0
                 WHERE epoch_hour >= $1 AND ts_ns >= $2 AND ts_ns < $3
                   AND series_id = ANY($4::bigint[])
                 ORDER BY ts_ns, gpu
                """,
                hour - 1, start_ns, end_ns, sids,
            )
        except Exception as e:
            await _drop_warehouse_conn()
            raise RuntimeError(f"{GURU_WAREHOUSE}\n  query: {e}") from e
    out = [dict(r) for r in recs]
    for r in out:
        if r.get("ts_ns") is None or r.get("gpu") is None:
            raise RuntimeError(f"{GURU_WAREHOUSE}\n  NULL ts_ns/gpu from signal_tier0")
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
