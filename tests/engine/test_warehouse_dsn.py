"""Warehouse DSN prefers Gaius Postgres FDW, not Signals :5455."""

import os

from gaius.engine.services.warehouse_ingest import warehouse_dsn


def test_default_dsn_is_gaius_postgres(monkeypatch) -> None:
    monkeypatch.delenv("GAIUS_WAREHOUSE_DSN", raising=False)
    monkeypatch.delenv("GAIUS_WAREHOUSE_USE_SIGNALS", raising=False)
    monkeypatch.setenv("PGPORT", "5444")
    dsn = warehouse_dsn()
    assert "5444" in dsn
    assert "zndx_gaius" in dsn
    assert "5455" not in dsn


def test_signals_fallback_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("GAIUS_WAREHOUSE_DSN", raising=False)
    monkeypatch.setenv("GAIUS_WAREHOUSE_USE_SIGNALS", "1")
    monkeypatch.delenv("SIGNALS_WAREHOUSE_DSN", raising=False)
    dsn = warehouse_dsn()
    assert "5455" in dsn
    assert "signals" in dsn
