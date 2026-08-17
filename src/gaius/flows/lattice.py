"""Signals lattice client for Metaflow steps (host or RKE2).

Call ``zndx.engine.v1.Engine/Complete`` on the Gaius engine. Never dial
vLLM ``:8081``. Target:

- Host / Airflow submitter: ``127.0.0.1:50051``
- RKE2 Metaflow task: ``GAIUS_ENGINE_GRPC=gaius-engine.metaflow.svc.cluster.local:50051``

This is not a Gaius Metaflow instance — metadata/datastore stay on Signals.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

GURU_NOLATTICE = "#GR.00000002.NOLATTICE"
GURU_NOCAP = "#GR.00000003.NOCAP"
DEFAULT_CAPABILITY = "thinking"
DEFAULT_TARGET = "127.0.0.1:50051"


def engine_target(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    raw = (env.get("GAIUS_ENGINE_GRPC") or DEFAULT_TARGET).strip()
    if env.get("KUBERNETES_SERVICE_HOST") and "svc.cluster.local" not in raw:
        raise RuntimeError(
            f"{GURU_NOLATTICE} in-cluster step must set GAIUS_ENGINE_GRPC "
            "to gaius-engine.metaflow.svc.cluster.local:50051 "
            f"(got {raw!r}).\n"
            "  Apply infra/k8s/gaius-engine-host-bridge.yaml"
        )
    return raw or DEFAULT_TARGET


@dataclass(frozen=True)
class LatticeComplete:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    reasoning_content: str
    finish_reason: str


def complete(
    prompt: str,
    *,
    capability: str = DEFAULT_CAPABILITY,
    system_prompt: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.7,
    json_schema: dict[str, Any] | str | None = None,
    timeout_s: float = 300.0,
    target: str | None = None,
) -> LatticeComplete:
    """Blocking Complete for Metaflow steps (sync FlowSpec)."""
    import grpc

    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    addr = target or engine_target()
    schema = ""
    if json_schema is not None:
        schema = json_schema if isinstance(json_schema, str) else json.dumps(json_schema)
    cap = (capability or DEFAULT_CAPABILITY).strip() or DEFAULT_CAPABILITY
    req = zpb.CompleteRequest(
        capability=cap,
        prompt=prompt,
        system_prompt=system_prompt or "",
        max_tokens=int(max_tokens),
        temperature=float(temperature),
        json_schema=schema,
    )
    channel = grpc.insecure_channel(addr)
    try:
        stub = zpb_grpc.EngineStub(channel)
        resp = stub.Complete(req, timeout=timeout_s)
    except grpc.RpcError as e:
        raise RuntimeError(
            f"{GURU_NOLATTICE} Engine/Complete failed at {addr}: {e.code().name} {e.details()}\n"
            "  Try: grpcurl -plaintext ${GAIUS_ENGINE_GRPC:-127.0.0.1:50051} "
            "zndx.engine.v1.Engine/Status\n"
            "  Or:  /gpu status"
        ) from e
    finally:
        channel.close()
    return LatticeComplete(
        text=resp.text or "",
        model=resp.model or "",
        prompt_tokens=int(resp.prompt_tokens or 0),
        completion_tokens=int(resp.completion_tokens or 0),
        latency_ms=float(resp.latency_ms or 0.0),
        reasoning_content=resp.reasoning_content or "",
        finish_reason=resp.finish_reason or "",
    )


def require_signals_metaflow(environ: dict[str, str] | None = None) -> None:
    """Fail if this process is about to use a Gaius-local / Tilt datastore."""
    from gaius.flows.platform_metaflow import GURU_NOPLATFORM, PlatformMetaflowError

    env = environ if environ is not None else os.environ
    ds = (env.get("METAFLOW_DEFAULT_DATASTORE") or "").strip().lower()
    sysroot = env.get("METAFLOW_DATASTORE_SYSROOT_S3") or ""
    if ds in {"local", ""}:
        raise PlatformMetaflowError(
            GURU_NOPLATFORM,
            "Prospects uses the Signals Metaflow datastore, not a Gaius-local one. "
            f"METAFLOW_DEFAULT_DATASTORE={ds!r}.\n"
            "  Set GAIUS_METAFLOW_MODE=platform (Signals :30180 + RustFS).",
        )
    if "metaflow-artifacts" in sysroot or "devenv-minio" in (
        env.get("METAFLOW_S3_ENDPOINT_URL") or ""
    ):
        raise PlatformMetaflowError(
            GURU_NOPLATFORM,
            "config/metaflow/k8s.json is the old Tilt/MinIO profile, not Signals. "
            "Use SIGNALS_ROOT/config/metaflow/platform.json.",
        )
