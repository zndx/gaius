"""Prospects → Signals Data Product facts (no warehouse write)."""

from __future__ import annotations

import os

import pytest

from gaius.engine.sentinel_claim import EXTRACT
from gaius.flows.prospects.publish import (
    CATALOG,
    GURU_NOPUBLISH,
    GURU_NORUSTFS,
    PRODUCT_ID,
    ProspectsPublishError,
    product_facts,
    publish_run,
    require_rustfs,
)


PLATFORM_ENV = {
    "METAFLOW_DEFAULT_DATASTORE": "s3",
    "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow/metaflow",
    "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9010",
}


def test_format_market_row_keeps_symbol_and_body() -> None:
    # (2026-09-04) The formatter moved with the FMP roll to the flow that owns
    # the pull: gaius.flows.prospects.market_feed.format_market_row.
    from gaius.flows.prospects.market_feed import format_market_row as _format_market_row

    text = _format_market_row(
        "8-K",
        {
            "symbol": "CHTR",
            "formType": "8-K",
            "filingDate": "2026-08-15",
            "title": "Charter item",
            "finalLink": "https://sec.gov/x",
        },
    )
    assert "CHTR" in text
    assert "8-K" in text
    assert "sec.gov" in text


def test_product_env_stamps_rustfs_hx() -> None:
    from gaius.flows.prospects.product_env import apply_product_env, PRODUCT_BUCKET

    env = apply_product_env(
        {
            "AWS_ACCESS_KEY_ID": "k",
            "AWS_SECRET_ACCESS_KEY": "s",
            "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9010",
            "SIGNALS_ROOT": "/tmp/signals-root",
        }
    )
    assert env["GAIUS_RUSTFS_BUCKET"] == PRODUCT_BUCKET
    assert env["GAIUS_RUSTFS_ENDPOINT"] == "127.0.0.1:9010"
    assert env["GAIUS_RUSTFS_ACCESS_KEY"] == "rustfsadmin"
    assert env["GAIUS_HX_USE_RUSTFS"] == "true"
    assert env["SIGNALS_DATA_PRODUCT_HISTORY"].endswith(
        "data-product-history.jsonl"
    )


def test_engine_apply_metaflow_stamps_rustfs(monkeypatch: pytest.MonkeyPatch) -> None:
    """HX is Signals RustFS; devenv RustFS is not a warehouse."""
    monkeypatch.setenv("GAIUS_RUSTFS_ENDPOINT", "localhost:9014")
    monkeypatch.setenv("GAIUS_RUSTFS_BUCKET", "zndx-gaius")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "rustfsadmin")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "rustfsadmin")
    monkeypatch.setenv("GAIUS_METAFLOW_MODE", "local")
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config(mode="local")
    assert "9010" in os.environ["GAIUS_RUSTFS_ENDPOINT"]
    assert os.environ["GAIUS_RUSTFS_BUCKET"] == "signals-dataproducts"
    assert os.environ["GAIUS_RUSTFS_ACCESS_KEY"] == "rustfsadmin"
    assert os.environ["GAIUS_HX_PREFIX"] == "iceberg/"


def test_hx_platform_refuses_filesystem_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from gaius.hx.config import HxConfig
    from gaius.hx.storage import get_storage_config

    monkeypatch.setenv("GAIUS_METAFLOW_MODE", "platform")
    monkeypatch.setattr(
        "gaius.hx.storage._check_rustfs_available",
        lambda _cfg: False,
    )
    with pytest.raises(RuntimeError, match="#HX.00000001.NORUSTFS"):
        get_storage_config(HxConfig(), check_rustfs=True)


def test_record_availability_needs_update_without_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.flows.prospects import publish as pub

    monkeypatch.setattr(pub, "latest_snapshot_uri", lambda environ=None: None)
    out = pub.record_availability(environ=PLATFORM_ENV, reason="test")
    assert out["needs_update"] is True
    assert out["product_id"] == PRODUCT_ID


def test_catalog_id_is_gaius_prospects_corpus() -> None:
    assert PRODUCT_ID == "gaius.prospects.corpus"
    assert CATALOG["peer"] == "gaius"
    assert CATALOG["kind"] == "corpus"
    assert CATALOG["leaf"] == EXTRACT.queue
    assert "root.gaius" not in CATALOG["leaf"]


def test_require_rustfs_rejects_local() -> None:
    with pytest.raises(ProspectsPublishError, match=GURU_NORUSTFS):
        require_rustfs({"METAFLOW_DEFAULT_DATASTORE": "local"})
    with pytest.raises(ProspectsPublishError, match=GURU_NORUSTFS):
        require_rustfs({})
    with pytest.raises(ProspectsPublishError, match=GURU_NORUSTFS):
        require_rustfs(
            {
                "METAFLOW_DEFAULT_DATASTORE": "s3",
                "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow-artifacts/x",
                "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
            }
        )


def test_product_facts_map_run_and_yk() -> None:
    row = product_facts(
        {
            "flow_name": "ProspectsUpdateFlow",
            "run_id": "42",
            "pathspec": "ProspectsUpdateFlow/42",
            "yk_app_id": "article-curate-1786767299",
            "yk_queue": EXTRACT.queue,
            "symbols": "MTN,AAPL",
        },
        environ=PLATFORM_ENV,
    )
    assert row["id"] == PRODUCT_ID
    assert row["object_store"] == "rustfs"
    assert row["snapshot_uri"] == "s3://metaflow/metaflow/ProspectsUpdateFlow/42"
    assert row["data_uri"] == "s3://signals-dataproducts/gaius/prospects/42"
    assert row["yk_app_id"] == "article-curate-1786767299"
    assert row["yk_queue"] == "root.internal.inference.extract"
    assert row["run.ProspectsUpdateFlow/42.yk_queue"] == EXTRACT.queue
    assert row["assessment"] == "nominal"
    assert "MTN" in row["delta"]


def test_product_facts_need_run_identity() -> None:
    with pytest.raises(ProspectsPublishError, match=GURU_NOPUBLISH):
        product_facts({"flow_name": "ProspectsUpdateFlow"}, environ=PLATFORM_ENV)


def test_publish_run_uses_injected_review() -> None:
    seen: list[tuple[str, str]] = []

    def review(product: dict, kind: str, summary: str) -> dict:
        seen.append((kind, summary))
        assert product["id"] == PRODUCT_ID
        return {"tx_id": "injected", "product_id": PRODUCT_ID}

    out = publish_run(
        {
            "flow_name": "ProspectsUpdateFlow",
            "run_id": "7",
        },
        environ=PLATFORM_ENV,
        review=review,
        required=True,
    )
    assert out["tx_id"] == "injected"
    assert seen[0][0] == "updated"
    assert "ProspectsUpdateFlow/7" in seen[0][1]


def test_append_history_jsonl(tmp_path) -> None:
    from gaius.flows.prospects.publish import append_history_jsonl

    path = tmp_path / "data-product-history.jsonl"
    ev = append_history_jsonl(
        kind="updated",
        summary="ProspectsUpdateFlow/26 retained s3://signals-dataproducts/gaius/prospects/26",
        facts={
            "pathspec": "ProspectsUpdateFlow/26",
            "snapshot_uri": "s3://metaflow/metaflow/ProspectsUpdateFlow/26",
            "data_uri": "s3://signals-dataproducts/gaius/prospects/26",
            "yk_app_id": "article-curate-1786767299",
            "yk_queue": EXTRACT.queue,
        },
        environ={"SIGNALS_DATA_PRODUCT_HISTORY": str(path)},
    )
    assert ev["product_id"] == PRODUCT_ID
    assert path.is_file()
    line = path.read_text(encoding="utf-8").strip()
    assert "gaius.prospects.corpus" in line
    assert "ProspectsUpdateFlow/26" in line


def test_publish_run_skips_when_not_required() -> None:
    out = publish_run(
        {"flow_name": "ProspectsUpdateFlow", "run_id": "8"},
        environ=PLATFORM_ENV,
        required=False,
    )
    assert out["skipped"] is True
    assert out["product_id"] == PRODUCT_ID
    assert "facts" not in out
