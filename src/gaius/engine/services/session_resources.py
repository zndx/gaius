"""Origin rustfs session materials for ServerQuery RESOURCES.

Bucket ``gaius``, keys ``resources/<zettel-id>/…``. Empty is honest.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("gaius.engine.session_resources")

BUCKET = os.environ.get("GAIUS_RESOURCES_S3_BUCKET", "gaius")
PREFIX = os.environ.get("GAIUS_RESOURCES_S3_PREFIX", "resources").strip("/")
RUSTFS_URL = os.environ.get("SIGNALS_RUSTFS_URL", "http://127.0.0.1:9010")


def _note_stem(note_id: str) -> str:
    rel = (note_id or "").replace("\\", "/").strip().lstrip("/")
    if not rel or any(p in ("..", "") for p in Path(rel).parts):
        return ""
    if rel.endswith(".md"):
        rel = rel[:-3]
    return rel


def list_session_materials(note_id: str) -> list[dict[str, Any]]:
    stem = _note_stem(note_id)
    if not stem:
        return []
    pref = f"{PREFIX}/{stem}" if PREFIX else stem
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=RUSTFS_URL,
            aws_access_key_id=os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin"),
            aws_secret_access_key=os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin"),
            config=Config(s3={"addressing_style": "path"}),
            region_name="us-east-1",
        )
        listed = client.list_objects_v2(Bucket=BUCKET, Prefix=pref.rstrip("/") + "/")
    except Exception:
        log.debug("resources list skipped note_id=%s", note_id, exc_info=True)
        return []
    objects: list[dict[str, Any]] = []
    for obj in listed.get("Contents") or []:
        key = str(obj.get("Key") or "")
        name = key.rsplit("/", 1)[-1]
        if not name or name.endswith("/"):
            continue
        try:
            got = client.get_object(Bucket=BUCKET, Key=key)
            raw = got["Body"].read()
            text = raw.decode("utf-8")
        except Exception:
            log.debug("resources get failed key=%s", key, exc_info=True)
            continue
        objects.append(
            {"name": name, "text": text, "uri": f"s3://{BUCKET}/{key}"}
        )
    objects.sort(key=lambda r: r["name"])
    return objects
