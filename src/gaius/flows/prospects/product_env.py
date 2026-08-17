"""Env stamps so prospects can keep ``gaius.prospects.corpus`` unattended.

Platform Metaflow already owns RustFS keys. HX and History must use that
same plane — not devenv MinIO ``zndx-gaius`` / ``minioadmin``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

PRODUCT_ID = "gaius.prospects.corpus"
PRODUCT_BUCKET = "signals-dataproducts"
HX_PREFIX = "gaius/hx/"
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


def apply_product_env(env: dict[str, str]) -> dict[str, str]:
    """Mutate *env* so HX + History land on Signals RustFS."""
    root = signals_root(env)
    endpoint = rustfs_endpoint(env)
    parsed = urlparse(endpoint)
    host = parsed.netloc or parsed.path or "127.0.0.1:9010"
    env["SIGNALS_ROOT"] = str(root)
    env.setdefault(
        "SIGNALS_DATA_PRODUCT_HISTORY",
        str(root / "build" / "state" / "data-product-history.jsonl"),
    )
    env["GAIUS_HX_USE_MINIO"] = "true"
    env["GAIUS_MINIO_BUCKET"] = PRODUCT_BUCKET
    env["GAIUS_MINIO_ENDPOINT"] = host
    env.setdefault("GAIUS_MINIO_ACCESS_KEY", env.get("AWS_ACCESS_KEY_ID", ""))
    env.setdefault("GAIUS_MINIO_SECRET_KEY", env.get("AWS_SECRET_ACCESS_KEY", ""))
    return env


def is_platform_env(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    mode = (env.get("GAIUS_METAFLOW_MODE") or "").strip().lower()
    if mode == "platform":
        return True
    ds = (env.get("METAFLOW_DEFAULT_DATASTORE") or "").strip().lower()
    return ds == "s3" and "9010" in rustfs_endpoint(env)
