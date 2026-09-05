"""Env stamps so prospects can keep ``gaius.prospects.corpus`` unattended.

Platform Metaflow already owns RustFS keys. HX and History must use that
same plane — not devenv RustFS ``zndx-gaius`` / ``rustfsadmin``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

PRODUCT_ID = "gaius.prospects.corpus"
PRODUCT_BUCKET = "signals-dataproducts"
HX_PREFIX = "iceberg/"
PRODUCT_PREFIX = "gaius/prospects/"
DEFAULT_SIGNALS_ROOT = Path.home() / "local" / "src" / "wxs" / "signals"


def signals_root(environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    return Path(env.get("SIGNALS_ROOT") or str(DEFAULT_SIGNALS_ROOT))


def rustfs_endpoint(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    raw = (
        env.get("METAFLOW_S3_ENDPOINT_URL")
        or env.get("AWS_ENDPOINT_URL_S3")
        or "http://127.0.0.1:9010"
    )
    return raw.rstrip("/")


def rustfs_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """RustFS keys, read ONLY from the explicit RustFS variables.

    Never from ``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY``: an ambient default
    credential chain is what leaked the retired object store's admin key into
    every S3 client (the Nautilus journal, 2026-09-04). Order: the gaius
    ``GAIUS_RUSTFS_*`` pair, then Signals' ``RUSTFS_*`` pair, then the RustFS
    default.
    """
    env = environ if environ is not None else os.environ
    ak = (env.get("GAIUS_RUSTFS_ACCESS_KEY") or env.get("RUSTFS_ACCESS_KEY") or "").strip()
    sk = (env.get("GAIUS_RUSTFS_SECRET_KEY") or env.get("RUSTFS_SECRET_KEY") or "").strip()
    return ak or "rustfsadmin", sk or "rustfsadmin"


def apply_product_env(env: dict[str, str]) -> dict[str, str]:
    """Mutate *env* so HX + History land on Signals RustFS."""
    root = signals_root(env)
    endpoint = rustfs_endpoint(env)
    parsed = urlparse(endpoint)
    host = parsed.netloc or parsed.path or "127.0.0.1:9010"
    ak, sk = rustfs_credentials(env)
    env["SIGNALS_ROOT"] = str(root)
    env.setdefault(
        "SIGNALS_DATA_PRODUCT_HISTORY",
        str(root / "build" / "state" / "data-product-history.jsonl"),
    )
    env["GAIUS_HX_USE_RUSTFS"] = "true"
    env["GAIUS_RUSTFS_BUCKET"] = PRODUCT_BUCKET
    env["GAIUS_RUSTFS_ENDPOINT"] = host
    env["GAIUS_RUSTFS_ACCESS_KEY"] = ak
    env["GAIUS_RUSTFS_SECRET_KEY"] = sk
    env["GAIUS_HX_PREFIX"] = HX_PREFIX
    return env


def is_platform_env(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    mode = (env.get("GAIUS_METAFLOW_MODE") or "").strip().lower()
    if mode == "platform":
        return True
    ds = (env.get("METAFLOW_DEFAULT_DATASTORE") or "").strip().lower()
    return ds == "s3" and "9010" in rustfs_endpoint(env)
