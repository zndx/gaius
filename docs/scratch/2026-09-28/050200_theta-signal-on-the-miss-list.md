# Theta on the miss list, not its own token

`theta_not_caught_up` was a second spelling of `miss:theta_cycle` inside `Endpoint.detail`. Callers had a Theta-specific flag and no schema for it. Status now sends guru plus `miss:<kind>,…` only.

A completed ledger row with both infer counters at zero is `#THETA.00000013.CONSFAIL`, not caught up. Week 38 row 23 was that blank pass and is now `failed`. A later week closes only when the counters record a result.
