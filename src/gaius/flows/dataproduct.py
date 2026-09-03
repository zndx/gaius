"""Shared Signals data-product inventory helpers (peer side).

The signals-protocol data-product contract (``specification/protocol/data_products.md``)
is a warehouse contract: a peer owns product identity + object bytes; **Signals
owns** the ``tx`` / ``details`` / ``hx_reasoning`` inventory tables (Kudu tier0 +
Iceberg tier1) and mints the RFC 9562 UUIDv7 ``tx_id``. A peer records a run by
calling the Signals writer ``signals.ops.history.review`` — never by writing the
warehouse itself, and never Gaius PG ``:5444`` or pglite.

These helpers are product-agnostic; ``flows/prospects/publish.py`` (the first
product) inlined them, ``flows/article_curation/publish.py`` uses this module.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from gaius.engine.sentinel_claim import federation_required

log = logging.getLogger("gaius.flows.dataproduct")

GURU_NOPUBLISH = "#DP.00000001.NOPUBLISH"
GURU_NORUSTFS = "#DP.00000002.NORUSTFS"

# The Signals object plane. Product bytes MUST live here (peers are tenants).
ALLOWED_OBJECT_PREFIXES = ("s3://signals-dataproducts/", "s3a://signals-dataproducts/")


class DataProductError(RuntimeError):
    def __init__(self, code: str, product_id: str, detail: str) -> None:
        self.code = code
        super().__init__(
            f"{code} {detail}\n"
            "  Try: uv run python -m signals.ops review-product "
            f"{product_id} --kind updated\n"
            "  Or:  just signals-ready   # in $SIGNALS_ROOT\n"
            "  Do not write product rows to Gaius :5444 or pglite"
        )


def run_attr(flow: str, run_id: str, name: str) -> str:
    """Run-qualified attribute key: keeps every retained version visible on one
    product (latest-wins never erases prior runs)."""
    return f"run.{flow}/{run_id}.{name}"


def require_signals_object_plane(location: str, product_id: str) -> str:
    """Fail closed unless the product's bytes live on the Signals object plane."""
    loc = (location or "").strip()
    if not any(loc.startswith(p) for p in ALLOWED_OBJECT_PREFIXES):
        raise DataProductError(
            GURU_NORUSTFS,
            product_id,
            f"product location {loc!r} is not on Signals RustFS "
            f"(expected one of {ALLOWED_OBJECT_PREFIXES})",
        )
    return loc


def publish_required(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    raw = (env.get("GAIUS_REQUIRE_PRODUCT_PUBLISH") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return federation_required()


def signals_root(product_id: str, environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    root = Path(env.get("SIGNALS_ROOT") or str(Path.home() / "local/src/wxs/signals"))
    if not (root / "src" / "signals" / "ops" / "history.py").is_file():
        raise DataProductError(
            GURU_NOPUBLISH,
            product_id,
            f"SIGNALS_ROOT {root} has no signals.ops.history "
            "(need the Signals tree, not a Gaius-local writer)",
        )
    return root


def history_jsonl_path(product_id: str, environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    raw = (env.get("SIGNALS_DATA_PRODUCT_HISTORY") or "").strip()
    if raw:
        return Path(raw)
    return signals_root(product_id, env) / "build" / "state" / "data-product-history.jsonl"


def append_history_jsonl(
    product_id: str,
    agent: str,
    *,
    kind: str,
    summary: str,
    facts: dict[str, Any],
    environ: Mapping[str, str] | None = None,
    tx_id: str | None = None,
) -> dict[str, Any]:
    """Lab History reader (Signals UI); the warehouse (Impala) is the SoR."""
    path = history_jsonl_path(product_id, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    ev = {
        "ts": time.time(),
        "product_id": product_id,
        "kind": kind,
        "summary": summary,
        "agent": agent,
        "tx_id": tx_id or uuid4().hex,
        "pathspec": facts.get("pathspec") or "",
        "snapshot_uri": facts.get("snapshot_uri") or "",
        "data_uri": facts.get("data_uri") or "",
        "yk_app_id": facts.get("yk_app_id") or "",
        "yk_queue": facts.get("yk_queue") or "",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev) + "\n")
    ev["jsonl_path"] = str(path)
    return ev


def _signals_python(root: Path) -> list[str]:
    venv_py = root / ".devenv" / "state" / "venv" / "bin" / "python"
    if venv_py.is_file():
        return [str(venv_py)]
    return ["uv", "run", "--no-sync", "python"]


def _review_env(root: Path, environ: Mapping[str, str] | None) -> dict[str, str]:
    env = dict(environ if environ is not None else os.environ)
    env["DEVENV_ROOT"] = str(root)
    kdc = root / ".devenv" / "kdc"
    if (kdc / "krb5.conf").is_file():
        env.setdefault("KRB5_CONFIG", str(kdc / "krb5.conf"))
    if (kdc / "krb5cc").exists() or (kdc / "krb5.conf").is_file():
        env.setdefault("KRB5CCNAME", str(kdc / "krb5cc"))
    env.setdefault("IMPALA_HS2_HOST", "tinybox.dev.vista.zndx.org")
    return env


def review_via_signals(
    product_id: str,
    facts: dict[str, Any],
    *,
    kind: str,
    summary: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Record a run with the Signals writer (mints UUIDv7 tx; asserts details;
    writes hx_reasoning). Shells into $SIGNALS_ROOT so Gaius never vendors a
    second warehouse."""
    root = signals_root(product_id, environ)
    script = (
        "import json, sys\n"
        "from signals.ops.history import review\n"
        "payload = json.load(sys.stdin)\n"
        "ev, path = review(\n"
        "    payload['product_id'],\n"
        "    kind=payload['kind'],\n"
        "    summary=payload['summary'],\n"
        "    product=payload['product'],\n"
        "    source='gaius',\n"
        ")\n"
        "print(json.dumps({\n"
        "    'tx_id': ev.get('tx_id') or ev.get('event_id'),\n"
        "    'product_id': ev.get('product_id'),\n"
        "    'kind': ev.get('kind'),\n"
        "    'brief_path': str(path),\n"
        "    'assessment': ev.get('assessment'),\n"
        "}))\n"
    )
    payload = {"product_id": product_id, "kind": kind, "summary": summary, "product": facts}
    proc = subprocess.run(
        [*_signals_python(root), "-c", script],
        cwd=str(root),
        input=json.dumps(payload, default=str),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
        env=_review_env(root, environ),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "")[:800]
        raise DataProductError(
            GURU_NOPUBLISH,
            product_id,
            f"signals.ops.history.review failed (exit {proc.returncode}): {detail}",
        )
    lines = (proc.stdout or "").strip().splitlines()
    if not lines:
        raise DataProductError(GURU_NOPUBLISH, product_id, "signals.ops.history.review returned no JSON")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise DataProductError(
            GURU_NOPUBLISH,
            product_id,
            f"signals.ops.history.review stdout is not JSON: {lines[-1][:200]}",
        ) from e
