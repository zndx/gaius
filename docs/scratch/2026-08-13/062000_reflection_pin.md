# Reflection for grpcurl / lattice-ci

**Date:** 2026-08-13

`grpcio-reflection==1.83` ships `reflection_pb2` gencode 7.35.1; this tree
must stay on protobuf 6 (`xai-sdk`, otel, grpcio-tools all `<7`). Venv had
drifted to 1.83 while `uv.lock` had 1.81.1.

Pinned `grpcio-reflection>=1.59,<1.82` in the grpc extra, installed 1.81.1.
Engine fail-fast `#EN.00000015.NOREFLECT` if import fails.

```
grpcurl -plaintext 127.0.0.1:50051 list
# gaius.engine.GaiusService
# grpc.reflection.v1alpha.ServerReflection
# inference.GRPCInferenceService
# zndx.engine.v1.Engine

just lattice-ci --require gaius   # PASS codegen + reflection
```
