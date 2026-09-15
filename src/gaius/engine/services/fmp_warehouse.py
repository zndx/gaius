"""Prepare typed FMP warehouse tables and hook Metabase on completion.

Engine-first: RPC/CLI/MCP enqueue a Metaflow. The flow Completes thinking
only for a model narrative; column IRIs are the declared scratch map in
``hx.fmp_warehouse``. After Kudu land, gRPC ProjectWarehouse on the
Metabase peer from FederationSurfaces (project=metabase / :3200).
"""
from __future__ import annotations

import json
import logging
import os
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


def federation_surfaces(*, engine_target: str = "", timeout_s: float = 10.0) -> list[dict[str, Any]]:
    """Ask local Gaius FederationSurfaces. Fail-closed on RPC error."""
    import grpc

    from gaius.engine.generated import FederationSurfacesRequest
    from gaius.engine.generated import gaius_service_pb2_grpc as pb_grpc

    addr = (
        engine_target
        or os.environ.get("GAIUS_ENGINE_TARGET")
        or "127.0.0.1:50051"
    ).strip()
    channel = grpc.insecure_channel(addr)
    try:
        stub = pb_grpc.GaiusServiceStub(channel)
        resp = stub.FederationSurfaces(FederationSurfacesRequest(), timeout=timeout_s)
    except grpc.RpcError as e:
        raise RuntimeError(
            f"{GURU_MB} FederationSurfaces at {addr} failed: "
            f"{e.code().name} {e.details()}"
        ) from e
    finally:
        channel.close()
    if resp.error:
        raise RuntimeError(f"{GURU_MB} FederationSurfaces: {resp.error}")
    return [
        {
            "project": it.project,
            "engine_target": it.engine_target,
            "primary_ui": it.primary_ui,
        }
        for it in resp.items
    ]


def resolve_metabase_target(
    *,
    engine_target: str = "",
    surfaces: list[dict[str, Any]] | None = None,
) -> str:
    """Metabase engine from explicit target, env, or FederationSurfaces."""
    explicit = (engine_target or os.environ.get("METABASE_ENGINE_TARGET") or "").strip()
    if explicit:
        return explicit
    rows = surfaces if surfaces is not None else federation_surfaces()
    peer = metabase_peer(rows)
    if peer is None or not str(peer.get("engine_target") or "").strip():
        raise RuntimeError(
            f"{GURU_MB} FederationSurfaces has no metabase peer "
            "(project=metabase or primary_ui :3200)."
        )
    return str(peer["engine_target"]).strip()


def notify_metabase(
    *,
    tables: list[dict[str, Any]],
    engine_target: str = "",
    timeout_s: float = 30.0,
    surfaces: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """gRPC ProjectWarehouse on the Metabase engine. Fail-closed if unreachable."""
    import grpc

    engine_target = resolve_metabase_target(
        engine_target=engine_target, surfaces=surfaces
    )
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
        full = str(t.get("table") or "")
        name = full.split(".")[-1]
        names.append(full or name)
        iris = t.get("iris") or {}
        if isinstance(iris, dict):
            bindings[name] = iris
            if name.startswith("v_fmp_"):
                bindings[name[6:]] = iris
            if name.startswith("fmp_"):
                bindings[name[4:].removesuffix("_tier0")] = iris
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
