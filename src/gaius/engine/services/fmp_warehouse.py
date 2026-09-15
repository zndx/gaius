"""Prepare typed FMP warehouse tables and hook Metabase on completion.

Engine-first: RPC/CLI/MCP enqueue a Metaflow. The flow Completes thinking
only for a model narrative; column IRIs are the declared scratch map in
``hx.fmp_warehouse``. After land, gRPC ProjectWarehouse on the Metabase peer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("gaius.engine.services.fmp_warehouse")

GURU_MB = "#SL.00000010.MBNOPEER"
GURU = "#FMP.00000010.WAREHOUSE"


async def enqueue_prepare(
    pool: Any,
    *,
    symbols: list[str],
    tools: list[str] | None = None,
    source: str = "engine",
) -> int:
    """Insert scheduled_tasks row; STP spawns FmpWarehouseFlow."""
    payload = {
        "symbols": [s.strip().upper() for s in symbols if s.strip()],
        "tools": tools or ["quote", "filings", "calendar"],
    }
    if not payload["symbols"]:
        raise RuntimeError(f"{GURU} symbols required")
    tid = await pool.fetchval(
        """
        INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
        VALUES ('fmp_warehouse', $1::jsonb, $2, NOW())
        RETURNING id
        """,
        json.dumps(payload),
        source,
    )
    return int(tid)


def metabase_peer(surfaces: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in surfaces:
        project = str(item.get("project") or "").lower()
        ui = str(item.get("primary_ui") or "")
        target = str(item.get("engine_target") or "")
        if project == "metabase" or ":3200" in ui or ":50451" in target:
            return item
    return None


def notify_metabase(
    *,
    tables: list[dict[str, Any]],
    engine_target: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """gRPC ProjectWarehouse on the Metabase engine. Fail-closed if unreachable."""
    import grpc

    if not engine_target:
        raise RuntimeError(
            f"{GURU_MB} FederationSurfaces has no metabase peer "
            "(project=metabase or primary_ui :3200)."
        )
    # Generated stub lives in the AGPL tree; Gaius talks the proto over plaintext.
    try:
        from gaius.engine.generated.metabase import metabase_engine_pb2 as pb
        from gaius.engine.generated.metabase import metabase_engine_pb2_grpc as pb_grpc
    except ImportError as e:
        raise RuntimeError(
            f"{GURU_MB} Metabase engine stubs missing: {e}\n"
            "  Compile src/gaius/engine/proto/metabase_engine.proto into generated/metabase."
        ) from e

    bindings = {}
    names = []
    for t in tables:
        name = str(t.get("table") or "").split(".")[-1]
        names.append(str(t.get("table") or name))
        iris = t.get("iris") or {}
        if isinstance(iris, dict):
            bindings[name] = iris
    req = pb.ProjectWarehouseRequest(
        tables_json=json.dumps(names),
        bindings_json=json.dumps(bindings),
        namespace="gaius.fmp",
    )
    channel = grpc.insecure_channel(engine_target)
    try:
        stub = pb_grpc.MetabaseEngineStub(channel)
        resp = stub.ProjectWarehouse(req, timeout=timeout_s)
    except grpc.RpcError as e:
        raise RuntimeError(
            f"{GURU_MB} ProjectWarehouse at {engine_target} failed: "
            f"{e.code().name} {e.details()}"
        ) from e
    finally:
        channel.close()
    if not resp.ok:
        raise RuntimeError(f"{resp.guru or GURU_MB} {resp.detail}")
    return {"ok": True, "fields": resp.fields_projected, "detail": resp.detail}
