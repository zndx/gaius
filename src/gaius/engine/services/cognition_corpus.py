"""Cognition corpus surface — reads ``hx.cot_reasoning`` (PyIceberg).

Reasoning traces are the product (deep CoT+reflection retained per flow
run). This module surfaces that corpus on the Cognition page: a light
list scan (no prompt/trace bodies) and a full single-trace fetch with the
tagged dual-constraint ``reasoning_layers``.

Sync PyIceberg — callers on the event loop wrap in ``asyncio.to_thread``.

Gurus:
  #HX.00000004.CORPUSREAD — corpus scan failed
  #HX.00000005.NOTRACE    — trace id not found
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

GURU_CORPUSREAD = "#HX.00000004.CORPUSREAD"
GURU_NOTRACE = "#HX.00000005.NOTRACE"

# Light fields for the list view — NO prompt/raw_response/output bodies.
# flow_name and generated_at are partition sources and MUST be selected
# (PyIceberg raises "Could not find field with id" otherwise).
# reasoning_layers IS selected: parsing it yields the layer badges.
_LIST_FIELDS = (
    "id",
    "product_id",
    "flow_name",
    "step_name",
    "run_id",
    "subject",
    "technique",
    "model_name",
    "decision",
    "confidence",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "generated_at",
    "reasoning_layers",
)

_MAX_LIMIT = 200


def _table():
    from gaius.hx.catalog import get_catalog
    from gaius.hx.cot_reasoning import get_cot_reasoning_table

    return get_cot_reasoning_table(get_catalog())


def _parse_layers(raw: str | None) -> list[dict]:
    """Tolerant parse of the reasoning_layers JSON column."""
    if not raw:
        return []
    try:
        layers = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(layers, list):
        return []
    out = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        out.append(
            {
                "layer": str(layer.get("layer") or ""),
                "producer": str(layer.get("producer") or ""),
                "tokens": int(layer.get("tokens") or 0),
                "text": str(layer.get("text") or ""),
            }
        )
    return out


def _row_item(row: dict) -> dict:
    gen = row.get("generated_at")
    layers = _parse_layers(row.get("reasoning_layers"))
    return {
        "id": row.get("id") or "",
        "product_id": row.get("product_id") or "",
        "flow_name": row.get("flow_name") or "",
        "step_name": row.get("step_name") or "",
        "run_id": row.get("run_id") or "",
        "subject": row.get("subject") or "",
        "technique": row.get("technique") or "",
        "model_name": row.get("model_name") or "",
        "decision": row.get("decision") or "",
        "confidence": float(row.get("confidence") or 0.0),
        "input_tokens": int(row.get("input_tokens") or 0),
        "output_tokens": int(row.get("output_tokens") or 0),
        "latency_ms": int(row.get("latency_ms") or 0),
        "generated_at_ms": int(gen.timestamp() * 1000) if gen else 0,
        "has_layers": bool(layers),
        "layer_count": len(layers),
    }


def _scan_to_rows(scan) -> list[dict]:
    arrow = scan.to_arrow()
    cols = arrow.column_names
    return [
        {c: arrow.column(c)[i].as_py() for c in cols}
        for i in range(arrow.num_rows)
    ]


def fetch_corpus(
    limit: int = 40,
    window_days: int = 30,
    flow: str = "",
) -> tuple[list[dict], int]:
    """Recent reasoning traces (light rows), newest first.

    Returns (items, total-matched-in-window).
    """
    from datetime import datetime, timedelta, timezone

    limit = max(1, min(int(limit or 40), _MAX_LIMIT))
    window_days = max(1, int(window_days or 30))
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    filters = [f"generated_at >= '{since.isoformat()}'"]
    if flow:
        safe = flow.replace("'", "")
        filters.append(f"flow_name == '{safe}'")
    try:
        scan = _table().scan(
            row_filter=" and ".join(filters),
            selected_fields=_LIST_FIELDS,
        )
        rows = _scan_to_rows(scan)
    except Exception as e:  # noqa: BLE001 — re-raise with a guru
        raise RuntimeError(
            f"{GURU_CORPUSREAD} could not scan hx.cot_reasoning: {e}\n"
            "  Check: sudo systemctl status signals-polaris.service (:8181) "
            "and RustFS :9010 credentials"
        ) from e
    rows.sort(key=lambda r: r.get("generated_at") or 0, reverse=True)
    total = len(rows)
    return [_row_item(r) for r in rows[:limit]], total


def fetch_trace(record_id: str) -> dict:
    """One full reasoning trace: item + prompt/trace/output + tagged layers."""
    if not record_id:
        raise ValueError(f"{GURU_NOTRACE} empty trace id")
    safe = record_id.replace("'", "")
    try:
        scan = _table().scan(row_filter=f"id == '{safe}'", limit=1)
        rows = _scan_to_rows(scan)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"{GURU_CORPUSREAD} could not read hx.cot_reasoning id={safe}: {e}\n"
            "  Check: sudo systemctl status signals-polaris.service (:8181) "
            "and RustFS :9010 credentials"
        ) from e
    if not rows:
        raise ValueError(f"{GURU_NOTRACE} no reasoning trace with id {safe}")
    row = rows[0]
    return {
        "item": _row_item(row),
        "prompt": row.get("prompt") or "",
        "reasoning_trace": row.get("reasoning_trace") or "",
        "output": row.get("output") or "",
        "layers": _parse_layers(row.get("reasoning_layers")),
    }
