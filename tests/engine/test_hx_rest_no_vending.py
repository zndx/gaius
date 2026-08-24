"""Polarisfork does not vend S3 STS; HX must not request vended-credentials."""

from gaius.hx.catalog import _get_s3_properties
from gaius.hx.config import HxConfig


def test_rest_catalog_opts_out_of_credential_vending() -> None:
    import inspect
    from gaius.hx import catalog as hx_catalog

    src = inspect.getsource(hx_catalog._create_rest_catalog)
    assert "header.X-Iceberg-Access-Delegation" in src
    assert "vended-credentials" not in src.split("header.X-Iceberg-Access-Delegation")[1][:80]


def test_s3_properties_have_rustfs_keys() -> None:
    cfg = HxConfig(
        catalog_name="signals",
        minio_endpoint="127.0.0.1:9010",
        minio_access_key="",
        minio_secret_key="",
    )
    props = _get_s3_properties(cfg)
    assert props["s3.access-key-id"]
    assert props["s3.secret-access-key"]
    assert props["s3.path-style-access"] == "true"
