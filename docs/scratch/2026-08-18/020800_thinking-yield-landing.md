# Landing: productive yield of thinking watts

Depart from TUI 19×19 / κ-at-cursor as the hero. The web landing
should show **what the 27B did**, not occupancy. Parked VRAM is free;
inference is the meter.

Visual references (do not restyle away from these):

- `build/elk_01.png` — Elastic Discover: **horizontal** time histogram
  above a document table. Query bar. Familiar ops chrome.
- `build/2026-08-17-1007_graph.zip` (Theo / @kirbytheodor):
  - `graph-01` — temporal trail `[a]` dashed-mapped onto a contemporaneous
    state graph `[b]`. Correspondence lines are the product.
  - `graph-02` — “change over time” trail **plus** a stack of diamond
    **point-in-time** slices. State evolution is a byproduct of the trail,
    not a second system.
  - `graph-03` / `graph-04` — traversable project lineage; **Record** vs
    **State**; hyperedge blobs (Mechanism / Mutant / Assay). Color regions
    group a lineage, not a HUD.

## What we actually have

- Thinking Completes on 0–3 (real tokens; split `tokens_in`/`tokens_out`
  now recorded at `BackendRouter.route` — recycle engine to scrape).
- CLT is **Qwen3-1.7B** (light), ~115 / 20 480 sparse features, engine `CLT` RPC.
  Collection `gaius_clt_latent_thoughts` is empty today (0 points).
- TDA + Ollivier–Ricci already run on **card embeddings**, not on activations.
- No circuit-tracer hook on 27B today. Do not pretend 27B internals.
- Power: consume **dcgm-exporter** from Signals
  (`https://github.com/nvidia/dcgm-exporter`). This Prometheus (`:9090`)
  has no DCGM series yet. Do not add a DCGM client here.

## Layout (familiar above the fold, geometry below)

```
┌─────────────────────────────────────────────────────────────┐
│  ELK Discover strip (full width, above the fold)            │
│  query · Auto interval · histogram of Completes             │
│  stacked: heavy / medium / light  (duty, not occupancy)     │
│  optional overlay: DCGM W once Signals scrapes it           │
├─────────────────────────────────────────────────────────────┤
│  Document table (same time window)                          │
│  @timestamp  class  in/out  ms  artifact  (thought/hop/…)   │
└─────────────────────────────────────────────────────────────┘
┌──────────────────────────────┬──────────────────────────────┐
│  [a] trail (time →)          │  [b] state at playhead       │
│  Completes as a decision DAG │  one diamond slice:          │
│  dashed correspondence ───→  │  CLT co-activation graph     │
│                              │  + PySR curve on same domain │
└──────────────────────────────┴──────────────────────────────┘
  Record | State     (graph-03/04 tabs)
  State = blob-grouped lineage (thoughts, agenda hops, zettels)
```

The histogram and the CLT stack share **one time domain**. Brushing a
bar sets the playhead; the diamond stack is that bar’s slice plus
neighbors. Do not invent a second clock.

## Layers (build in this order)

**A. Yield tape (ops).** Event stream of Completes: class (heavy / medium / light),
ms, tokens_in, tokens_out, what came out (thought, agenda mutation, chart, zettel).
This is the ELK table. Engine-first: persist `InferenceYield` from
`VLLMController.complete`.

**B. Product, not occupancy.** Last N thinking *artifacts* with elapsed
watts-as-time. “23 s → this thought / this hop.” Links into Summary / Ask.
Until DCGM lands, watts-as-time is honest; joules/token is a later column.

**C. CLT as a probe, not a HUD.** Activations from **light**, or from
running 27B *output text* through light CLT as an interpreter (label as
probe, not as 27B internals). One time-slice = one Complete (or a 30 s
bucket). Nodes = active features (~115). Consensus features across a
session become the persistent `[b]` graph.

**D. ORC + TDA on the feature graph.** Nodes = CLT features, edges =
co-activation across Completes. κ = bottleneck vs expansion of the week.
Persistence = motifs that survive. This replaces the Go board as the
geometry, not as the homepage chrome. Lives in the **State** tab.

**E. PySR last, on low-d summaries, same time domain.** Symbolic
regression of `tokens_out ~ f(prompt_len, tools, class)` or
`feature-density ~ f(domain)`. Never on 20 k-d raw activations. Engine
job (Julia), hall-of-fame as a zettel. Only surface an equation that
beats a linear baseline. Draw it as an annotation on the histogram /
trail — not a third competing plot.

## Aesthetic

Familiar Discover chrome on top (histogram + table). Cutting-edge
underneath: temporal trail ↔ stacked state slices, correspondence
dashes, blob-grouped lineage. CAD minigrids stay in a lab view.

## CLT tabulation (the reason this is not entropy counting)

The Discover table is **not** tokens and heat. It is a windowed
histogram of **sparse feature activations**, two streams, same clock:

| stream | source | meaning |
|---|---|---|
| **inflow** | `content_items` title+abstract (`fetched_at`) | what ArXiv / bioRxiv / FMP / blogs brought in |
| **thought** | cognition thoughts, card summaries, real summarization | what agents said about that text |

Windows: 1 m / 1 h / 1 d / 7 d (ELK Auto interval). Columns: feature
label (or `Lxx F#####` until labeled), stream, count, mean activation,
example docs. Brush a bar → those features + those docs.

Live foundation (2026-08-18): ingest **is** running (`arxiv_cs_dc`
133 items / 36 h, 282 KB paths this week). `gaius.zndx.org` is **not**
— last published card 14 Mar, `publish_cards` ships 0, `article_curate`
blocked on `#YK.00000005.DISK`. Cognition writes 0 thoughts. CLT
import is broken (`HF_HUB_ENABLE_HF_TRANSFER`). First productive
paint: batch-probe last-week abstracts on parked light, persist
`FeatureTape`. Do not wait for the public site to thaw.

## High-value watts (what the landing must make obvious)

A Complete is **yield** only if it leaves a queryable artifact (thought
row, zettel, agenda hop, CLT slice, chart). Decode at 100 % SM / ~110 W
with no row in `cognition_thoughts` is **generative noise**.

Do not start medium/light just to fill 4–5. Parked is correct. Use GPU 4
for a CLT probe when we want understanding, not another chat replica.

## Out of scope for v1

PySR on the hot path. Fake 27B CLT. Another occupancy gauge. DCGM
exporter in this repo.
