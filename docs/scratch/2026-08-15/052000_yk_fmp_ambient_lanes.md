# FMP and Ambient on Signals leaves

FMP ingest is bursty (API comes and goes). Ambient is a RAM FIFO that
must not hit disk. Both can later use GPU for agentic summarization.

Gaius stamps existing Signals leaves (no `root.gaius`, no new YAML):

| Lane | Queue | GPU | Lifetime |
|------|-------|-----|----------|
| FMP check | `root.external.rate-metered` | 0 | admit → delete |
| Ambient buffer | `root.internal.compute` | 0 | `gaius-ambient` until `/ambient stop` |
| Summarization / docling | `root.internal.inference.extract` | 1 | bind the one extract token |

`#YK.00000004.ENVELOPE` is per queue. FMP and Ambient never reuse the
extract `app-id`.
