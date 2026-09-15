"""Typed FMP warehouse flatten + Metabase peer pick."""
from __future__ import annotations

from gaius.engine.services.fmp_warehouse import metabase_peer
from gaius.hx.fmp_warehouse import COLUMN_IRIS, flatten_filings, flatten_profile, land


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


def test_scratch_iris_are_sdg_shaped():
    for cols in COLUMN_IRIS.values():
        for iri in cols.values():
            assert iri.startswith("https://signals.zndx.org/sdg#")


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
