"""YK light CLT probe → feature_tape. Salience corpus, not chat."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from gaius.engine.sentinel_claim import (
    apply_and_admit,
    capability_workload_id,
    gpu_start_allowed,
    light_wait_available,
)

logger = logging.getLogger(__name__)

GURU_NOLIGHT = (
    "CLT probe needs a light YK slot.\n"
    "  Guru: #CLT.00000002.NOLIGHT\n"
    "  Try: wait for internal.inference.light"
)
GURU_NOSTART = (
    "CLT probe GPU start refused (no admitted Application).\n"
    "  Guru: #CLT.00000003.NOADMIT\n"
    "  Try: Signals YK admit clt-probe"
)

KIND = "clt-probe"
BATCH = 8
WINDOW = timedelta(days=7)


def _collapse_features(raw: list[dict[str, Any]]) -> list[tuple[int, int, float]]:
    """Max activation per (layer, feature) across token positions."""
    best: dict[tuple[int, int], float] = {}
    for f in raw:
        key = (int(f["layer_idx"]), int(f["feature_idx"]))
        act = float(f["activation"])
        if act > best.get(key, 0.0):
            best[key] = act
    # Keep a compact top set so disk/index stay lean
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:64]
    return [(layer, idx, act) for (layer, idx), act in ranked]


async def run_probe_batch(pool: Any, *, gpu_index: int = 4) -> dict[str, Any]:
    from gaius.engine.services.clt_service import get_clt_service
    from gaius.engine.services.feature_tape import (
        ensure_tape,
        insert_activations,
        pick_unprobed_inflow,
        tape_stats,
    )

    await ensure_tape(pool)
    # No light GPU token free (thinking holds four, the embedding sentinel
    # one; a prospects extract or a CLT/SKOS admit may hold the last): a
    # deferral, not a failure — the probe runs every 5 min and takes the
    # next free slot. Raising here booked an error row per miss.
    if not light_wait_available():
        return {"status": "deferred", "reason": "no light YK slot", "probed": 0,
                "rows_written": 0, "remaining_hint": True}
    # Standing CLT worker process ↔ gaius-clt. Not a per-batch extract claim.
    wid = capability_workload_id("clt")
    import asyncio as _aio

    try:
        await _aio.to_thread(apply_and_admit, wid, KIND)  # off-loop: never block the engine
    except Exception as e:  # noqa: BLE001 — classify, never mask
        if "#YK.00000002.NOTADMITTED" in str(e):
            return {"status": "deferred", "reason": "yk_admission", "probed": 0,
                    "rows_written": 0, "remaining_hint": True}
        raise
    if not gpu_start_allowed(wid):
        raise RuntimeError(GURU_NOSTART)

    svc = get_clt_service(gpu_index=gpu_index)
    svc.ensure_loaded()

    since = datetime.now(timezone.utc) - WINDOW
    items = await pick_unprobed_inflow(pool, since=since, limit=BATCH)
    probed = 0
    rows_written = 0
    worker = f"gpu{gpu_index}"
    for row in items:
        from gaius.engine.services.clt_skos_admit import extracted_source_text
        from gaius.ingest.htmlplain import to_plain_text

        try:
            text, _origin = extracted_source_text(
                title=str(row["title"] or ""),
                summary=str(row["body"] or ""),
                kb_path=str(row["kb_path"] or ""),
            )
        except RuntimeError:
            text = to_plain_text(f"{row['title']}\n\n{row['body']}")
        text = text[:4000]
        event_id = f"inflow:{row['id']}"
        resp = svc._send_command(
            {"method": "extract", "params": {"text": text, "top_k": 32}},
            timeout=180.0,
        )
        if "error" in resp:
            logger.warning("CLT extract failed %s: %s", event_id, resp["error"])
            continue
        feats = _collapse_features(resp.get("result", {}).get("features") or [])
        n = await insert_activations(
            pool,
            event_id=event_id,
            stream="inflow",
            source_id=str(row["id"]),
            ts=row["fetched_at"],
            rows=feats,
            worker=worker,
        )
        probed += 1
        rows_written += n

    stats = await tape_stats(pool, since=since)
    return {
        "status": "ok",
        "probed": probed,
        "rows_written": rows_written,
        "remaining_hint": len(items) == BATCH,
        "workload_id": wid,
        "gpu": gpu_index,
        **stats,
    }
