"""Write Aperture remainder windows into gaius.theta.cycle scratch THS.

Fail-open: a dark warehouse must not stall thinking / ambient synthesis.
Expire is DROP RANGE PARTITION (hour), never row DELETE.

Guru: #THETA.00000006.SCRATCHFT
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

GURU = "#THETA.00000006.SCRATCHFT"
_TIER0 = (
    "theta_scratch_vertex_tier0",
    "theta_scratch_edge_tier0",
    "theta_scratch_incidence_tier0",
)


def _vertex_id(axis: str, entry_id: str, start: int, end: int) -> str:
    raw = f"{axis}|{entry_id}|{start}|{end}".encode()
    return hashlib.blake2b(raw, digest_size=16).hexdigest()


def _text_id(entry_id: str) -> int:
    h = hashlib.blake2b((entry_id or "").encode(), digest_size=8).digest()
    return int.from_bytes(h, "big", signed=True)


async def ensure_hour_partitions(conn: Any, hour: int) -> None:
    """ADD RANGE PARTITION VALUE = hour on scratch tier0 (gpu_metrics grain)."""
    for tbl in _TIER0:
        add = (
            f"ALTER TABLE signals_dataproducts.{tbl} "
            f"ADD RANGE PARTITION VALUE = {int(hour)}"
        )
        try:
            await conn.fetchval(
                "SELECT impala_fdw_exec($1, $2)", "impala_kudu_srv", add
            )
        except Exception as e:
            msg = " ".join(str(e).split())
            if "already" not in msg.lower() and "overlap" not in msg.lower():
                raise


async def record_remainder(
    conn: Any,
    spans: list[dict[str, Any]],
    *,
    aperture: str = "",
    c_epoch: str = "",
    tau: float | None = None,
    hx_generation_id: str = "",
) -> int:
    """INSERT remainder vertices. Returns rows attempted; 0 if spans empty."""
    if not spans:
        return 0
    now = time.time()
    eh = int(now) // 3600
    ts_ns = int(now * 1_000_000_000)
    await ensure_hour_partitions(conn, eh)
    rows = []
    for s in spans:
        rows.append(
            (
                eh,
                ts_ns,
                _vertex_id(
                    str(s.get("axis") or ""),
                    str(s.get("entry_id") or ""),
                    int(s.get("start") or 0),
                    int(s.get("end") or 0),
                ),
                "window",
                _text_id(str(s.get("entry_id") or "")),
                None,
                None,
                int(s.get("start") or 0),
                int(s.get("end") or 0),
                str(s.get("reason") or "none"),
                tau,
                float(s.get("margin") or 0.0),
                c_epoch,
                aperture,
                hx_generation_id,
            )
        )
    await conn.executemany(
        """
        INSERT INTO theta_scratch_vertex_tier0 (
            epoch_hour, ts_ns, vertex_id, kind, text_id, layer, feature_idx,
            window_start, window_end, reason, tau, margin, c_epoch, aperture,
            hx_generation_id
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        """,
        rows,
    )
    return len(rows)


async def record_remainder_fail_open(
    pool: Any | None,
    spans: list[dict[str, Any]],
    *,
    aperture: str = "",
    c_epoch: str = "",
    tau: float | None = None,
) -> int:
    if pool is None or not spans:
        return 0
    try:
        async with pool.acquire() as conn:
            return await record_remainder(
                conn,
                spans,
                aperture=aperture,
                c_epoch=c_epoch,
                tau=tau,
            )
    except Exception:
        logger.warning(
            "scratch remainder not landed (%s spans)\n  Guru: %s",
            len(spans),
            GURU,
            exc_info=True,
        )
        return 0
