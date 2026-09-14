"""gaius.theta.cycle — THS settle, Kudu DROP RANGE, Iceberg expire+orphan GC.

One Metaflow (ThetaCycleFlow) runs this. Scratch tablets are the storage
layer; cycle names are the product surface.

Guru: #THETA.00000007.CYCLE
Never row DELETE. Expire Iceberg only as whole epoch_hour partitions.
Live UTC hour is never dropped from Kudu.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

GURU = "#THETA.00000007.CYCLE"
FDW_SERVER = "impala_kudu_srv"
ICEBERG_NS = "signals_dataproducts"

# Product FT (Gaius Postgres) → physical Kudu tablet → Polar Iceberg twin.
FAMILIES: tuple[tuple[str, str, str], ...] = (
    (
        "theta_cycle_vertex_tier0",
        "signals_dataproducts.theta_scratch_vertex_tier0",
        "theta_scratch_vertex_tier1",
    ),
    (
        "theta_cycle_edge_tier0",
        "signals_dataproducts.theta_scratch_edge_tier0",
        "theta_scratch_edge_tier1",
    ),
    (
        "theta_cycle_incidence_tier0",
        "signals_dataproducts.theta_scratch_incidence_tier0",
        "theta_scratch_incidence_tier1",
    ),
)

# Fibonacci slot 9: 34 h hot on Kudu after verify Iceberg still holds history.
DEFAULT_KUDU_HOT_HOURS = 1  # drop a closed hour once Iceberg matches (gpu_metrics grain)
DEFAULT_ICEBERG_RETAIN_HOURS = 34 * 24  # 34 days ≈ slot-9 days; Iceberg is the warm store


def epoch_hour(now: float | None = None) -> int:
    return int(now if now is not None else time.time()) // 3600


@dataclass
class HourPlan:
    hour: int
    kudu_n: int
    ice_n: int
    needs_analog: bool
    drop_sql: str


@dataclass
class CycleReport:
    now_hour: int
    analoged: list[int] = field(default_factory=list)
    dropped: list[int] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)
    planned: list[dict[str, Any]] = field(default_factory=list)
    apply: bool = False


def refuse_drop(hour: int, ice_n: int, kudu_n: int) -> None:
    if ice_n < kudu_n:
        raise RuntimeError(
            f"{GURU} refuse DROP hour={hour} ice={ice_n} < kudu={kudu_n}"
        )


def partition_delete_sql(hour: int) -> str:
    """Equality on identity partition — metadata-only. Never a row predicate."""
    return f"epoch_hour = {int(hour)}"


def plan_closed_hours(
    *,
    kudu: dict[int, int],
    ice: dict[int, int],
    now_hour: int,
    kudu_table: str,
) -> list[HourPlan]:
    out: list[HourPlan] = []
    for hour in sorted(h for h in kudu if h < now_hour):
        kudu_n = int(kudu[hour])
        ice_n = int(ice.get(hour, 0))
        out.append(
            HourPlan(
                hour=hour,
                kudu_n=kudu_n,
                ice_n=ice_n,
                needs_analog=ice_n < kudu_n,
                drop_sql=(
                    f"ALTER TABLE {kudu_table} "
                    f"DROP RANGE PARTITION VALUE = {hour}"
                ),
            )
        )
    return out


async def _hour_counts(conn: Any, ft: str, ice_table: str) -> tuple[dict[int, int], dict[int, int]]:
    kudu: dict[int, int] = {}
    for row in await conn.fetch(
        f"SELECT epoch_hour, count(*)::bigint AS n FROM {ft} GROUP BY 1"
    ):
        kudu[int(row["epoch_hour"])] = int(row["n"])
    ice = _iceberg_hour_counts(ice_table)
    return kudu, ice


def _iceberg_hour_counts(ice_table: str) -> dict[int, int]:
    table = _load_iceberg(ice_table)
    out: dict[int, int] = {}
    scan = table.scan().to_arrow()
    if scan.num_rows == 0 or "epoch_hour" not in scan.column_names:
        return out
    for h in scan.column("epoch_hour").to_pylist():
        if h is None:
            continue
        out[int(h)] = out.get(int(h), 0) + 1
    return out


def _load_iceberg(ice_table: str) -> Any:
    import os

    from pyiceberg.catalog import load_catalog

    props = {
        "type": "rest",
        "uri": os.environ.get("SIGNALS_POLARIS_URI", "http://127.0.0.1:8181/api/catalog").rstrip("/"),
        "warehouse": os.environ.get("POLARIS_CATALOG_NAME", "signals"),
        "credential": os.environ.get("SIGNALS_POLARIS_CREDENTIAL", "admin:admin"),
        "scope": "PRINCIPAL_ROLE:ALL",
        "header.X-Iceberg-Access-Delegation": "",
        "s3.endpoint": os.environ.get("SIGNALS_RUSTFS_ENDPOINT", "http://127.0.0.1:9010"),
        "s3.access-key-id": os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin"),
        "s3.secret-access-key": os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin"),
        "s3.path-style-access": "true",
        "s3.region": "us-east-1",
    }
    return load_catalog("signals", **props).load_table(f"{ICEBERG_NS}.{ice_table}")


async def analog_hour(conn: Any, ft: str, ice_table: str, hour: int) -> int:
    rows = await conn.fetch(f"SELECT * FROM {ft} WHERE epoch_hour = $1", hour)
    if not rows:
        return 0
    table = _load_iceberg(ice_table)
    import pyarrow as pa

    recs = [dict(r) for r in rows]
    table.append(pa.Table.from_pylist(recs, schema=table.schema().as_arrow()))
    return len(recs)


async def drop_range(conn: Any, kudu_table: str, hour: int) -> None:
    ddl = f"ALTER TABLE {kudu_table} DROP RANGE PARTITION VALUE = {int(hour)}"
    await conn.fetchval("SELECT impala_fdw_exec($1, $2)", FDW_SERVER, ddl)


def expire_iceberg_hours(ice_table: str, hours: list[int]) -> list[int]:
    if not hours:
        return []
    table = _load_iceberg(ice_table)
    done: list[int] = []
    for h in hours:
        pred = partition_delete_sql(h)
        if not pred.startswith("epoch_hour = "):
            raise RuntimeError(f"{GURU} refuse non-partition expire {pred!r}")
        table.delete(pred)
        done.append(h)
    return done


def cleanup_iceberg(ice_table: str) -> None:
    table = _load_iceberg(ice_table)
    maint = getattr(table, "maintenance", None)
    if maint is None:
        logger.warning("%s no table.maintenance on %s", GURU, ice_table)
        return
    expire = getattr(maint, "expire_snapshots", None)
    if callable(expire):
        expire().commit()
    orphans = getattr(maint, "delete_orphan_files", None)
    if callable(orphans):
        orphans().commit()


async def run_cycle(
    conn: Any,
    *,
    apply: bool,
    now_hour: int | None = None,
    retain_hours: int = DEFAULT_ICEBERG_RETAIN_HOURS,
    analog: bool = True,
    drop: bool = True,
    expire: bool = True,
) -> CycleReport:
    now = int(now_hour if now_hour is not None else epoch_hour())
    report = CycleReport(now_hour=now, apply=apply)
    retain_after = now - int(retain_hours)
    for ft, kudu_table, ice_table in FAMILIES:
        kudu, ice = await _hour_counts(conn, ft, ice_table)
        plans = plan_closed_hours(
            kudu=kudu, ice=ice, now_hour=now, kudu_table=kudu_table
        )
        for p in plans:
            item = {
                "family": ft,
                "hour": p.hour,
                "kudu_n": p.kudu_n,
                "ice_n": p.ice_n,
                "needs_analog": p.needs_analog,
                "drop_sql": p.drop_sql,
            }
            report.planned.append(item)
            if not apply:
                continue
            if analog and p.needs_analog:
                await analog_hour(conn, ft, ice_table, p.hour)
                ice = _iceberg_hour_counts(ice_table)
                p.ice_n = int(ice.get(p.hour, 0))
                item["ice_n"] = p.ice_n
                report.analoged.append(p.hour)
            if drop:
                refuse_drop(p.hour, p.ice_n, p.kudu_n)
                await drop_range(conn, kudu_table, p.hour)
                leftover = int((await _hour_counts(conn, ft, ice_table))[0].get(p.hour, 0))
                if leftover:
                    raise RuntimeError(
                        f"{GURU} DROP RANGE {p.hour} left {leftover} Kudu rows on {ft}"
                    )
                report.dropped.append(p.hour)
        if expire:
            ice = _iceberg_hour_counts(ice_table)
            stale = sorted(h for h in ice if h < retain_after)
            if apply and stale:
                report.expired.extend(expire_iceberg_hours(ice_table, stale))
                cleanup_iceberg(ice_table)
    return report

