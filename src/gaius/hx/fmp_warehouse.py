"""Typed FMP warehouse tables (THS: Kudu ``fmp_*_tier0`` + Postgres views).

Not ``raw.fmp_exchange`` JSON blobs. Starter Annual columns only.
Scratch IRIs until Aegir admits them into sdg-corpora (K15).
Kudu INSERT via impala_fdw ``kudu_scan`` is the land path; Polarisfork
Iceberg ``gaius.fmp.*`` is a best-effort copy. Metabase reads
``warehouse.v_fmp_*`` (not Gaius :3100 ``meta.*``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("gaius.hx.fmp_warehouse")

GURU = "#FMP.00000010.WAREHOUSE"
NAMESPACE = "gaius.fmp"
VIEW_NAMESPACE = "warehouse"

# Scratch SDG-shaped IRIs — not Aegir-admitted. Projector writes these
# into Metabase field settings.scientific; do not pretend they are OWL TBox.
COLUMN_IRIS: dict[str, dict[str, str]] = {
    "profile": {
        "symbol": "https://signals.zndx.org/sdg#TickerSymbol",
        "name": "https://signals.zndx.org/sdg#OrganizationName",
        "exchange": "https://signals.zndx.org/sdg#MarketExchange",
        "sector": "https://signals.zndx.org/sdg#IndustrySector",
        "industry": "https://signals.zndx.org/sdg#IndustryClassification",
        "market_cap": "https://signals.zndx.org/sdg#MarketCapitalization",
        "as_of": "https://signals.zndx.org/sdg#ObservationTime",
    },
    "filings": {
        "symbol": "https://signals.zndx.org/sdg#TickerSymbol",
        "form": "https://signals.zndx.org/sdg#SecFormType",
        "filed": "https://signals.zndx.org/sdg#SecFilingDate",
        "url": "https://signals.zndx.org/sdg#SecFilingUrl",
        "as_of": "https://signals.zndx.org/sdg#ObservationTime",
    },
    "earnings": {
        "symbol": "https://signals.zndx.org/sdg#TickerSymbol",
        "announced": "https://signals.zndx.org/sdg#EarningsAnnouncementDate",
        "eps": "https://signals.zndx.org/sdg#EarningsPerShare",
        "eps_estimated": "https://signals.zndx.org/sdg#EarningsPerShareEstimate",
        "as_of": "https://signals.zndx.org/sdg#ObservationTime",
    },
}

# Metabase / Postgres face. Last path segment is what ProjectWarehouse matches.
VIEW_NAMES = {
    "profile": f"{VIEW_NAMESPACE}.v_fmp_profile",
    "filings": f"{VIEW_NAMESPACE}.v_fmp_filings",
    "earnings": f"{VIEW_NAMESPACE}.v_fmp_earnings",
}

KUDU_TABLES = {
    "profile": "fmp_profile_tier0",
    "filings": "fmp_filings_tier0",
    "earnings": "fmp_earnings_tier0",
}

INSERT_SQL = {
    "profile": """
        INSERT INTO fmp_profile_tier0 (
            epoch_hour, ts_ns, symbol, name, exchange, sector, industry,
            market_cap, website, description
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
    "filings": """
        INSERT INTO fmp_filings_tier0 (
            epoch_hour, ts_ns, symbol, form, filed, url
        ) VALUES ($1, $2, $3, $4, $5, $6)
        """,
    "earnings": """
        INSERT INTO fmp_earnings_tier0 (
            epoch_hour, ts_ns, symbol, announced, eps, eps_estimated
        ) VALUES ($1, $2, $3, $4, $5, $6)
        """,
}


def _schema_profile():
    from pyiceberg.schema import Schema
    from pyiceberg.types import DoubleType, NestedField, StringType, TimestamptzType

    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "name", StringType(), required=False),
        NestedField(3, "exchange", StringType(), required=False),
        NestedField(4, "sector", StringType(), required=False),
        NestedField(5, "industry", StringType(), required=False),
        NestedField(6, "market_cap", DoubleType(), required=False),
        NestedField(7, "website", StringType(), required=False),
        NestedField(8, "description", StringType(), required=False),
        NestedField(9, "as_of", TimestamptzType(), required=True),
    )


def _schema_filings():
    from pyiceberg.schema import Schema
    from pyiceberg.types import NestedField, StringType, TimestamptzType

    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "form", StringType(), required=False),
        NestedField(3, "filed", StringType(), required=False),
        NestedField(4, "url", StringType(), required=False),
        NestedField(5, "as_of", TimestamptzType(), required=True),
    )


def _schema_earnings():
    from pyiceberg.schema import Schema
    from pyiceberg.types import DoubleType, NestedField, StringType, TimestamptzType

    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "date", StringType(), required=False),
        NestedField(3, "eps", DoubleType(), required=False),
        NestedField(4, "eps_estimated", DoubleType(), required=False),
        NestedField(5, "as_of", TimestamptzType(), required=True),
    )


SCHEMAS = {
    "profile": _schema_profile,
    "filings": _schema_filings,
    "earnings": _schema_earnings,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def flatten_profile(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = _now()
    out = []
    for row in items:
        cap = row.get("market_cap")
        try:
            cap_f = float(cap) if cap is not None else None
        except (TypeError, ValueError):
            cap_f = None
        out.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "name": str(row.get("name") or "") or None,
                "exchange": str(row.get("exchange") or "") or None,
                "sector": str(row.get("sector") or "") or None,
                "industry": str(row.get("industry") or "") or None,
                "market_cap": cap_f,
                "website": str(row.get("website") or "") or None,
                "description": str(row.get("description") or "") or None,
                "as_of": now,
            }
        )
    return [r for r in out if r["symbol"]]


def flatten_filings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = _now()
    out = []
    for row in items:
        out.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "form": str(row.get("form") or "") or None,
                "filed": str(row.get("filed") or "") or None,
                "url": str(row.get("url") or "") or None,
                "as_of": now,
            }
        )
    return [r for r in out if r["symbol"]]


def flatten_earnings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = _now()
    out = []
    for row in items:
        def _f(key: str) -> float | None:
            v = row.get(key)
            if v is None:
                v = row.get("epsEstimated") if key == "eps_estimated" else v
            try:
                return float(v) if v is not None and v != "" else None
            except (TypeError, ValueError):
                return None

        announced = str(row.get("announced") or row.get("date") or row.get("epsDate") or "") or None
        out.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "announced": announced,
                "date": announced,
                "eps": _f("eps"),
                "eps_estimated": _f("eps_estimated") or _f("epsEstimated"),
                "as_of": now,
            }
        )
    return [r for r in out if r["symbol"]]


FLATTEN = {
    "profile": flatten_profile,
    "quote": flatten_profile,
    "filings": flatten_filings,
    "earnings": flatten_earnings,
    "calendar": flatten_earnings,
}


def ensure_table(catalog: Any, name: str) -> Any:
    if name not in SCHEMAS:
        raise RuntimeError(f"{GURU} unknown warehouse table {name!r}")
    table_id = f"{NAMESPACE}.{name}"
    try:
        return catalog.load_table(table_id)
    except Exception:
        try:
            catalog.create_namespace(NAMESPACE)
        except Exception:
            pass
        return catalog.create_table(table_id, schema=SCHEMAS[name]())


def kudu_rows(name: str, rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """THS tuples for ``fmp_*_tier0``. Unique ts_ns per row (PK)."""
    if name not in KUDU_TABLES:
        raise RuntimeError(f"{GURU} unknown warehouse table {name!r}")
    now = _now()
    ts0 = int(now.timestamp() * 1_000_000_000)
    eh = int(now.timestamp()) // 3600
    out: list[tuple[Any, ...]] = []
    for i, row in enumerate(rows):
        ts_ns = ts0 + i
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        if name == "profile":
            out.append(
                (
                    eh,
                    ts_ns,
                    symbol,
                    row.get("name"),
                    row.get("exchange"),
                    row.get("sector"),
                    row.get("industry"),
                    row.get("market_cap"),
                    row.get("website"),
                    row.get("description"),
                )
            )
        elif name == "filings":
            out.append(
                (
                    eh,
                    ts_ns,
                    symbol,
                    row.get("form"),
                    row.get("filed"),
                    row.get("url"),
                )
            )
        else:
            out.append(
                (
                    eh,
                    ts_ns,
                    symbol,
                    row.get("announced") or row.get("date"),
                    row.get("eps"),
                    row.get("eps_estimated"),
                )
            )
    return out


def _result(name: str, n: int, **extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "table": VIEW_NAMES[name],
        "kudu_table": KUDU_TABLES[name],
        "rows": n,
        "iris": dict(COLUMN_IRIS.get(name, {})),
        **extra,
    }


async def _ensure_day_partitions(conn: Any, hour: int) -> None:
    from gaius.engine.services.warehouse_ingest import HOURS_PER_DAY, day_floor

    day0 = day_floor(hour)
    for tbl in KUDU_TABLES.values():
        for d in (day0, day0 + HOURS_PER_DAY):
            add = (
                f"ALTER TABLE signals_dataproducts.{tbl} "
                f"ADD RANGE PARTITION {d} <= VALUES < {d + HOURS_PER_DAY}"
            )
            try:
                await conn.fetchval("SELECT impala_fdw_exec($1, $2)", "impala_kudu_srv", add)
            except Exception as e:
                msg = " ".join(str(e).split()).lower()
                if "already" not in msg and "overlap" not in msg:
                    raise RuntimeError(
                        f"{GURU} ADD RANGE PARTITION {tbl} failed: {e}\n"
                        "  Apply signals `python -m signals.ops schema-apply` "
                        "(config/platform/fmp-kudu.sql) then "
                        "gaius scripts/warehouse/fmp-fdw.sql."
                    ) from e


async def land_kudu_async(name: str, rows: list[dict[str, Any]], *, conn: Any | None = None) -> dict[str, Any]:
    payload = kudu_rows(name, rows)
    if not payload:
        return _result(name, 0)
    sql = INSERT_SQL[name]
    own = conn is None
    if own:
        import asyncpg
        from gaius.engine.services.warehouse_ingest import warehouse_dsn

        try:
            conn = await asyncpg.connect(warehouse_dsn(), timeout=60)
        except Exception as e:
            raise RuntimeError(
                f"{GURU} warehouse DSN unavailable: {e}\n"
                "  Gaius :5444 impala_fdw is the land path. "
                "Do not write meta.* on :3100."
            ) from e
    try:
        await _ensure_day_partitions(conn, int(payload[0][0]))
        await conn.executemany(sql, payload)
    except Exception as e:
        raise RuntimeError(
            f"{GURU} INSERT {KUDU_TABLES[name]} failed: {e}\n"
            "  Need signals schema-apply (fmp-kudu.sql) and "
            "scripts/warehouse/fmp-fdw.sql on :5444."
        ) from e
    finally:
        if own and conn is not None:
            await conn.close()
    return _result(name, len(payload))


def land_kudu(
    name: str,
    rows: list[dict[str, Any]],
    *,
    execute: Any | None = None,
) -> dict[str, Any]:
    """INSERT typed rows into Kudu ``fmp_*_tier0`` via impala_fdw. Fail-closed."""
    if name not in KUDU_TABLES:
        raise RuntimeError(f"{GURU} unknown warehouse table {name!r}")
    if not rows:
        return _result(name, 0)
    payload = kudu_rows(name, rows)
    if execute is not None:
        execute(INSERT_SQL[name], payload)
        return _result(name, len(payload))
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(land_kudu_async(name, rows))
    raise RuntimeError(
        f"{GURU} land_kudu called from a running loop; use land_kudu_async"
    )


def land_iceberg(name: str, rows: list[dict[str, Any]], *, catalog: Any | None = None) -> dict[str, Any]:
    """Append typed rows to Polarisfork Iceberg ``gaius.fmp.<name>`` (copy)."""
    if name not in SCHEMAS:
        raise RuntimeError(f"{GURU} unknown warehouse table {name!r}")
    if not rows:
        return {"table": f"{NAMESPACE}.{name}", "rows": 0, "ok": True}
    if catalog is None:
        from gaius.hx.catalog import get_catalog

        try:
            catalog = get_catalog()
        except Exception as e:
            raise RuntimeError(
                f"{GURU} Polarisfork catalog unavailable: {e}\n"
                "  Iceberg REST is the copy path. Kudu via FDW is the land path."
            ) from e
    import pyarrow as pa

    table = ensure_table(catalog, name)
    ice_rows = [{k: v for k, v in r.items() if k != "announced"} for r in rows]
    arrow = pa.Table.from_pylist(ice_rows, schema=table.schema().as_arrow())
    table.append(arrow)
    snap = table.current_snapshot()
    return {
        "ok": True,
        "table": f"{NAMESPACE}.{name}",
        "rows": len(rows),
        "snapshot_id": getattr(snap, "snapshot_id", None),
        "iris": dict(COLUMN_IRIS.get(name, {})),
    }


def land(
    name: str,
    rows: list[dict[str, Any]],
    *,
    catalog: Any | None = None,
    execute: Any | None = None,
) -> dict[str, Any]:
    """Kudu FDW INSERT (required). Polarisfork Iceberg is a best-effort copy."""
    if name not in SCHEMAS:
        raise RuntimeError(f"{GURU} unknown warehouse table {name!r}")
    result = land_kudu(name, rows, execute=execute)
    if execute is not None:
        return result
    try:
        result["iceberg"] = land_iceberg(name, rows, catalog=catalog)
    except Exception as e:
        log.warning("polarisfork copy skipped: %s", e)
        result["iceberg"] = {"ok": False, "error": str(e)[:200]}
    return result
