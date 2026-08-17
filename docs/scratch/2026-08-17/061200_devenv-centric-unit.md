# systemd is the hook; devenv owns the graph

Align Gaius with Atelier's wrap: `signals.target` membership only.
`systemd_start.sh` runs `devenv up -d` (no dedicated `gaius-systemd`
runtime, no `postgresql.auto.conf` pin, no cgroup ownership check).

Ports: product scripts follow devenv `PGPORT`, then a live PGDATA
listener. SecretSpec declared in `secretspec.toml`; devenv.yaml enables
the dotenv provider.

Installed `/etc/systemd/system/gaius.service` may still export
`GAIUS_DEVENV_RUNTIME` / `PGPORT=5444` until `just install-systemd
--peers gaius --enable`. Scripts honor that env if set (legacy).
