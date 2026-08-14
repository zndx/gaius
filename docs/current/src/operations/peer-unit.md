# Signals peer unit (gaius.service)

Gaius joins the Signals lattice as peer id `gaius`. Process lifecycle is a
systemd oneshot under `signals.target`; the wire contract is
`zndx.engine.v1.Engine` on **:50051**.

This is **not** the older GPU-mesh story in `src/gaius/engine/FEDERATION.md`.
Lattice accept is Engine/Status, not KServe peer discovery.

| Fact | Value |
|------|--------|
| Peer id | `gaius` |
| Unit | `gaius.service` (`After=signals-ready.service`) |
| Wrappers | `scripts/systemd_start.sh` / `scripts/systemd_stop.sh` |
| gRPC lattice | `:50051` — `zndx.engine.v1.Engine` (+ native `GaiusService` + OIP) |
| Postgres | `:5444` (`zndx_gaius`) — never Signals `:5455` |
| Capability | `cognition` |
| Status.project | `gaius` |

## Wrappers

`systemd_start.sh` skip-up only if the **unit** already owns the single
`:50051` listener **and** `pg_isready` on **:5444**. A leftover login-shell
devenv or a shifted postmaster on :5445 does **not** count. Otherwise it
reaps Gaius compose daemons, stops an orphan Gaius `postmaster` holding
`.devenv/state/postgres`, then `just up` with `PGPORT=5444`.

`systemd_stop.sh` downs that runtime, SIGTERM/KILLs remaining Gaius compose
daemons (cwd match only), then frees `:50051` of `gaius.engine`. It does
**not** call `just teardown` / GPU cleanup (sibling leases).

```bash
# Local product stack (same as the unit)
just up
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
just down
```

## Operator (after wrappers land)

From the Signals tree:

```bash
just install-systemd --peers gaius --enable
sudo systemctl start signals.target    # not bare "signals"
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius
```

`systemctl start gaius` starts this peer alone; it still waits on
`signals-ready.service`.

The unit is `Type=oneshot` `RemainAfterExit=yes` with `KillMode=control-group`.
It sets `XDG_RUNTIME_DIR=/run/user/<uid>` and
`GAIUS_DEVENV_RUNTIME=/run/user/<uid>/gaius-systemd` so it never attaches to
a leftover `$XDG_RUNTIME_DIR/devenv-<hash>` from a login-shell `devenv up`.
After `systemctl restart gaius` the listener must be in
`system.slice/gaius.service` (one PID on `:50051`).

## Platform Metaflow / events (when federated)

When Gaius is joining the Signals foundation, treat platform Metaflow as the
system of record — do not treat the Gaius-local Tilt Metaflow as SoR:

```bash
export METAFLOW_SERVICE_URL=http://127.0.0.1:30180
# profile: signals config/metaflow/platform.json
```

CloudEvents such as `dev.gaius.article.curate.requested` go to the platform
broker (`signals-events/default`), not a Gaius-local event bus.

Gaius-local Metabase on `:3100` is **not** the federation dashboard. That is
the optional AGPL Metabase peer (`:3200` / `:50451`).

## Health

Health/FMEA stays Gaius-local (`/health`, `/health fix engine`). Lattice-ci
probes generated-client Status **and** server reflection (`grpcurl list`).
Generated stubs remain the protocol SoR; reflection is the external spot-check.

`:50051` is exclusive. gRPC `SO_REUSEPORT` is off; a second `gaius-engine`
must fail with `#EN.00000014.DUALBIND` rather than dual-bind. GPU cleanup
is lease-aware and must stay that way so Ægir/Atelier endpoints survive a
Gaius restart.
