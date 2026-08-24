"""Engine warehouse: DCGM → Postgres impala_fdw INSERT → Kudu.

The Gaius engine is the writer. Postgres :5455 `gpu_metrics_tier0`
(kudu_scan) is the insert path. `gpu_metrics` is the HS2 UNION view of
hot Kudu ∪ cold Iceberg and is not writable (N3).
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
    "  Try: psql -h 127.0.0.1 -p 5455 -U signals -d signals "
    "-c 'INSERT INTO gpu_metrics_tier0 ...'\n"
    "  Or:  /health fix engine"
)

INTERVAL_S = float(os.environ.get("GAIUS_WAREHOUSE_INGEST_S", "1"))
DCGM_METRICS_URL = os.environ.get("GAIUS_DCGM_METRICS_URL", "http://127.0.0.1:9400/metrics")
_TASK: asyncio.Task[None] | None = None


def warehouse_dsn() -> str:
    return os.environ.get(
        "SIGNALS_WAREHOUSE_DSN",
        "postgresql://signals@127.0.0.1:5455/signals",
    )


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
    rows: list[dict[str, Any]] = []
    for i in sorted(by):
        rec = by[i]
        missing = [
            k
            for k in ("power_w", "util_pct", "mem_used_mb", "temp_c")
            if k not in rec
        ]
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

    dsn = warehouse_dsn()
    conn = None
    inserted = 0
    ticks = 0
    while True:
        t0 = time.monotonic()
        try:
            gpus = sample_gpus()
            now = time.time()
            if conn is None or conn.is_closed():
                conn = await asyncpg.connect(dsn, timeout=8)
            await insert_gpu_rows(conn, _tuples(now, gpus))
            inserted += len(gpus)
            ticks += 1
            if ticks == 1 or ticks % 30 == 0:
                logger.info(
                    "warehouse ingest ticks=%s inserted=%s gpus=%s last_w=%s",
                    ticks,
                    inserted,
                    len(gpus),
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
