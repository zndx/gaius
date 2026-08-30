"""Publish an ArticleCurationFlow run as Signals product ``gaius.curation.cot_reasoning``.

The product is the accumulating chain-of-thought corpus the curation flow refines:
every ``select_article`` run's ``cot_reflection`` trace, retained in the HX
Iceberg table ``hx.cot_reasoning`` (Signals Polaris catalog, RustFS object plane)
with its flow/step/subject context. Gaius owns identity, the bytes, and the
Metaflow flow; Signals owns ``details`` / ``tx`` / ``hx_reasoning``.

Per the contract, history is kept with run-qualified facts
(``run.{flow}/{run_id}.*``) on top of the Iceberg table's own snapshot history, so
a federated engine can surface the complete product — every article, every run —
from the Signals warehouse alone.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

from gaius.engine.sentinel_claim import EXTRACT
from gaius.flows.dataproduct import (
    DataProductError,
    append_history_jsonl,
    publish_required,
    require_signals_object_plane,
    review_via_signals,
    run_attr,
)
from gaius.hx.cot_reasoning import CURATION_PRODUCT_ID, TABLE_IDENTIFIER

log = logging.getLogger("gaius.flows.article_curation.publish")

PRODUCT_ID = CURATION_PRODUCT_ID
AGENT = "gaius-curation"
STEP_NAME = "select_article"

CATALOG: dict[str, str] = {
    "id": PRODUCT_ID,
    "peer": "gaius",
    "title": "Article curation chain-of-thought reasoning",
    "kind": "reasoning",
    "leaf": EXTRACT.queue,
    "agent_focus": (
        "Quality and depth of retained cot_reflection traces for select_article "
        f"({TABLE_IDENTIFIER} on RustFS, one row per run); lineage of Metaflow "
        "pathspec, optillm technique, model, and YK extract claim; delta vs the "
        "prior run's decision; nominal walk of article-curate (reasoning that "
        "completes and lands is nominal — long generations are the product)."
    ),
}

ReviewFn = Callable[[dict[str, Any], str, str], dict[str, Any]]


def product_facts(run: dict[str, Any]) -> dict[str, Any]:
    """Map one ArticleCurationFlow run (+ its retained CotRecord) onto details facts."""
    flow = str(run.get("flow_name") or "").strip()
    run_id = str(run.get("run_id") or "").strip()
    if not flow or not run_id:
        raise DataProductError(
            "#DP.00000001.NOPUBLISH", PRODUCT_ID, "product facts need flow_name and run_id (Metaflow current)"
        )
    location = require_signals_object_plane(str(run.get("table_location") or ""), PRODUCT_ID)
    pathspec = str(run.get("pathspec") or f"{flow}/{run_id}")
    subject = str(run.get("subject") or "")
    record_id = str(run.get("record_id") or "")
    snapshot_id = str(run.get("snapshot_id") or "")
    yk_app = str(run.get("yk_app_id") or "")
    yk_queue = str(run.get("yk_queue") or EXTRACT.queue)
    technique = str(run.get("technique") or "")
    model = str(run.get("model_name") or "")
    out_tokens = int(run.get("output_tokens") or 0)
    row = dict(CATALOG)
    row.update(
        {
            "flow_name": flow,
            "run_id": run_id,
            "pathspec": pathspec,
            "step_name": STEP_NAME,
            "subject": subject,
            "table_identifier": TABLE_IDENTIFIER,
            "data_uri": location,
            "snapshot_uri": f"{location}#snapshot={snapshot_id}" if snapshot_id else location,
            "record_id": record_id,
            "iceberg_snapshot_id": snapshot_id,
            "technique": technique,
            "model_name": model,
            "output_tokens": str(out_tokens),
            "object_store": "rustfs",
            "yk_app_id": yk_app,
            "yk_queue": yk_queue,
            "latest_flow_name": flow,
            "latest_run_id": run_id,
            "latest_subject": subject,
            "latest_record_id": record_id,
            "assessment": "nominal",
            "assessment_agent": AGENT,
            "upkeep_nominal": "n/a",
            "quality": (
                f"{technique} trace ({out_tokens} tokens, {model}) retained in "
                f"{TABLE_IDENTIFIER} id={record_id}"
            ),
            "lineage": f"{pathspec} yk={yk_app or '—'} queue={yk_queue} snapshot={snapshot_id or '—'}",
            "delta": f"run {run_id} decided {subject or '—'}",
        }
    )
    for name, val in (
        ("subject", subject),
        ("record_id", record_id),
        ("iceberg_snapshot_id", snapshot_id),
        ("data_uri", location),
        ("yk_app_id", yk_app),
        ("yk_queue", yk_queue),
        ("technique", technique),
        ("assessment", "nominal"),
    ):
        if val:
            row[run_attr(flow, run_id, name)] = val
    return row


def flow_run_record(flow: Any) -> dict[str, Any]:
    """Pull Metaflow identity, YK stamps, and the retained CotRecord off a live flow."""
    flow_name, run_id, pathspec = "", "", ""
    try:
        from metaflow import current

        flow_name = str(getattr(current, "flow_name", "") or "")
        run_id = str(getattr(current, "run_id", "") or "")
        pathspec = str(getattr(current, "pathspec", "") or "")
    except Exception:
        log.debug("metaflow.current unavailable for product facts", exc_info=True)
    if not flow_name:
        flow_name = type(flow).__name__
    cot = getattr(flow, "cot_record", None) or {}
    trace = getattr(flow, "selection_trace", None) or {}
    return {
        "flow_name": flow_name,
        "run_id": run_id,
        "pathspec": pathspec,
        "subject": str(getattr(flow, "selected_slug", "") or ""),
        "record_id": cot.get("id", ""),
        "snapshot_id": cot.get("snapshot_id", ""),
        "table_location": cot.get("location", ""),
        "technique": str(trace.get("technique") or ""),
        "model_name": str(trace.get("model") or ""),
        "output_tokens": trace.get("output_tokens") or 0,
        "yk_app_id": os.environ.get("GAIUS_YK_APPLICATION_ID", ""),
        "yk_queue": EXTRACT.queue,
    }


def publish_run(
    run: dict[str, Any],
    *,
    kind: str = "updated",
    summary: str = "",
    environ: dict[str, str] | None = None,
    review: ReviewFn | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    """Record ``gaius.curation.cot_reasoning`` for this run with the Signals writer."""
    env = environ if environ is not None else os.environ
    must = publish_required(env) if required is None else required
    if review is None and not must:
        log.info("skip product publish (Signals warehouse not required)")
        return {"skipped": True, "product_id": PRODUCT_ID}
    facts = product_facts(run)
    text = summary or (
        f"{facts['flow_name']}/{facts['run_id']} {facts['technique'] or 'reasoning'} "
        f"→ {facts['subject'] or '—'} retained {TABLE_IDENTIFIER} id={facts['record_id']}"
    )
    if review is not None:
        return review(facts, kind, text)
    jsonl = append_history_jsonl(PRODUCT_ID, AGENT, kind=kind, summary=text, facts=facts, environ=env)
    try:
        recorded = review_via_signals(PRODUCT_ID, facts, kind=kind, summary=text, environ=env)
    except DataProductError as e:
        log.warning("warehouse review failed; History JSONL recorded: %s", e)
        jsonl["warehouse_error"] = str(e).split("\n", 1)[0]
        jsonl["product_id"] = PRODUCT_ID
        jsonl["facts"] = facts
        return jsonl
    recorded["product_id"] = PRODUCT_ID
    recorded["facts"] = facts
    recorded["jsonl_path"] = jsonl.get("jsonl_path")
    return recorded


def publish_from_flow(
    flow: Any,
    *,
    environ: dict[str, str] | None = None,
    review: ReviewFn | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    return publish_run(flow_run_record(flow), environ=environ, review=review, required=required)
