# signals.target complete refresh

Operator doctrine: `systemctl restart signals.target` is a full group
recycle (stop then start), not a surgical start of failed units.

Gaius wrappers now wait for Engine/Status **and** board UI `:9890`.
`gaius-ui` pins `PGPORT=5444` so devenv's allocator cannot leave the UI
waiting on `:5445`. Scheduled-task catch-up no longer blocks daemon start.

Signals: `just signals-restart` + `signals-refresh.service` verify every
enabled member. Atelier is currently `failed` (`:50251`); a refresh will
honestly fail until that peer binds.
