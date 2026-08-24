"""Engine warehouse ingest: nvidia-smi → Postgres impala_fdw INSERT → Kudu.

The Gaius engine is the writer. Postgres :5455 `gpu_metrics_tier0`
(kudu_scan) is the insert path. `gpu_metrics` is the HS2 UNION view of
hot Kudu ∪ cold Iceberg and is not writable (N3).
Guru: #EN.00000031.FDWINGEST
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
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
NVIDIA_SMI = os.environ.get("NVIDIA_SMI", "nvidia-smi")
_TASK: asyncio.Task[None] | None = None


def warehouse_dsn() -> str:
    return os.environ.get(
        "SIGNALS_WAREHOUSE_DSN",
        "postgresql://signals@127.0.0.1:5455/signals",
    )


def sample_gpus() -> list[dict[str, Any]]:
    """Live nvidia-smi rows. Fail-fast if the binary or parse fails."""
    proc = subprocess.run(
        [
            NVIDIA_SMI,
            "--query-gpu=index,power.draw,utilization.gpu,memory.used,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=2.0,
    )
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            raise RuntimeError(f"{GURU}\n  nvidia-smi parse: {line!r}")
        rows.append(
            {
                "gpu_index": int(float(parts[0])),
                "power_w": float(parts[1]),
                "util_pct": float(parts[2]),
                "mem_used_mb": float(parts[3]),
                "temp_c": float(parts[4]),
            }
        )
    if not rows:
        raise RuntimeError(f"{GURU}\n  nvidia-smi returned no GPUs")
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
