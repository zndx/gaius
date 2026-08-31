# Cognition Phase 3 (federation-wide) + 2D contributions calendar recovery

## 2D calendar (user course-correction)

The Phase-1 calendar degraded to a 1-row strip whenever the Activity chart
resolved to week/month grain (365d/all windows) — losing the GitHub-style
2D shape (day-of-week vertical axis × full-year week columns) that defines
this display. Fixed per AgentsView `Heatmap.svelte`:

- **Grain-independent**: the calendar always renders DAILY cells. When the
  surface answered coarser (week/month), `paintCalendar` refetches the SAME
  range + filters at `bucket=day` (loadVersion-guarded, cached by query
  string). Only if the server degrades day away (>MAX_BUCKETS span) does it
  fall back to the honest strip.
- **AgentsView conformance**: Sunday-start week columns; row labels
  `["","Mon","","Wed","","Fri",""]`; month labels above the grid where a
  new month lands in rows ≤3; fluid `cellStep = clamp((width-labels)/cols)`
  with proportional gap so a year fills the panel at any width.
- Verified server-side: `window=365d&bucket=day` → interval=day, 366
  buckets; even `all` currently resolves to day (188 days of history).

## Phase 3 — federation-wide (makes the page's name true)

- **signals-protocol (additive v1, 2026-08-31)**: `SERVER_QUERY_KIND_COGNITION
  = 10`; `ServerQueryResponse.cognition = 12` (`CognitionHint` +
  `CognitionActivityBucket`/`CognitionStreamHint`). A peer without a
  cognition unit leaves the hint unset — honest, never an error.
- **Gaius answers**: zndx servicer enriches kind=COGNITION async (SCHEDULES
  pattern) from `cognition_service.surface(window="30d")` — running,
  totals, buckets, stream mix.
- **Collector**: `s2s.collect_peer_cognition` — self row first, then the
  PEERS BFS (collect_peer_surfaces rules); peers answering an empty hint
  are absent from the result.
- **RPC**: `GaiusService/FederationCognition` (reuses `CognitionBucket` /
  `CognitionStreamCount`); gaius-ui `/api/gaius/v1/federation/cognition`.
- **UI**: Federation panel above Activity — one lane per answering engine:
  project chip, running dot, ~30d sparkline, thoughts/cycles counts,
  last-cycle recency; the gaius lane outlined as self. 120s
  visibility-aware refresh. Hidden when nothing answers.

**Signals-session flag**: their signals-protocol submodule now lags the
2026-08-30 PRODUCTS additions AND this kind=10 — bump before signals-ui
mirrors any of this.

Phase 2 close-out note: production restart validated 6/6 on :9890 (SSE
200 via the lazy mpsc bridge, drawer content+chain) before Phase 3 landed.

## Waterfall dropped (user course-correction)

The Waterfall strip was redundant with the engine-metrics waterfall
elsewhere and visually dense; removed the panel, painter, and 5s poll from
the Cognition page (the `/api/gaius/v1/cognition/waterfall` route stays —
it is not page-owned). The freed real estate hosts cognition-oriented
content instead — immediately, the Phase-4 reasoning corpus panel.

## Phase 4 — reasoning corpus (hx.cot_reasoning)

Reasoning traces are the product; the page now surfaces the corpus:

- `engine/services/cognition_corpus.py`: PyIceberg reader over
  `hx.cot_reasoning` (engine env already carries RustFS keys + Polaris URI
  via gaius-engine.sh). List scan = light fields only (no prompt/trace
  bodies; flow_name+generated_at stay selected — partition-source gotcha),
  newest first; `fetch_trace(id)` returns everything incl. parsed
  `reasoning_layers`. Sync PyIceberg wrapped in `asyncio.to_thread`.
  Gurus #HX.00000004.CORPUSREAD, #HX.00000005.NOTRACE.
- RPCs `CognitionCorpus` / `CognitionTrace` (+ UI proto subset, numbers
  matched); gaius-ui `/api/gaius/v1/cognition/corpus` + `/trace`.
- UI: "Reasoning corpus" panel (subject, flow/step/run, technique, model,
  out-tokens, latency, recency, "N layers" badge); click opens a trace
  drawer rendering each tagged dual-constraint layer (model|method ·
  producer · tokens · chars) plus the full reasoning trace and decision
  output. `output_tokens` is the honest volume signal (no text weighing).
- Live smoke pre-restart: 3 traces in 60d; first = dual layers
  model 17,030 ch + method 1,710 ch (5,244 tok) — the run-1729 capture.

Phase-3 validation (recorded): federation lanes answered — 1 lane (gaius,
running, 60 thoughts/30d, interval=day, 31 buckets, 3 streams); peers are
honest absences (no cognition units yet). Calendar day-grain 366 buckets;
SSE + drawer regressions green.
