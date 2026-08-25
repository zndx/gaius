"""Engine warehouse: DCGM → Postgres impala_fdw INSERT → Kudu.

The Gaius engine is the writer. Local zndx_gaius `gpu_metrics_tier0`
(impala_fdw → system Kudu) is the insert path. `gpu_metrics` is the HS2
UNION of hot Kudu ∪ cold Iceberg and is not writable (N3). Signals
:5455 FDW stays; set GAIUS_WAREHOUSE_USE_SIGNALS=1 to use it.
Guru: #EN.00000031.FDWINGEST
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

GURU = (
    "Engine warehouse ingest via Postgres impala_fdw failed.\n"
    "  Guru: #EN.00000031.FDWINGEST\n"
    "  Try: psql -h 127.0.0.1 -p 5444 -d zndx_gaius "
    "-c 'INSERT INTO gpu_metrics_tier0 ...'\n"
    "  Or:  /health fix engine"
)

INTERVAL_S = float(os.environ.get("GAIUS_WAREHOUSE_INGEST_S", "1"))
DCGM_METRICS_URL = os.environ.get("GAIUS_DCGM_METRICS_URL", "http://127.0.0.1:9400/metrics")

# Extended DCGM fields land narrow in gpu_dcgm (field, value) rather than as
# columns on gpu_metrics: that table is created by the C++ gpu_kudu_create
# client, so Impala resolves it read-only and ADD COLUMNS raises
# TableNotFoundException. A further field here costs no warehouse DDL.
_DCGM_EXTRA = {
    "DCGM_FI_DEV_SM_CLOCK": "sm_clock_mhz",
    "DCGM_FI_DEV_MEMORY_TEMP": "mem_temp_c",
    "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION": "energy_mj",
    "DCGM_FI_DEV_XID_ERRORS": "xid_errors",
}
# Core fields are required — a GPU missing one is a fail-fast. The extended
# fields are recorded when the exporter offers them; absence is a missing row,
# never a zero.
_DCGM_CORE = ("power_w", "util_pct", "mem_used_mb", "temp_c")
_TASK: asyncio.Task[None] | None = None


def warehouse_dsn() -> str:
    """Gaius Postgres with impala_fdw. Signals :5455 remains a fallback."""
    if os.environ.get("GAIUS_WAREHOUSE_DSN"):
        return os.environ["GAIUS_WAREHOUSE_DSN"]
    if os.environ.get("GAIUS_WAREHOUSE_USE_SIGNALS", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return os.environ.get(
            "SIGNALS_WAREHOUSE_DSN",
            "postgresql://signals@127.0.0.1:5455/signals",
        )
    port = os.environ.get("PGPORT", "5444")
    return f"postgresql://gaius:gaius@127.0.0.1:{port}/zndx_gaius"


def sample_gpus() -> list[dict[str, Any]]:
    """Live DCGM exporter rows. Fail-fast if :9400 is down or a GPU is missing."""
    from gaius.engine.services.waterfall_drivers import (
        _gpu_index,
        _http_get,
        parse_prom_text,
    )

    text = _http_get(DCGM_METRICS_URL, timeout=1.0)
    if not text:
        raise RuntimeError(f"{GURU}\n  DCGM {DCGM_METRICS_URL} unreachable")
    by: dict[int, dict[str, float]] = {}
    for metric, labels, val in parse_prom_text(text):
        i = _gpu_index(labels)
        if i is None:
            continue
        rec = by.setdefault(i, {})
        if metric == "DCGM_FI_DEV_POWER_USAGE":
            rec["power_w"] = float(val)
        elif metric == "DCGM_FI_DEV_GPU_UTIL":
            rec["util_pct"] = float(val)
        elif metric == "DCGM_FI_DEV_FB_USED":
            rec["mem_used_mb"] = float(val)
        elif metric == "DCGM_FI_DEV_GPU_TEMP":
            rec["temp_c"] = float(val)
        elif metric in _DCGM_EXTRA:
            rec[_DCGM_EXTRA[metric]] = float(val)
    rows: list[dict[str, Any]] = []
    for i in sorted(by):
        rec = by[i]
        missing = [k for k in _DCGM_CORE if k not in rec]
        if missing:
            raise RuntimeError(
                f"{GURU}\n  DCGM gpu={i} missing {', '.join(missing)}"
            )
        rows.append({"gpu_index": i, **rec})
    if not rows:
        raise RuntimeError(f"{GURU}\n  DCGM returned no GPUs")
    return rows


def _tuples(now: float, gpus: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    ts_ns = int(now * 1_000_000_000)
    epoch_hour = int(now) // 3600
    return [
        (
            epoch_hour,
            ts_ns,
            g["gpu_index"],
            g["power_w"],
            g["util_pct"],
            g["mem_used_mb"],
            g["temp_c"],
        )
        for g in gpus
    ]


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
    """Watts/util from Kudu ∪ Iceberg. Query each FT with pushable preds."""
    import asyncpg
    from collections import defaultdict

    if interval not in ("minute", "hour", "day"):
        raise RuntimeError(f"{GURU}\n  bad hist interval {interval!r}")
    start_ns = int(start.astimezone(timezone.utc).timestamp() * 1_000_000_000)
    end_ns = int(end.astimezone(timezone.utc).timestamp() * 1_000_000_000)
    start_h = int(start.astimezone(timezone.utc).timestamp()) // 3600
    end_h = int(end.astimezone(timezone.utc).timestamp()) // 3600
    conn = await asyncpg.connect(warehouse_dsn(), timeout=60)
    per: dict[tuple[datetime, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    try:
        kudu = await conn.fetch(
            """
            SELECT ts_ns, gpu_index, power_w, util_pct
              FROM gpu_metrics_tier0
             WHERE ts_ns >= $1 AND ts_ns < $2
            """,
            start_ns,
            end_ns,
        )
        hot_hours = {int(r["ts_ns"]) // 1_000_000_000 // 3600 for r in kudu}
        ice_hours = [
            h for h in range(start_h, end_h + 1) if h not in hot_hours
        ]
        ice: list[Any] = []
        if ice_hours:
            ice = await conn.fetch(
                """
                SELECT ts_ns, gpu_index, power_w, util_pct
                  FROM gpu_metrics_tier1
                 WHERE epoch_hour = ANY($1::int[])
                   AND ts_ns >= $2 AND ts_ns < $3
                """,
                ice_hours,
                start_ns,
                end_ns,
            )
    finally:
        await conn.close()
    for r in list(kudu) + list(ice):
        m = _bucket_ts(int(r["ts_ns"]), interval)
        gi = int(r["gpu_index"])
        rec = per[(m, gi)]
        rec[0] += float(r["power_w"] or 0.0)
        rec[1] += float(r["util_pct"] or 0.0)
        rec[2] += 1.0
    by_m: dict[datetime, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for (m, _gi), rec in per.items():
        n = rec[2] or 1.0
        slot = by_m[m]
        slot[0] += rec[0] / n
        slot[1] += rec[1] / n
        slot[2] += 1.0
    out = [
        {
            "m": m,
            "watts": float(v[0]),
            "util": float(v[1] / v[2]) if v[2] else 0.0,
        }
        for m, v in sorted(by_m.items())
    ]
    return out


def dcgm_tuples(now: float, gpus: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Narrow gpu_dcgm rows for whichever extended fields DCGM offered."""
    ts_ns = int(now * 1_000_000_000)
    epoch_hour = int(now) // 3600
    out: list[tuple[Any, ...]] = []
    for g in gpus:
        for field in _DCGM_EXTRA.values():
            if field in g:
                out.append((epoch_hour, ts_ns, g["gpu_index"], field, float(g[field])))
    return out


def cognition_tuples(now: float, samples: list[Any]) -> list[tuple[Any, ...]]:
    """Narrow cognition_metrics rows. A gap is present=False, not zero."""
    ts_ns = int(now * 1_000_000_000)
    epoch_hour = int(now) // 3600
    return [
        (epoch_hour, ts_ns, s.name, float(s.value), bool(s.present)) for s in samples
    ]


async def insert_dcgm_rows(conn: Any, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO gpu_dcgm_tier0 (epoch_hour, ts_ns, gpu_index, field, value)
        VALUES ($1, $2, $3, $4, $5)
        """,
        rows,
    )


async def insert_cognition_rows(conn: Any, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO cognition_metrics_tier0 (
            epoch_hour, ts_ns, channel, value, present
        ) VALUES ($1, $2, $3, $4, $5)
        """,
        rows,
    )


# Kudu range partitions are per UTC hour; an INSERT into an hour with no
# partition fails the flush. impala_fdw_exec permits exactly this DDL.
_TIER0_TABLES = ("gpu_metrics_tier0", "gpu_dcgm_tier0", "cognition_metrics_tier0")


async def ensure_hour_partition(conn: Any, hour: int) -> dict[str, str]:
    """Best-effort ADD RANGE PARTITION for ``hour`` on every tier0 table.

    Already-present is success. Anything else is returned for the caller to
    log — the INSERT that follows carries the real fail-fast.
    """
    out: dict[str, str] = {}
    for tbl in _TIER0_TABLES:
        add = (
            f"ALTER TABLE signals_dataproducts.{tbl} "
            f"ADD RANGE PARTITION {hour} <= VALUES < {hour + 1}"
        )
        err = ""
        try:
            await conn.fetchval("SELECT impala_fdw_exec($1, $2)", "impala_kudu_srv", add)
        except Exception as e:
            err = " ".join(str(e).split())[:160]
        # The FDW's own post-ALTER check reads SHOW RANGE PARTITIONS before the
        # catalog has settled and reports "did not verify" for a partition that
        # is in fact present. Ask again ourselves — that answer is the one that
        # decides whether the hour's INSERTs can land.
        try:
            shown = await conn.fetchval(
                "SELECT impala_fdw_exec($1, $2)",
                "impala_kudu_srv",
                f"SHOW RANGE PARTITIONS signals_dataproducts.{tbl}",
            )
        except Exception as e:
            out[tbl] = err or " ".join(str(e).split())[:160]
            continue
        out[tbl] = "present" if f"VALUE = {hour}" in (shown or "") else (
            err or "partition absent after ADD"
        )
    return out


async def insert_gpu_rows(conn: Any, rows: list[tuple[Any, ...]]) -> None:
    await conn.executemany(
        """
        INSERT INTO gpu_metrics_tier0 (
            epoch_hour, ts_ns, gpu_index, power_w, util_pct, mem_used_mb, temp_c
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        rows,
    )


async def _loop() -> None:
    import asyncpg

    # The cognition drivers only run under the poller. The in-process strip
    # used to start it; now the warehouse writer is their only consumer, so
    # the ingest owns that. Without this every cognition channel records
    # present=False forever and the strip shows eight dead rows.
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
            hour = int(now) // 3600
            if hour != last_hour:
                # New UTC hour: its range partition must exist before the
                # first INSERT of the hour, on every tier0 table.
                status = await ensure_hour_partition(conn, hour)
                logger.info("warehouse partitions hour=%s %s", hour, status)
                last_hour = hour
            await insert_gpu_rows(conn, _tuples(now, gpus))
            await insert_dcgm_rows(conn, dcgm_tuples(now, gpus))
            from gaius.engine.services.waterfall_drivers import cognition_samples

            cog = cognition_tuples(now, cognition_samples())
            await insert_cognition_rows(conn, cog)
            inserted += len(gpus)
            ticks += 1
            if ticks == 1 or ticks % 30 == 0:
                logger.info(
                    "warehouse ingest ticks=%s inserted=%s gpus=%s cognition=%s "
                    "last_w=%s",
                    ticks,
                    inserted,
                    len(gpus),
                    sum(1 for r in cog if r[4]),
                    [round(g["power_w"], 1) for g in gpus],
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
