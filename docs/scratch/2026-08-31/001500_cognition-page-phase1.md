# Cognition page Phase 1 — scale-aware Activity (AgentsView three-tier port)

Session log, 2026-08-31 (early). Implements Phase 1 of the approved
comprehensive Cognition-page plan (three Explore-agent reports: AgentsView
feature inventory, prototype dissection, federation data catalog).

## The flagship fix

The prototype truncated and never re-scaled: a hard `Math.min(windowDays,
42)` clamp on the day bars, a fixed-11px 7×N year grid (~25px wide on a
7-day window), day-only granularity end-to-end, per-panel max-ratio color
scales, unnormalized hour-of-week, and a one-shot fetch. All replaced with
the AgentsView **three-tier** pattern (MIT; math ported, framework skipped —
gaius-ui stays Node-free):

1. **Server resolves the bucket unit from range duration** —
   `gaius/engine/services/cognition_buckets.py` (pure, 19 tests): window
   grammar `24h/7d/…/all`, policy ≤48h→hour, ≤14d→6h, ≤180d→day,
   ≤1100d→week, else month; overrides `hour|6h|day|week|month`; over-budget
   ranges DEGRADE (better than upstream's hard fail); calendar tiling (UTC
   midnight / ISO Monday / month-first) with clipped half-open windows;
   zero-filled folds. `cognition_surface.py` rebuilds the series with
   `date_trunc` at the aligned grain and echoes
   `interval/range_*/effective_end/bucket_seconds`; per-bucket
   thoughts/cycles/tokens/salience_max.
2. **Client positions buckets by their REAL bounds** — new
   `assets/js/cogchart.js` (niceScale 1/2/5 ladder, quartile heat levels,
   unit-aware ticks) + rewritten `cognition.js`: true-width SVG bars,
   ResizeObserver re-layout, partial-range shading, cycles overlay
   (previously a dead wire field), popstate-correct minimal URLs,
   stale-response guard.
3. **Axis/labels switch on the unit** — fraction ticks w/ real UTC times for
   hour/6h, Monday starts for day, month starts for week, thinned month
   labels; tooltips carry range + thoughts + cycles + tokens.

Calendar panel: fluid cells (`--cog-cell` var; width-responsive like the
AgentsView Heatmap) for day interval, bucket strip for week/month, hidden
for sub-day. Hour-of-week normalized to per-week rates with quartile levels.

Proto: `CognitionSurfaceRequest{window,bucket,from_ms,to_ms}` +
`CognitionBucket` + response fields 21-26, mirrored in the gaius-ui client
subset (numbers matched); `days` legacy field retained but empty.

## Validation

- Unit: 28 surface+bucket tests (policy boundaries, calendar tiling incl.
  ISO-Monday/month walks, zero-fill, half-open abutment, legacy gurus).
- Live after a real `systemctl restart gaius.service`: every window resolves
  the right interval and FILLS the panel — 24h→hour(25), 7d→6h(29),
  30d→day(31), 90d→day(91), 365d→week(54), all→week; overrides
  30d/hour(721), 365d/month(13); buckets abut exactly; legacy
  `window_days` still answers; **bucket sum == window total (472 == 472)**;
  page + assets 200.

## Lessons (paid for tonight)

- A backgrounded `cargo build … | tail` masked a REAL failure (E0063) with
  exit 0 — always `set -o pipefail` around builds. The failure itself was
  dual-constraint fallout: zndx `CompleteRequest` literals in
  `gaius-ui/src/engine.rs` needed the new `capabilities` field.
- A degraded "daemon repair" restart kept the Aug-28 gaius-ui binary
  serving, which presented as null new-fields in the JSON. After any
  gaius-ui .rs/proto change: check `target/release/gaius-ui` mtime AND the
  running pid's start time.
- Engine boot registers `cognition_service` ~4½ min in (after db_pool) —
  the surface 503s (#COG.00000024.NOSVC) until then; validation must wait
  for it, not for :50051.

## Pending (approved plan)

Phase 2 (brush drill-down, thought drawer + chains, SSE ticker via
SubscribeCognition, waterfall strip) · Phase 3 (SERVER_QUERY_KIND_COGNITION
+ collector + per-peer lanes) · Phase 4 (hx.cot_reasoning corpus panel).

## Phase 2 (same session) — depth: drawer, live, brush, waterfall

- **Thought drawer**: new `GaiusService/CognitionThought` RPC — full
  `content` (never truncated), confidence/novelty/status/domains/
  generator_model/tokens_used, and the ancestor chain via the
  `predecessor_id` recursive CTE (ported from the MCP get_thought_chain).
  Rail/top rows open the drawer; chain rows navigate; "Open in Summary"
  keeps the deep link. Guru `#COG.00000035.NOTHOUGHT`.
- **Live SSE ticker**: gaius-ui bridges the engine's existing (previously
  unconsumed) `SubscribeCognition` stream to
  `/api/gaius/v1/cognition/events`. Lesson: the engine stream yields
  nothing until the first cognition event, so the bridge must send HTTP
  headers immediately and connect upstream lazily (spawn + mpsc channel,
  `hello` event, KeepAlive comments) — the first implementation hung the
  response awaiting the subscribe. Client: EventSource with live dot,
  thought events prepend to the rail, `cycle_end` triggers a panel refresh;
  60s visibility-aware poll as fallback.
- **Brush range selection**: pointer-drag on the Activity SVG →
  `from_ms/to_ms` refetch (server-side membership; buckets re-resolve for
  the sub-range), URL-persisted, clear-chip. Keyboard nav deferred.
- **Waterfall strip**: the already-routed
  `/api/gaius/v1/cognition/waterfall` finally painted — per-row
  auto-contrast canvas, 5s visibility-aware poll (23 channels live,
  driver=warehouse).
- Rendered previously-dead fields: `current_task` on the stats tile.

Validated on a throwaway instance against the live engine (fast iteration,
no restart round-trip), 6/6: drawer content+chain, rich fields, not-found
503, SSE 200/event-stream, waterfall 23×240 matrix, brush sub-range
honesty. Production restart follows.
