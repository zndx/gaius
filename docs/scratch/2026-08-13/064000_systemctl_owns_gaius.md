# systemctl restart gaius owns the listener

**Date:** 2026-08-13

Stop reaps all devenv compose daemons with `cwd` = Gaius checkout (not
just `devenv processes down` on one runtime). Start skip-up only if the
listener is already in `gaius.service`. Unit sets `XDG_RUNTIME_DIR` and
`GAIUS_DEVENV_RUNTIME`.

Verified: `systemctl stop gaius` → `:50051` free; `systemctl start gaius` →
one listener in `system.slice/gaius.service`; `grpcurl list` + lattice-ci
PASS.

`devenv uv.sync.extras` now includes `grpc` so `just up` does not drop
`grpcio-reflection`.
