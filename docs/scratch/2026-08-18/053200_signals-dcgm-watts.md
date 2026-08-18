# Signals DCGM — ephemeral watts in Gaius

Signals advertises `Status.surfaces kind=telemetry` →
`http://tinybox.dev.vista.zndx.org:9410/v1/metrics` (OTLP JSON,
`Cache-Control: no-store`, 503 if DCGM down). Host exporter is :9400.

Gaius does **not** run DCGM. Engine `SignalsTelemetry` RPC: discover
that surface via `SIGNALS_ENGINE_TARGET` Status (or
`SIGNALS_TELEMETRY_URL`), one GET, parse `gpu.power.draw` /
util / energy / memory. Skip PROF/DCP. No disk, no queue.

- CLI: `/gpu watts`
- Observe: `GPU W` / `Infer W` (one scrape per ObserveStatus)
- UI: chrome strip `/api/gaius/v1/watts`, poll 5s only while visible
- Guru: `#EP.00000017.NOTELEMETRY`

Needs engine recycle (new RPC) and a gaius-ui rebuild (client proto).
`salience_per_watt` is null until FeatureTape exists.
