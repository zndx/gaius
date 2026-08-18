"""YK light CLT probe → feature_tape. Salience corpus, not chat."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from gaius.engine.sentinel_claim import (
    YkAdmitError,
    ephemeral_claim,
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
    if not light_wait_available():
        raise RuntimeError(GURU_NOLIGHT)
    wid = ephemeral_claim(KIND, f"gaius-clt-probe-{gpu_index}")
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
        text = f"{row['title']}\n\n{row['body']}"[:4000]
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
