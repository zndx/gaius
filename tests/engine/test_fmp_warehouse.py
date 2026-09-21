"""Typed FMP warehouse flatten + Kudu land shape + Metabase peer pick."""
from __future__ import annotations

import pytest

from gaius.engine.services.fmp_warehouse import metabase_peer, resolve_metabase_target
from gaius.hx.fmp_warehouse import (
    COLUMN_IRIS,
    VIEW_NAMES,
    flatten_earnings,
    flatten_filings,
    flatten_profile,
    kudu_rows,
    land,
)


def test_flatten_profile_requires_symbol():
    rows = flatten_profile(
        [{"symbol": "aapl", "name": "Apple", "market_cap": 1e12, "sector": "Tech"}]
    )
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["market_cap"] == 1e12
    assert flatten_profile([{"name": "nope"}]) == []


def test_flatten_filings():
    rows = flatten_filings([{"symbol": "CHTR", "form": "10-K", "url": "https://sec"}])
    assert rows[0]["form"] == "10-K"


def test_flatten_earnings_announced():
    rows = flatten_earnings([{"symbol": "AAPL", "date": "2026-01-29", "eps": 1.5}])
    assert rows[0]["announced"] == "2026-01-29"
    assert rows[0]["eps"] == 1.5


def test_flatten_quote_keeps_numeric_price():
    from gaius.hx.fmp_warehouse import flatten_quote

    rows = flatten_quote(
        [{"symbol": "slb", "name": "Schlumberger", "price": 38.5, "change": 0.4, "volume": 1e6}]
    )
    assert rows[0]["symbol"] == "SLB"
    assert rows[0]["price"] == 38.5
    assert rows[0]["volume"] == 1000000
    assert flatten_quote([{"symbol": "SLB"}]) == []


def test_flatten_eod_bars():
    from gaius.hx.fmp_warehouse import flatten_eod

    rows = flatten_eod(
        [{"symbol": "SLB", "as_of": "2026-09-14", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    )
    assert rows[0]["bar_date"] == "2026-09-14"
    assert rows[0]["close"] == 1.5


def test_scratch_iris_are_sdg_shaped():
    for cols in COLUMN_IRIS.values():
        for iri in cols.values():
            assert iri.startswith("https://signals.zndx.org/sdg#")
    assert "announced" in COLUMN_IRIS["earnings"]
    assert VIEW_NAMES["profile"] == "warehouse.v_fmp_profile"


def test_kudu_rows_are_ths_shaped():
    rows = flatten_profile(
        [{"symbol": "aapl", "name": "Apple", "market_cap": 1e12}]
    )
    payload = kudu_rows("profile", rows)
    eh, ts_ns, symbol, name, *_rest = payload[0]
    assert isinstance(eh, int) and eh > 0
    assert isinstance(ts_ns, int) and ts_ns > 0
    assert symbol == "AAPL" and name == "Apple"
    two = kudu_rows(
        "filings",
        flatten_filings(
            [
                {"symbol": "AAPL", "form": "10-K"},
                {"symbol": "MSFT", "form": "10-Q"},
            ]
        ),
    )
    assert two[0][1] != two[1][1]
    from gaius.hx.fmp_warehouse import flatten_eod, flatten_quote

    q = kudu_rows("quote", flatten_quote([{"symbol": "SLB", "price": 38.5, "volume": 10}]))
    assert q[0][2] == "SLB" and q[0][5] == 38.5
    e = kudu_rows(
        "eod",
        flatten_eod([{"symbol": "SLB", "as_of": "2026-09-14", "close": 38.1}]),
    )
    assert e[0][2] == "SLB" and e[0][3] == "2026-09-14" and e[0][7] == 38.1


def test_land_kudu_execute_inserts():
    calls: list[tuple] = []

    def execute(sql, rows):
        calls.append((sql, rows))

    out = land(
        "profile",
        flatten_profile([{"symbol": "MSFT", "name": "Microsoft"}]),
        execute=execute,
    )
    assert "INSERT INTO fmp_profile_tier0" in calls[0][0]
    assert calls[0][1][0][2] == "MSFT"
    assert out["table"] == "warehouse.v_fmp_profile"
    assert out["kudu_table"] == "fmp_profile_tier0"
    assert out["rows"] == 1
    assert out["iris"]["symbol"].endswith("TickerSymbol")


def test_land_unknown_table_fail_closed():
    try:
        land("not_a_table", [{"symbol": "X"}], catalog=object())
    except RuntimeError as e:
        assert "#FMP.00000010.WAREHOUSE" in str(e)
    else:
        raise AssertionError("expected fail-closed")


def test_metabase_peer_prefers_project():
    rows = [
        {"project": "gaius", "engine_target": "127.0.0.1:50051", "primary_ui": "http://x:9119"},
        {"project": "metabase", "engine_target": "127.0.0.1:50451", "primary_ui": "http://x:3200"},
    ]
    peer = metabase_peer(rows)
    assert peer is not None and peer["project"] == "metabase"
    assert metabase_peer([rows[0]]) is None


def test_resolve_metabase_target_from_surfaces(monkeypatch):
    monkeypatch.delenv("METABASE_ENGINE_TARGET", raising=False)
    assert (
        resolve_metabase_target(
            surfaces=[
                {
                    "project": "metabase",
                    "engine_target": "10.0.0.1:50451",
                    "primary_ui": "http://x:3200",
                }
            ]
        )
        == "10.0.0.1:50451"
    )


def test_resolve_metabase_target_fail_closed(monkeypatch):
    monkeypatch.delenv("METABASE_ENGINE_TARGET", raising=False)
    with pytest.raises(RuntimeError, match="#SL.00000010.MBNOPEER"):
        resolve_metabase_target(
            surfaces=[
                {
                    "project": "gaius",
                    "engine_target": "127.0.0.1:50051",
                    "primary_ui": "http://x:9119",
                }
            ]
        )
