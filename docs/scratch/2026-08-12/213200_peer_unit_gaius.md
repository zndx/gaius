# peer-unit@gaius — lattice join

**Date:** 2026-08-12

## Why

Signals peer-unit-spec / peer-integration.md: Gaius is the first in-org peer
after Metabase. Sample `gaius.service` still ran temporary `just up` and the
engine did not register `zndx.engine.v1.Engine`, so lattice-ci Status would
fail even with :50051 listening.

## Done (Gaius tree)

- `scripts/systemd_start.sh` / `systemd_stop.sh` (Metabase pattern)
- `just up` / `just down` for those wrappers
- Generated `zndx.engine.v1` bindings from `external/signals-protocol`
- `GaiusZndxEngineServicer` on the existing gRPC server (Status + Complete)
- Status: `project=gaius`, always advertises `cognition`
- Docs: `docs/current/src/operations/peer-unit.md`

## Done (Signals tree)

- `infra/systemd/gaius.service` Exec* → Gaius wrappers; `After=signals-ready`

## Accept (operator)

```bash
cd ~/local/src/wxs/signals
just install-systemd --peers gaius --enable
sudo systemctl start signals.target
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius
```

Engine must be restarted once for the new servicer to bind. Status is available
as soon as gRPC is up (phase GRPC); it does not wait for vLLM endpoints.

## Verification (this session)

- `pytest tests/engine/test_zndx_engine_servicer.py` — 8 passed
- Ephemeral `:50059` `grpcurl … Engine/Status` → `project=gaius`,
  `capability=cognition`, `totalGpus=6`
- `just install-systemd --peers gaius --enable` — unit installed, enabled
- Live `:50051` still the pre-change engine (no reflection, Status RPC
  unimplemented). Two devenv daemons were both holding the port; did not
  recycle the product engine from this session.
- `just lattice-ci --require gaius` FAIL until that recycle
