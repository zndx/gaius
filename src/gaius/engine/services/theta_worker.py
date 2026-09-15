"""Theta consolidation worker — JVM + BERTSubs off the engine event loop.

Spawned by ThetaService with CUDA_VISIBLE_DEVICES (light leaf). JSON-RPC
on stdin/stdout, same shape as clt_worker.

    CUDA_VISIBLE_DEVICES=<gpu> python -m gaius.engine.services.theta_worker
"""

from __future__ import annotations

import json
import sys
from typing import Any


def main() -> int:
    print("theta_worker starting", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": {"message": str(e)}}), flush=True)
            continue
        method = cmd.get("method")
        if method == "shutdown":
            print(json.dumps({"result": "ok"}), flush=True)
            return 0
        if method == "status":
            print(json.dumps({"result": {"ready": True}}), flush=True)
            continue
        if method != "consolidate":
            print(json.dumps({"error": {"message": f"unknown method {method}"}}), flush=True)
            continue
        params = cmd.get("params") or {}
        try:
            result = _consolidate(params)
            print(json.dumps({"result": result}, default=str), flush=True)
        except Exception as e:
            print(
                json.dumps(
                    {
                        "error": {
                            "message": str(e),
                            "type": type(e).__name__,
                        }
                    }
                ),
                flush=True,
            )
    return 0


def _consolidate(params: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from gaius.agents.theta.agent import ThetaAgent
    from gaius.engine.services.theta_service import ThetaService, ThetaConfig

    slice_id = str(params.get("slice_id") or "")
    thoughts = list(params.get("thoughts") or [])
    max_candidates = int(params.get("max_candidates") or 10)

    async def _run() -> dict[str, Any]:
        svc = ThetaService(ThetaConfig())
        # Worker already has thoughts; skip pool load by calling the agent
        # after encoding here (same encode path as the service).
        centroid = await svc._encode_centroid(thoughts)
        agent = ThetaAgent(
            profile=svc.config.profile,
            kb_root=svc.config.kb_root,
            research_mode=svc.config.research_mode,
        )
        result = await agent.run_consolidation(
            temporal_slice=slice_id,
            max_candidates=max_candidates,
            centroid=centroid,
            documents=thoughts,
        )
        return {
            "success": result.error is None,
            "slice_id": result.slice_id,
            "signal": result.signal.to_dict() if result.signal else None,
            "candidates_evaluated": result.candidates_evaluated,
            "candidates_selected": result.candidates_selected,
            "documents_augmented": result.documents_augmented,
            "effectiveness": result.effectiveness,
            "error": result.error,
        }

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
