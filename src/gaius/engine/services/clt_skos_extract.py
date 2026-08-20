"""Positional CLT extract for SKOS grounding (does not collapse layers)."""

from __future__ import annotations

from typing import Any

from gaius.engine.sentinel_claim import (
    apply_and_admit,
    capability_workload_id,
    gpu_start_allowed,
)
from gaius.engine.services.clt_service import get_clt_service

KIND = "clt-probe"


def extract_positional(
    text: str,
    *,
    gpu_index: int = 4,
    top_k: int = 32,
) -> dict[str, Any]:
    wid = capability_workload_id("clt")
    apply_and_admit(wid, KIND)
    if not gpu_start_allowed(wid):
        raise RuntimeError(
            "CLT SKOS extract GPU start refused (no admitted Application).\n"
            "  Guru: #CLT.00000003.NOADMIT"
        )
    svc = get_clt_service(gpu_index=gpu_index)
    svc.ensure_loaded()
    resp = svc._send_command(
        {"method": "extract", "params": {"text": text, "top_k": top_k}},
        timeout=180.0,
    )
    if "error" in resp:
        raise RuntimeError(f"CLT extract failed: {resp['error']}")
    result = resp.get("result") or {}
    feats = result.get("features") or []
    for f in feats:
        f["model"] = "clt"
    return {
        "features": feats,
        "offsets": [tuple(p) for p in (result.get("offsets") or [])],
        "total_positions": int(result.get("total_positions") or 0),
        "workload_id": wid,
    }
