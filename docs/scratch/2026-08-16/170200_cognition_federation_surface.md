# Cognition page: federation surface (AgentsView grammar)

`/cognition` is no longer a `<pre>` dump. Native gaius-ui (Askama +
vanilla JS + Keiretsu) using AgentsView dashboard density:

- left rail = thought stream (not Claude/Codex sessions)
- six stats, year heatmap, day bars, hour-of-week, top-by-salience

Data is engine `CognitionSurface` over `cognition_thoughts` /
`cognition_cycles`. Empty windows are zeros. Missing pool/service
fail-fast (`#COG.00000024`–`29`). CLI: `/thoughts surface [days]`.
