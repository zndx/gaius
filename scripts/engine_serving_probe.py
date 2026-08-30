#!/usr/bin/env python3
"""Cheap out-of-band :50051 liveness probe for the engine-ready watchdog.

Exit codes (the watchdog acts on these):
  0  Status answered — engine SERVING.
  2  gRPC UNAVAILABLE — connection-level failure (process dead / port closed).
     This is the definitive "dead" signal the watchdog recycles on. It is what the
     2026-08-29 outage looked like (`:50051` down, `nc -z` the only truth).
  3  gRPC DEADLINE_EXCEEDED — reachable but SLOW to answer. NOT counted as dead:
     the engine's Status RPC is legitimately bimodal (~0.15s typically, but 20s+
     spikes under endpoint/GPU contention), so slowness must never trigger a
     recycle of a healthy-but-busy engine.
  1  Any other error.

Why not reuse scripts/zndx_status_ok.py: importing the generated protobuf stubs
pulls `from gaius.engine.generated...` (engine_pb2_grpc.py:6), which drags in
`gaius.engine.__init__ -> server ->` the whole engine — ~5.8s CPU and ~885 MB RSS
per call. Far too heavy to run every poll. This probe imports ONLY `grpc` (~0.1s)
and issues a RAW unary call with identity (de)serializers: StatusRequest has no
required fields, so an empty request is valid, and we only need the server to
respond — we do not deserialize the reply. Project-identity (project == "gaius",
the NOTUNIT/DUALBIND guard) is the readiness probe's job, not this liveness check.
"""
from __future__ import annotations

import os
import sys

import grpc


def main() -> int:
    port = os.environ.get("GAIUS_ENGINE_GRPC_PORT", "50051")
    timeout = float(os.environ.get("GAIUS_ENGINE_PROBE_RPC_TIMEOUT", "8"))
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        status = channel.unary_unary(
            "/zndx.engine.v1.Engine/Status",
            request_serializer=lambda b: b,      # identity: raw bytes in
            response_deserializer=lambda b: b,   # identity: raw bytes out (ignored)
        )
        status(b"", timeout=timeout)  # raw: empty request, reply ignored
    except grpc.RpcError as e:
        code = e.code()
        print(f"Status RPC failed: {code}", file=sys.stderr)
        if code == grpc.StatusCode.UNAVAILABLE:
            return 2   # dead / unreachable — the recycle signal
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            return 3   # alive but slow — do NOT recycle
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"probe error: {e}", file=sys.stderr)
        return 1
    finally:
        channel.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
