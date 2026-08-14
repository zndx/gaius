# signals-protocol pin: Engine/Yield

**Date:** 2026-08-14

`external/signals-protocol` `4433547` (Remediate) → `428a525`
(`feat: add Engine/Yield for C2-preempted sentinel Applications`).
Matches weathership/signals pin `d492716`.

```
cd external/signals-protocol && git fetch origin && git checkout 428a525
just proto-generate
```

Yield is now the shared proto, not a dirty one-off in the submodule.
Live `:50051` already listed `Engine/Yield`. Tests: 12 passed
(`test_flow_yield` + `test_zndx_engine_servicer`).
