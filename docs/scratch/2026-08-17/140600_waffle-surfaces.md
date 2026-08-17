# Chrome waffle — federated primary UIs

Replace `19×19 · one next question` with a 9-dot waffle. The rail lists
peers that **advertise** `Status.surfaces` kind=primary. Empty is honest.

Discovery is S2S: `SIGNALS_ENGINE_TARGET` / configured PEERS → Status +
one-hop ServerQuery PEERS. No canned Signals/Aegir/Atelier URL list.
Gaius `/peers` and `Gaius/FederationSurfaces`. Signals Status advertises
`SIGNALS_UI_URL` (default `:9889`).
