"""Publish a ProspectsUpdateFlow run as Signals product ``gaius.prospects.corpus``.

Gaius owns identity and facts. Signals owns ``details`` / ``tx`` / ``hx``
on RustFS. This module never writes Gaius PG ``:5444`` or pglite.

When Signals is on the lattice, ``end`` must record a UUIDv7 ``tx`` via
``signals.ops.history.review`` (Signals writer). Standalone devenv skips.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from gaius.engine.sentinel_claim import EXTRACT, federation_required

log = logging.getLogger("gaius.flows.prospects.publish")

PRODUCT_ID = "gaius.prospects.corpus"
GURU_NOPUBLISH = "#DP.00000001.NOPUBLISH"
GURU_NORUSTFS = "#DP.00000002.NORUSTFS"

ALLOWED_ROOT_PREFIXES = ("s3://metaflow/", "s3://signals-dataproducts/")
RUSTFS_PORT = "9010"

CATALOG: dict[str, str] = {
    "id": PRODUCT_ID,
    "peer": "gaius",
    "title": "Prospects corpus",
    "kind": "corpus",
    "leaf": EXTRACT.queue,
    "agent_focus": (
        "Quality of retained SEC/FMP compact and summary objects on RustFS; "
        "lineage of Metaflow pathspec, code sha, and YK extract claim; "
        "delta vs prior latest_run_id; nominal walk of prospects-update "
        "(holding is not failed and not done)."
    ),
}

ReviewFn = Callable[[dict[str, Any], str, str], dict[str, Any]]


class ProspectsPublishError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(
            f"{code} {detail}\n"
            "  Try: uv run python -m signals.ops review-product "
            f"{PRODUCT_ID} --kind updated --summary 'prospects-update'\n"
            "  Or:  just signals-ready   # in $SIGNALS_ROOT\n"
            "  Do not write product rows to Gaius :5444 or pglite"
        )


def signals_root(environ: dict[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    root = Path(
        env.get("SIGNALS_ROOT") or str(Path.home() / "local/src/wxs/signals")
    )
    if not (root / "src" / "signals" / "ops" / "history.py").is_file():
        raise ProspectsPublishError(
            GURU_NOPUBLISH,
            f"SIGNALS_ROOT {root} has no signals.ops.history "
            "(need the Signals tree, not a Gaius-local writer)",
        )
    return root


def require_rustfs(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Fail closed if this run would claim a non-RustFS object plane."""
    env = environ if environ is not None else os.environ
    ds = (env.get("METAFLOW_DEFAULT_DATASTORE") or "").strip().lower()
    if ds in {"", "local"}:
        raise ProspectsPublishError(
            GURU_NORUSTFS,
            "Metaflow datastore is local or unset — product objects "
            "MUST land on Signals RustFS (s3)",
        )
    if ds != "s3":
        raise ProspectsPublishError(
            GURU_NORUSTFS,
            f"Metaflow datastore {ds!r} is not s3/RustFS",
        )
    root = (env.get("METAFLOW_DATASTORE_SYSROOT_S3") or "").strip()
    if not any(root.startswith(p) for p in ALLOWED_ROOT_PREFIXES):
        raise ProspectsPublishError(
            GURU_NORUSTFS,
            f"METAFLOW_DATASTORE_SYSROOT_S3 {root!r} is not a Signals RustFS bucket",
        )
    endpoint = (
        env.get("METAFLOW_S3_ENDPOINT_URL")
        or env.get("AWS_ENDPOINT_URL_S3")
        or ""
    )
    if RUSTFS_PORT not in endpoint and "rustfs" not in endpoint.lower():
        raise ProspectsPublishError(
            GURU_NORUSTFS,
            f"S3 endpoint {endpoint!r} is not RustFS (:{RUSTFS_PORT})",
        )
    return {
        "datastore": "s3",
        "datastore_root": root,
        "rustfs_endpoint": endpoint,
        "object_store": "rustfs",
    }


def run_attr(flow: str, run_id: str, name: str) -> str:
    return f"run.{flow}/{run_id}.{name}"


def product_facts(
    run: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Map one ProspectsUpdateFlow execution onto Signals details facts."""
    store = require_rustfs(environ)
    flow = str(run.get("flow_name") or "").strip()
    run_id = str(run.get("run_id") or "").strip()
    if not flow or not run_id:
        raise ProspectsPublishError(
            GURU_NOPUBLISH,
            "product facts need flow_name and run_id (Metaflow current)",
        )
    sysroot = store["datastore_root"].rstrip("/")
    snap = str(run.get("snapshot_uri") or f"{sysroot}/{flow}/{run_id}")
    data_uri = str(
        run.get("data_uri")
        or f"s3://signals-dataproducts/gaius/prospects/{run_id}"
    )
    pathspec = str(run.get("pathspec") or f"{flow}/{run_id}")
    yk_app = str(run.get("yk_app_id") or "")
    yk_queue = str(run.get("yk_queue") or EXTRACT.queue)
    symbols = str(run.get("symbols") or "")
    row = dict(CATALOG)
    row.update(store)
    row.update(
        {
            "flow_name": flow,
            "run_id": run_id,
            "pathspec": pathspec,
            "data_uri": data_uri,
            "snapshot_uri": snap,
            "code_package": str(run.get("code_package") or ""),
            "code_package_sha": str(run.get("code_package_sha") or ""),
            "deps": str(run.get("deps") or ""),
            "yk_app_id": yk_app,
            "yk_queue": yk_queue,
            "latest_flow_name": flow,
            "latest_run_id": run_id,
            "latest_snapshot_uri": snap,
            "symbols": symbols,
            "profile": str(run.get("profile") or ""),
            "domain": str(run.get("domain") or ""),
            "assessment": "nominal",
            "assessment_agent": "gaius-prospects",
            "upkeep_nominal": "n/a",
            "quality": f"prospects objects on {store['object_store']} {data_uri}",
            "lineage": f"{pathspec} yk={yk_app or '—'} queue={yk_queue}",
            "delta": f"run {run_id}" + (f" symbols={symbols}" if symbols else ""),
        }
    )
    for name, val in (
        ("snapshot_uri", snap),
        ("data_uri", data_uri),
        ("yk_app_id", yk_app),
        ("yk_queue", yk_queue),
        ("assessment", "nominal"),
    ):
        if val:
            row[run_attr(flow, run_id, name)] = val
    return row


def flow_run_record(flow: Any) -> dict[str, Any]:
    """Pull Metaflow identity + YK stamps off a live FlowSpec."""
    flow_name = ""
    run_id = ""
    pathspec = ""
    try:
        from metaflow import current

        flow_name = str(getattr(current, "flow_name", "") or "")
        run_id = str(getattr(current, "run_id", "") or "")
        pathspec = str(getattr(current, "pathspec", "") or "")
    except Exception:
        log.debug("metaflow.current unavailable for product facts", exc_info=True)
    if not flow_name:
        flow_name = type(flow).__name__
    symbols = getattr(flow, "symbol_list", None) or []
    return {
        "flow_name": flow_name,
        "run_id": run_id,
        "pathspec": pathspec,
        "yk_app_id": os.environ.get("GAIUS_YK_APPLICATION_ID", ""),
        "yk_queue": EXTRACT.queue,
        "symbols": ",".join(str(s) for s in symbols),
        "profile": str(getattr(flow, "_resolved_profile", "") or ""),
        "domain": str(getattr(flow, "_resolved_domain", "") or ""),
    }


def publish_required(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    raw = (env.get("GAIUS_REQUIRE_PRODUCT_PUBLISH") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return federation_required()


def history_jsonl_path(environ: dict[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    raw = (env.get("SIGNALS_DATA_PRODUCT_HISTORY") or "").strip()
    if raw:
        return Path(raw)
    return signals_root(env) / "build" / "state" / "data-product-history.jsonl"


def append_history_jsonl(
    *,
    kind: str,
    summary: str,
    facts: dict[str, Any],
    environ: dict[str, str] | None = None,
    tx_id: str | None = None,
) -> dict[str, Any]:
    """Lab History reader: Signals UI loads this JSONL (warehouse is Impala)."""
    path = history_jsonl_path(environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    ev = {
        "ts": time.time(),
        "product_id": PRODUCT_ID,
        "kind": kind,
        "summary": summary,
        "agent": "gaius-prospects",
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


def _review_env(root: Path, environ: dict[str, str] | None) -> dict[str, str]:
    env = dict(environ if environ is not None else os.environ)
    env["DEVENV_ROOT"] = str(root)
    kdc = root / ".devenv" / "kdc"
    if (kdc / "krb5.conf").is_file():
        env.setdefault("KRB5_CONFIG", str(kdc / "krb5.conf"))
    if (kdc / "krb5cc").exists() or (kdc / "krb5.conf").is_file():
        env.setdefault("KRB5CCNAME", str(kdc / "krb5cc"))
    env.setdefault("IMPALA_HS2_HOST", "tinybox.dev.vista.zndx.org")
    return env


def _review_via_signals(
    product: dict[str, Any],
    *,
    kind: str,
    summary: str,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = signals_root(environ)
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
    payload = {
        "product_id": PRODUCT_ID,
        "kind": kind,
        "summary": summary,
        "product": product,
    }
    proc = subprocess.run(
        [*_signals_python(root), "-c", script],
        cwd=str(root),
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
        env=_review_env(root, environ),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "")[:800]
        raise ProspectsPublishError(
            GURU_NOPUBLISH,
            f"signals.ops.history.review failed (exit {proc.returncode}): {detail}",
        )
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        raise ProspectsPublishError(
            GURU_NOPUBLISH,
            "signals.ops.history.review returned no JSON",
        )
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError as e:
        raise ProspectsPublishError(
            GURU_NOPUBLISH,
            f"signals.ops.history.review stdout is not JSON: {line[-1][:200]}",
        ) from e


def publish_run(
    run: dict[str, Any],
    *,
    kind: str = "updated",
    summary: str = "",
    environ: dict[str, str] | None = None,
    review: ReviewFn | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    """Record ``gaius.prospects.corpus`` for this run.

    ``review`` is injectable for tests. Live path shells into ``$SIGNALS_ROOT``
    so Gaius does not vendor a second warehouse.
    """
    env = environ if environ is not None else os.environ
    must = publish_required(env) if required is None else required
    if review is None and not must:
        log.info("skip product publish (Signals warehouse not required)")
        return {"skipped": True, "product_id": PRODUCT_ID}
    facts = product_facts(run, environ=env)
    text = summary or (
        f"{facts['flow_name']}/{facts['run_id']} retained {facts['data_uri']}"
    )
    if review is not None:
        return review(facts, kind, text)
    jsonl = append_history_jsonl(
        kind=kind, summary=text, facts=facts, environ=env
    )
    try:
        recorded = _review_via_signals(facts, kind=kind, summary=text, environ=env)
    except ProspectsPublishError as e:
        log.warning("warehouse review failed; History JSONL recorded: %s", e)
        jsonl["warehouse_error"] = str(e).split("\n", 1)[0]
        jsonl["product_id"] = PRODUCT_ID
        jsonl["facts"] = facts
        return jsonl
    recorded["product_id"] = PRODUCT_ID
    recorded["facts"] = facts
    recorded["jsonl_path"] = jsonl.get("jsonl_path")
    return recorded


def latest_snapshot_uri(environ: dict[str, str] | None = None) -> str | None:
    """Best-effort current ProspectsUpdateFlow snapshot on platform Metaflow."""
    env = environ if environ is not None else os.environ
    base = (env.get("METAFLOW_SERVICE_URL") or "http://127.0.0.1:30180").rstrip("/")
    try:
        from urllib.request import urlopen

        with urlopen(f"{base}/flows/ProspectsUpdateFlow/runs", timeout=5) as resp:
            runs = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(runs, list) or not runs:
        return None
    first = runs[0] if isinstance(runs[0], dict) else {}
    run_id = first.get("run_number") or first.get("run_id")
    if not run_id:
        return None
    root = (env.get("METAFLOW_DATASTORE_SYSROOT_S3") or "s3://metaflow/metaflow").rstrip("/")
    return f"{root}/ProspectsUpdateFlow/{run_id}"


def record_availability(
    *,
    environ: dict[str, str] | None = None,
    reason: str = "no new filings",
) -> dict[str, Any]:
    """Heartbeat: product stays current without a GPU update.

    If no snapshot exists, ``needs_update`` is True so the clock can force
    a watchlist run. Does not invent warehouse rows.
    """
    env = environ if environ is not None else os.environ
    snap = latest_snapshot_uri(env)
    if not snap:
        return {
            "product_id": PRODUCT_ID,
            "needs_update": True,
            "reason": "no ProspectsUpdateFlow snapshot on platform Metaflow",
        }
    run = {
        "flow_name": "ProspectsUpdateFlow",
        "run_id": snap.rsplit("/", 1)[-1],
        "snapshot_uri": snap,
        "pathspec": f"ProspectsUpdateFlow/{snap.rsplit('/', 1)[-1]}",
        "yk_app_id": env.get("GAIUS_YK_APPLICATION_ID", ""),
        "yk_queue": EXTRACT.queue,
    }
    try:
        facts = product_facts(run, environ=env)
    except ProspectsPublishError:
        facts = {
            "pathspec": run["pathspec"],
            "snapshot_uri": snap,
            "data_uri": f"s3://signals-dataproducts/gaius/prospects/{run['run_id']}",
            "yk_app_id": run["yk_app_id"],
            "yk_queue": run["yk_queue"],
        }
    ev = append_history_jsonl(
        kind="maintained",
        summary=f"{reason}; latest {snap} still current",
        facts=facts,
        environ=env,
    )
    ev["needs_update"] = False
    ev["product_id"] = PRODUCT_ID
    ev["snapshot_uri"] = snap
    return ev


def publish_from_flow(
    flow: Any,
    *,
    environ: dict[str, str] | None = None,
    review: ReviewFn | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    return publish_run(
        flow_run_record(flow),
        environ=environ,
        review=review,
        required=required,
    )
