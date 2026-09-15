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


def clt_probe_resident() -> bool:
    return gpu_start_allowed(capability_workload_id("clt"))


def _from_service(svc: Any, text: str, top_k: int, workload_id: str) -> dict[str, Any]:
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
        "workload_id": workload_id,
    }


def extract_positional_reuse_or_own(
    text: str,
    *,
    top_k: int = 16,
) -> tuple[dict[str, Any], str]:
    """CLT extract: resident gaius-clt (parallel) or this flow's LIGHT GPU (sequential).

    ColBERT and CLT are different models. They need not share a step. Parallel
    uses the standing CLT worker on the other light token; sequential unloads
    ColBERT and runs the CLT worker on this run's token.
    """
    wid = capability_workload_id("clt")
    if clt_probe_resident():
        return extract_positional(text, top_k=top_k), "parallel"

    from gaius.engine.embeddings.colbert import release_colbert_embedder
    from gaius.engine.sentinel_claim import embedding_cuda_device, own_gpu_application
    from gaius.engine.services.clt_service import CLTService

    if own_gpu_application() is None:
        raise RuntimeError(
            "CLT extract needs a resident clt-probe Application or this "
            "flow's LIGHT token.\n  Guru: #CLT.00000003.NOADMIT"
        )
    release_colbert_embedder()
    dev = embedding_cuda_device()
    idx = int(str(dev).rsplit(":", 1)[-1])
    svc = CLTService(gpu_index=idx)
    try:
        return _from_service(svc, text, top_k, wid), "sequential"
    finally:
        worker = getattr(svc, "_worker", None)
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=30)
            except Exception:
                worker.kill()
