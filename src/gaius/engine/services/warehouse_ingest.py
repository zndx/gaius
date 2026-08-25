"""Engine warehouse: DCGM + vLLM + cognition → Postgres impala_fdw INSERT → Kudu.

The engine is the writer. One narrow table, ``signal_tier0``, carries every
scalar sample; ``signal_series`` declares each series' storage type and unit
and the parser routes on it. Typing rule (docs/scratch/2026-08-25/214236):

    INT in → INT out at native precision.   16 of 17 DCGM families are integers
                                            (power is NVML milliwatts → INT32).
    float in → DECIMAL(18,6).                vLLM ratios, latency histograms,
                                            cognition channels.
    No float(val) widening anywhere.

Reads: the strip reads ``signal_tier0`` (hot, kudu_scan); the broad Kumo
window reads the ``signal`` UNION view (Kudu ∪ Iceberg+HDF5) through one
plan with predicates pushed to both stores.
Guru: #EN.00000031.FDWINGEST
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

GURU = (
    "Engine warehouse ingest via Postgres impala_fdw failed.\n"
    "  Guru: #EN.00000031.FDWINGEST\n"
    "  Try: psql -h 127.0.0.1 -p 5444 -d zndx_gaius "
    "-c 'INSERT INTO signal_tier0 ...'\n"
    "  Or:  /health fix engine"
)

INTERVAL_S = float(os.environ.get("GAIUS_WAREHOUSE_INGEST_S", "1"))
DCGM_METRICS_URL = os.environ.get("GAIUS_DCGM_METRICS_URL", "http://127.0.0.1:9400/metrics")

VT_INT = 0
VT_DEC = 1
SRC_DCGM, SRC_VLLM, SRC_ENGINE, SRC_HOST = 0, 1, 2, 3
DEC_Q = Decimal("0.000001")  # DECIMAL(18,6)
HOURS_PER_DAY = 24


@dataclass(frozen=True)
class Series:
    name: str
    vtype: int
    unit: str
    src: int
    dcgm_field: str | None = None
    description: str = ""

    @property
    def series_id(self) -> int:
        return series_id_of(self.name)


def series_id_of(name: str) -> int:
    """Stable 63-bit id from the canonical series name (no registry round-trip)."""
    h = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "big") & 0x7FFF_FFFF_FFFF_FFFF


# 17 DCGM families. Native types per exporter: integer except POWER_USAGE
# (double watts), which NVML sources as integer milliwatts — stored as mW.
DCGM_SERIES: tuple[Series, ...] = (
    Series("dcgm.sm_clock_mhz", VT_INT, "MHz", SRC_DCGM, "DCGM_FI_DEV_SM_CLOCK"),
    Series("dcgm.mem_clock_mhz", VT_INT, "MHz", SRC_DCGM, "DCGM_FI_DEV_MEM_CLOCK"),
    Series("dcgm.mem_temp_c", VT_INT, "C", SRC_DCGM, "DCGM_FI_DEV_MEMORY_TEMP"),
    Series("dcgm.gpu_temp_c", VT_INT, "C", SRC_DCGM, "DCGM_FI_DEV_GPU_TEMP"),
    Series("dcgm.power_mw", VT_INT, "mW", SRC_DCGM, "DCGM_FI_DEV_POWER_USAGE"),
    Series("dcgm.energy_mj", VT_INT, "mJ", SRC_DCGM, "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION"),
    Series("dcgm.gpu_util_pct", VT_INT, "percent", SRC_DCGM, "DCGM_FI_DEV_GPU_UTIL"),
    Series("dcgm.mem_copy_util_pct", VT_INT, "percent", SRC_DCGM, "DCGM_FI_DEV_MEM_COPY_UTIL"),
    Series("dcgm.enc_util_pct", VT_INT, "percent", SRC_DCGM, "DCGM_FI_DEV_ENC_UTIL"),
    Series("dcgm.dec_util_pct", VT_INT, "percent", SRC_DCGM, "DCGM_FI_DEV_DEC_UTIL"),
    Series("dcgm.xid_errors", VT_INT, "count", SRC_DCGM, "DCGM_FI_DEV_XID_ERRORS"),
    Series("dcgm.fb_free_mib", VT_INT, "MiB", SRC_DCGM, "DCGM_FI_DEV_FB_FREE"),
    Series("dcgm.fb_used_mib", VT_INT, "MiB", SRC_DCGM, "DCGM_FI_DEV_FB_USED"),
    Series("dcgm.remapped_rows_uncorr", VT_INT, "count", SRC_DCGM, "DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS"),
    Series("dcgm.remapped_rows_corr", VT_INT, "count", SRC_DCGM, "DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS"),
    Series("dcgm.row_remap_failure", VT_INT, "flag", SRC_DCGM, "DCGM_FI_DEV_ROW_REMAP_FAILURE"),
    Series("dcgm.nvlink_bw_total", VT_INT, "count", SRC_DCGM, "DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL"),
)
_DCGM_BY_FIELD = {s.dcgm_field: s for s in DCGM_SERIES}
# The strip cannot render without these four per GPU — a GPU missing one is a
# fail-fast. Other families are recorded when the exporter offers them.
_DCGM_CORE = ("dcgm.power_mw", "dcgm.gpu_util_pct", "dcgm.fb_used_mib", "dcgm.gpu_temp_c")

# Cognition channels (waterfall_drivers): every non-hardware driver channel.
# They are transients/ratios → DECIMAL. Registered lazily from the driver
# registry so a new channel needs no warehouse DDL.
COGNITION_UNIT = "ratio"

_TASK: asyncio.Task[None] | None = None
_SERIES_SEEDED = False


def warehouse_dsn() -> str:
    """Gaius Postgres with impala_fdw. Signals :5455 remains a fallback."""
    if os.environ.get("GAIUS_WAREHOUSE_DSN"):
        return os.environ["GAIUS_WAREHOUSE_DSN"]
    if os.environ.get("GAIUS_WAREHOUSE_USE_SIGNALS", "").lower() in ("1", "true", "yes"):
        return os.environ.get(
            "SIGNALS_WAREHOUSE_DSN", "postgresql://signals@127.0.0.1:5455/signals"
        )
    port = os.environ.get("PGPORT", "5444")
    return f"postgresql://gaius:gaius@127.0.0.1:{port}/zndx_gaius"


def cognition_series() -> list[Series]:
    from gaius.engine.services.waterfall_drivers import cognition_channel_names

    return [
        Series(f"cog.{n}", VT_DEC, COGNITION_UNIT, SRC_ENGINE, None, f"waterfall channel {n}")
        for n in cognition_channel_names()
    ]


def all_series() -> list[Series]:
    return list(DCGM_SERIES) + cognition_series()


# ---- parsing (no widening) ---------------------------------------------------

def _as_int(text: str, field: str) -> int:
    """Prometheus text renders integers as '3' or '3.0'; both are integers."""
    try:
        d = Decimal(text)
    except InvalidOperation as e:
        raise RuntimeError(f"{GURU}\n  {field}: unparseable {text!r}") from e
    if d != d.to_integral_value():
        raise RuntimeError(
            f"{GURU}\n  {field}: declared INT but exporter sent {text!r}; "
            "fix the series declaration, do not round"
        )
    return int(d)


def _as_dec(text: str, field: str) -> Decimal:
    try:
        d = Decimal(text)
    except InvalidOperation as e:
        raise RuntimeError(f"{GURU}\n  {field}: unparseable {text!r}") from e
    if not d.is_finite():
        raise RuntimeError(
            f"{GURU}\n  {field}: {text!r} has no DECIMAL representation; "
            "map unavailable to NULL at the source"
        )
    return d.quantize(DEC_Q)


def sample_gpus() -> dict[int, dict[str, int]]:
    """Live DCGM rows: {gpu_index: {series_name: int}}. Fail-fast on gaps in core."""
    from gaius.engine.services.waterfall_drivers import (
        _gpu_index,
        _http_get,
        parse_prom_text_raw,
    )

    text = _http_get(DCGM_METRICS_URL, timeout=1.0)
    if not text:
        raise RuntimeError(f"{GURU}\n  DCGM {DCGM_METRICS_URL} unreachable")
    by: dict[int, dict[str, int]] = {}
    for metric, labels, raw in parse_prom_text_raw(text):
        s = _DCGM_BY_FIELD.get(metric)
        if s is None:
            continue
        i = _gpu_index(labels)
        if i is None:
            continue
        if s.name == "dcgm.power_mw":
            # Exporter renders watts as a double; NVML measured milliwatts.
            w = _as_dec(raw, metric)
            by.setdefault(i, {})[s.name] = int((w * 1000).to_integral_value())
        else:
            by.setdefault(i, {})[s.name] = _as_int(raw, metric)
    for i, rec in by.items():
        missing = [k for k in _DCGM_CORE if k not in rec]
        if missing:
            raise RuntimeError(f"{GURU}\n  DCGM gpu={i} missing {', '.join(missing)}")
    if not by:
        raise RuntimeError(f"{GURU}\n  DCGM returned no GPUs")
    return by


# ---- rows --------------------------------------------------------------------

def dcgm_rows(now: float, gpus: dict[int, dict[str, int]]) -> list[tuple[Any, ...]]:
    ts_ns = int(now * 1_000_000_000)
    eh = int(now) // 3600
    out: list[tuple[Any, ...]] = []
    for gi in sorted(gpus):
        for name, v in gpus[gi].items():
            out.append((eh, ts_ns, series_id_of(name), SRC_DCGM, gi, None, v, None))
    return out


def cognition_rows(now: float, samples: list[Any]) -> list[tuple[Any, ...]]:
    """A gap (present=False) is a missing row, never a zero."""
    ts_ns = int(now * 1_000_000_000)
    eh = int(now) // 3600
    out: list[tuple[Any, ...]] = []
    for s in samples:
        if not s.present:
            continue
        d = Decimal(repr(float(s.value))).quantize(DEC_Q)
        out.append((eh, ts_ns, series_id_of(f"cog.{s.name}"), SRC_ENGINE, None, None, None, d))
    return out


async def insert_signal_rows(conn: Any, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO signal_tier0 (
            epoch_hour, ts_ns, series_id, src, gpu, inst, val_i, val_d
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        rows,
    )


async def seed_series(conn: Any) -> int:
    """Upsert the series registry. Idempotent; runs once per engine boot."""
    global _SERIES_SEEDED
    if _SERIES_SEEDED:
        return 0
    have = {int(r["series_id"]) for r in await conn.fetch("SELECT series_id FROM signal_series")}
    todo = [s for s in all_series() if s.series_id not in have]
    if todo:
        await conn.executemany(
            """
            INSERT INTO signal_series (series_id, name, vtype, unit, src, dcgm_field, description)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [(s.series_id, s.name, s.vtype, s.unit, s.src, s.dcgm_field, s.description) for s in todo],
        )
    _SERIES_SEEDED = True
    return len(todo)


# Kudu keeps day-wide ranges on the hourly epoch_hour column (bounds need not
# be unit width). The C++ creator provisions [today-1, today+2) at create; the
# writer keeps that lead as days roll. ALTER through HS2 is the path that has
# run for days without incident — only CREATE ... STORED AS KUDU crashed.
_TIER0_TABLES = ("signal_tier0",)


def day_floor(hour: int) -> int:
    return (hour // HOURS_PER_DAY) * HOURS_PER_DAY


async def ensure_day_partitions(conn: Any, hour: int) -> dict[str, str]:
    """ADD RANGE PARTITION for [today, today+2 days) on every tier0 table."""
    out: dict[str, str] = {}
    day0 = day_floor(hour)
    for tbl in _TIER0_TABLES:
        errs: list[str] = []
        for d in (day0, day0 + HOURS_PER_DAY):
            add = (
                f"ALTER TABLE signals_dataproducts.{tbl} "
                f"ADD IF NOT EXISTS RANGE PARTITION {d} <= VALUES < {d + HOURS_PER_DAY}"
            )
            try:
                await conn.fetchval("SELECT impala_fdw_exec($1, $2)", "impala_kudu_srv", add)
            except Exception as e:
                msg = " ".join(str(e).split())
                if "already" not in msg.lower() and "overlap" not in msg.lower():
                    errs.append(msg[:160])
        try:
            shown = await conn.fetchval(
                "SELECT impala_fdw_exec($1, $2)", "impala_kudu_srv",
                f"SHOW RANGE PARTITIONS signals_dataproducts.{tbl}",
            )
        except Exception as e:
            out[tbl] = "; ".join(errs) or " ".join(str(e).split())[:160]
            continue
        out[tbl] = "present" if f"{day0} <= VALUES" in (shown or "") else (
            "; ".join(errs) or "day range absent after ADD"
        )
    return out


# ---- reads -------------------------------------------------------------------

def _bucket_ts(ts_ns: int, interval: str) -> datetime:
    sec = ts_ns / 1_000_000_000.0
    if interval == "day":
        sec -= sec % 86400
    elif interval == "hour":
        sec -= sec % 3600
    else:
        sec -= sec % 60
    return datetime.fromtimestamp(sec, tz=timezone.utc)


async def fetch_gpu_hist_buckets(
    start: datetime, end: datetime, interval: str
) -> list[dict[str, Any]]:
    """Kumo: watts/util per bucket from the ``signal`` hierarchy (Kudu ∪ Iceberg).

    One query against the transparent surface. ``ts_ns`` and ``series_id``
    predicates push through impala_fdw → Impala → both stores: Kudu evaluates
    them natively, and for Iceberg the planner prunes files on manifest bounds
    and the HDF5 reader materialises only the matching hyperslab.
    """
    import asyncpg
    from collections import defaultdict

    if interval not in ("minute", "hour", "day"):
        raise RuntimeError(f"{GURU}\n  bad hist interval {interval!r}")
    start_ns = int(start.astimezone(timezone.utc).timestamp() * 1_000_000_000)
    end_ns = int(end.astimezone(timezone.utc).timestamp() * 1_000_000_000)
    start_h = int(start.astimezone(timezone.utc).timestamp()) // 3600
    end_h = int(end.astimezone(timezone.utc).timestamp()) // 3600
    sid_w = series_id_of("dcgm.power_mw")
    sid_u = series_id_of("dcgm.gpu_util_pct")
    conn = await asyncpg.connect(warehouse_dsn(), timeout=60)
    try:
        recs = await conn.fetch(
            """
            SELECT ts_ns, gpu, series_id, val_i
              FROM signal
             WHERE epoch_hour >= $1 AND epoch_hour <= $2
               AND ts_ns >= $3 AND ts_ns < $4
               AND series_id IN ($5, $6)
            """,
            start_h, end_h, start_ns, end_ns, sid_w, sid_u,
        )
    finally:
        await conn.close()
    per: dict[tuple[datetime, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in recs:
        m = _bucket_ts(int(r["ts_ns"]), interval)
        gi = int(r["gpu"]) if r["gpu"] is not None else -1
        rec = per[(m, gi)]
        if int(r["series_id"]) == sid_w:
            rec[0] += int(r["val_i"]) / 1000.0  # mW → W at the display boundary
            rec[2] += 1.0
        else:
            rec[1] += int(r["val_i"])
            rec[3] += 1.0
    by_m: dict[datetime, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for (m, _gi), rec in per.items():
        slot = by_m[m]
        slot[0] += rec[0] / (rec[2] or 1.0)
        slot[1] += rec[1] / (rec[3] or 1.0)
        slot[2] += 1.0
    return [
        {"m": m, "watts": float(v[0]), "util": float(v[1] / v[2]) if v[2] else 0.0}
        for m, v in sorted(by_m.items())
    ]


# ---- loop --------------------------------------------------------------------

async def _loop() -> None:
    import asyncpg

    # The cognition drivers only run under the poller; the warehouse writer is
    # their consumer, so the ingest owns starting it.
    try:
        from gaius.engine.services.waterfall_drivers import ensure_poller

        ensure_poller()
    except Exception:
        logger.warning("waterfall poller not started; cognition will be empty")

    dsn = warehouse_dsn()
    conn = None
    inserted = 0
    ticks = 0
    last_hour = -1
    while True:
        t0 = time.monotonic()
        try:
            gpus = sample_gpus()
            now = time.time()
            if conn is None or conn.is_closed():
                conn = await asyncpg.connect(dsn, timeout=8)
                n = await seed_series(conn)
                if n:
                    logger.info("warehouse series registry seeded +%s", n)
            hour = int(now) // 3600
            if hour != last_hour:
                status = await ensure_day_partitions(conn, hour)
                logger.info("warehouse partitions hour=%s day=%s %s", hour, day_floor(hour), status)
                last_hour = hour
            rows = dcgm_rows(now, gpus)
            from gaius.engine.services.waterfall_drivers import cognition_samples

            cog = cognition_rows(now, cognition_samples())
            await insert_signal_rows(conn, rows + cog)
            inserted += len(rows) + len(cog)
            ticks += 1
            if ticks == 1 or ticks % 30 == 0:
                logger.info(
                    "warehouse ingest ticks=%s inserted=%s gpus=%s dcgm_rows=%s cognition=%s "
                    "power_w=%s",
                    ticks, inserted, len(gpus), len(rows), len(cog),
                    [round(gpus[g]["dcgm.power_mw"] / 1000.0, 1) for g in sorted(gpus)],
                )
        except asyncio.CancelledError:
            if conn is not None and not conn.is_closed():
                await conn.close()
            raise
        except Exception:
            logger.error("%s", GURU, exc_info=True)
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
                conn = None
            await asyncio.sleep(max(2.0, INTERVAL_S))
            continue
        dt = time.monotonic() - t0
        await asyncio.sleep(max(0.05, INTERVAL_S - dt))


def start_warehouse_ingest() -> None:
    """Boot with the engine. Fail-fast log if the event loop cannot spawn."""
    global _TASK
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("%s\n  no running event loop", GURU)
        return
    if _TASK is not None and not _TASK.done():
        return
    _TASK = loop.create_task(_loop(), name="warehouse-ingest")
    logger.info("warehouse ingest started dsn=%s interval=%ss", warehouse_dsn(), INTERVAL_S)
