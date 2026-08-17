# Proto carries the caller's clock

Do not keep timezone in the UI only. Append-only:

- `zndx.engine.v1.CompleteRequest.timezone` + `clock_json`
- `AgendaListRequest.origin` + `timezone`
- `AgendaCreate` / `AgendaCard` / `AgendaUpdate.timezone`

List windows and item calendar days use the IANA zone.
Guru `#AG.00000009.BADORIGIN`, `#AG.00000010.BADTZ`.
Asset `0.2.18-proto-clock`. Engine recycled (thinking reloading).
