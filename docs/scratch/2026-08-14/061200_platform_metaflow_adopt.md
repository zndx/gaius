# Adopt Signals platform Metaflow from Engine/Status

When `zndx.engine.v1.Engine/Status` on `:50551` reports `project=signals` and a
healthy `metaflow` (preferred) or `scheduler` (YuniKorn today) capability, and
`:30180/ping` is pong, Gaius flows use `config/metaflow/platform.json` (or
`$SIGNALS_ROOT/config/metaflow/platform.json`). Federated + ping down is
`#MF.00000006.NOPLATFORM` — no Tilt fallback. Standalone (Status unreachable)
keeps `local.json`.

`gaius-engine.sh` now sources repo + parent `.env` so system.slice children
see XAI/BRAVE/CEREBRAS (direnv `source_up` does not run under the unit).
