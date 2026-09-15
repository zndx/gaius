"""Typed FMP warehouse tables (Iceberg ``gaius.fmp.*``).

Not ``raw.fmp_exchange`` JSON blobs. Starter Annual columns only.
Scratch IRIs until Aegir admits them into sdg-corpora (K15).
Kudu tier0 / FDW IMPORT is the next ops hop; this module lands Iceberg.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("gaius.hx.fmp_warehouse")

GURU = "#FMP.00000010.WAREHOUSE"
NAMESPACE = "gaius.fmp"

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
    },
    "earnings": {
        "symbol": "https://signals.zndx.org/sdg#TickerSymbol",
        "date": "https://signals.zndx.org/sdg#EarningsAnnouncementDate",
        "eps": "https://signals.zndx.org/sdg#EarningsPerShare",
        "eps_estimated": "https://signals.zndx.org/sdg#EarningsPerShareEstimate",
    },
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

        out.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "date": str(row.get("date") or row.get("epsDate") or "") or None,
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


def land(name: str, rows: list[dict[str, Any]], *, catalog: Any | None = None) -> dict[str, Any]:
    """Append typed rows to Iceberg ``gaius.fmp.<name>``. Fail-closed on catalog."""
    if not rows:
        return {"table": f"{NAMESPACE}.{name}", "rows": 0, "ok": True}
    if catalog is None:
        from gaius.hx.catalog import get_catalog

        try:
            catalog = get_catalog()
        except Exception as e:
            raise RuntimeError(
                f"{GURU} Polarisfork catalog unavailable: {e}\n"
                "  Iceberg REST is the land path. Do not write meta.* on Gaius :5444."
            ) from e
    import pyarrow as pa

    table = ensure_table(catalog, name)
    arrow = pa.Table.from_pylist(rows, schema=table.schema().as_arrow())
    table.append(arrow)
    snap = table.current_snapshot()
    return {
        "ok": True,
        "table": f"{NAMESPACE}.{name}",
        "rows": len(rows),
        "snapshot_id": getattr(snap, "snapshot_id", None),
        "iris": dict(COLUMN_IRIS.get(name, {})),
    }
