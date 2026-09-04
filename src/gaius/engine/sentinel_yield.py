"""Engine/Yield body: C2 asks Gaius to end the host process for a YK Application.

Sentinel **is** the Application. YK preempt → C2 HTTP last-gasp → this RPC.
Unknown ``workload_id`` is idempotent (ok, not ended).
"""

from __future__ import annotations

import logging
from typing import Any

from gaius.engine.flow_processes import flow_processes
from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.sentinel_claim import (
    AMBIENT_WORKLOAD_ID,
    EMBEDDING_WORKLOAD_ID,
    OPTILLM_WORKLOAD_ID,
    capability_workload_id,
    delete_flow_sentinel,
    release_kind,
)

log = logging.getLogger("gaius.engine.sentinel_yield")

# Standing vLLM / CLT aliases whose Application id is gaius-<alias>.
_CAPABILITY_ALIASES = frozenset(
    {
        "thinking",
        "reasoning",
        "ask-agent",
        "interpretable",
        "interpretable-b",
        "ask-sae",
        "clt",
        "orchestrator",
        "optillm",
    }
)


def alias_for_workload(workload_id: str) -> str:
    wid = (workload_id or "").strip()
    if wid.startswith("gaius-"):
        rest = wid[len("gaius-") :]
        if rest in _CAPABILITY_ALIASES:
            return rest
        if rest == "thinking":
            return "thinking"
    if wid in _CAPABILITY_ALIASES:
        return wid
    if wid.startswith("clt-probe"):
        return "clt"
    return ""


async def yield_workload(services: Any, request: zpb.YieldRequest) -> zpb.YieldResponse:
    wid = (request.workload_id or "").strip()
    if not wid:
        return zpb.YieldResponse(
            ok=True, process_ended=False, restore_started=False, message="empty workload_id"
        )

    table = flow_processes()
    if table.get(wid) is not None:
        ended, msg = await table.yield_one(wid)
        return zpb.YieldResponse(
            ok=True, process_ended=ended, restore_started=False, message=msg
        )

    if wid == AMBIENT_WORKLOAD_ID:
        ambient = getattr(services, "ambient_service", None)
        if ambient is not None:
            await ambient.pause_gpu(f"yield:{wid}")
            release_kind("ambient")
            await ambient.stop_daemon()
            await ambient._set_operator_disabled(False)
            await ambient._set_preempted(True)
            return zpb.YieldResponse(
                ok=True,
                process_ended=True,
                restore_started=False,
                message=f"ended ambient {wid}",
            )

    if wid in (OPTILLM_WORKLOAD_ID, "optillm") or alias_for_workload(wid) == "optillm":
        orch = getattr(services, "orchestrator_service", None)
        opt = getattr(orch, "_optillm", None) if orch is not None else None
        if opt is not None:
            await opt.stop()
        import asyncio as _aio

        await _aio.to_thread(delete_flow_sentinel, OPTILLM_WORKLOAD_ID)  # off-loop
        return zpb.YieldResponse(
            ok=True,
            process_ended=True,
            restore_started=False,
            message=f"stopped optillm {wid}",
        )

    if wid in (EMBEDDING_WORKLOAD_ID, "embedding", "colbert", "aperture"):
        # (2026-09-04) YuniKorn preempted the on-demand light claim (a higher
        # priority phase — extract, or another owner's embedding intent — needs
        # the token). Free the model, forget the GPU pin, retire the sentinel
        # (delete_flow_sentinel zero-floors the share on the way out). The next
        # embed call re-admits and re-pins wherever the light claim lands.
        import asyncio as _aio

        from gaius.engine.embeddings.colbert import release_colbert_embedder
        from gaius.engine.sentinel_claim import reset_light_device_pin

        unloaded = await _aio.to_thread(release_colbert_embedder)
        reset_light_device_pin()
        await _aio.to_thread(delete_flow_sentinel, EMBEDDING_WORKLOAD_ID)  # off-loop
        logging.getLogger("gaius.engine.sentinel_yield").info(
            "Yield %s: ColBERT unloaded=%s, light pin reset, sentinel retired",
            wid,
            unloaded,
        )
        return zpb.YieldResponse(
            ok=True,
            process_ended=True,
            restore_started=False,
            message=f"released embedding {wid} (model_unloaded={unloaded})",
        )

    alias = alias_for_workload(wid)
    orch = getattr(services, "orchestrator_service", None)
    if alias and orch is not None:
        stopped = await orch.stop_endpoint(alias)
        import asyncio as _aio

        await _aio.to_thread(delete_flow_sentinel, wid)  # off-loop (kubectl delete)
        await _aio.to_thread(delete_flow_sentinel, capability_workload_id(alias))
        restore_started = False
        if request.reason == zpb.YIELD_REASON_COMPLETED:
            try:
                await orch.complete_workload(wid)
                restore_started = True
            except Exception as e:
                log.warning("complete_workload after Yield: %s", e)
        msg = f"stopped endpoint {alias} workload_id={wid} stopped={stopped}"
        log.info("yield %s", msg)
        return zpb.YieldResponse(
            ok=True,
            process_ended=bool(stopped),
            restore_started=restore_started,
            message=msg,
        )

    return zpb.YieldResponse(
        ok=True,
        process_ended=False,
        restore_started=False,
        message=f"no host process for workload_id={wid}",
    )
