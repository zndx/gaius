# Sitrep empty was the 30s vLLM HTTP timeout

MCP `ThetaSitrep` succeeded (~0.6s). The follow-up `Engine/Complete`
hit `httpx.AsyncClient(timeout=30)` and leaked `error=""` as success.

Recycled orphaned engine (process-compose `gave_up`). New process logs
`http read timeout=180s`. Post-sitrep Complete: 43.3s, 1586 chars,
visible report. Would have died at 30s on the old client.
