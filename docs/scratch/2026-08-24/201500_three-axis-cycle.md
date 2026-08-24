# Cognition cycle is three FIFOs, then Aperture

`/ambient cycle` was HN fetch + synthesis. Prospects and Publishing
rolled on their own 60s loops, so a one-shot cycle could synthesize
an empty FMP/cards FIFO.

The cycle now, independently:

1. Ambient HN fetch + compact
2. Prospects ingest + compact
3. Publishing ingest + compact
4. Aperture MaxSim over all three
5. Thinking synthesis → Agenda (standing W34 brief)

One axis failing does not skip the others. Missing an axis is
`#PS.00000008.NOATTACH`, not a silent empty buffer.
