"""Gaius HX catalog is Polarisfork REST, not Postgres SQL."""

from gaius.hx.catalog import CatalogType, GURU_NOPOLARIS, get_catalog
from gaius.hx.config import HxConfig


def test_default_catalog_type_is_rest() -> None:
    cfg = HxConfig()
    assert cfg.catalog_type == "rest"
    assert cfg.catalog_name == "signals"
    assert cfg.polaris_uri.endswith("/api/catalog")
    assert cfg.warehouse_path == "s3://signals-dataproducts/iceberg"


def test_get_catalog_rest_fail_fast(monkeypatch) -> None:
    from gaius.hx import catalog as cat

    cat.reset_catalog()

    def boom(*_a, **_k):
        raise ConnectionError("refused")

    monkeypatch.setattr("pyiceberg.catalog.load_catalog", boom)
    cfg = HxConfig(catalog_type="rest", polaris_uri="http://127.0.0.1:8181/api/catalog")
    try:
        get_catalog(cfg, catalog_type=CatalogType.REST, force_reload=True)
        raise AssertionError("expected NOPOLARIS")
    except RuntimeError as e:
        assert GURU_NOPOLARIS in str(e)
        assert "signals-polaris.service" in str(e)
    finally:
        cat.reset_catalog()
