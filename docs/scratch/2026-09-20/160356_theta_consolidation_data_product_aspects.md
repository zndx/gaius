# Theta Consolidation Data Product — Aspects

The authentic Theta Consolidation data product has never existed. The
`theta_consolidation_runs` row is a **job ledger**. This note considers
the intended Signals Data Product **Aspects individually**, starting
from the Agenda-materials shape already live for AgentRTC.

Not implemented. `docs/current` still describes what runs today.

## Signals vocabulary (what "Aspect" means here)

Signals does not mint a proto type named Aspect. A Data Product is
already a bundle of independently reviewable planes:

| Plane | Where | Role |
|-------|--------|------|
| Identity | `product_id = {peer}.{domain}.{name}` | Stable name the peer publishes |
| Catalog facts | `details.a` (`peer`, `title`, `kind`, `leaf`, `agent_focus`, URIs, run ids) | Latest-wins inventory |
| Assertion epoch | `tx` (UUIDv7) | One create / update / maintain |
| Object bytes | RustFS (`s3://signals-dataproducts/{peer}/…` **or** `s3://{project}/resources/…`) | The thing a fact points at |
| ACP observation | `hx_reasoning` quality / lineage / delta / nominal | History is agent-facing |
| Discovery | `ServerQuery kind=PRODUCTS` → `ProductHint` | Hint only; warehouse is SoR |

The first draft of this note treated “Aspect” as an object/claim plane of
one product. That mixed three things the AgentRTC wiki keeps apart.
Signals still has no proto type named Aspect; the warehouse planes above
are how a product is *inventoried*. What a product *promises* is the
wiki vocabulary (NONNORMATIVE) in the next section.

Contract: [signals-protocol `data_products.md`](https://github.com/weathership/signals-protocol)
(in-tree: Signals `components/signals-protocol/specification/protocol/data_products.md`).
Peer playbook: Signals `docs/current/src/operations/peer-data-products.md`.

Intended identity (not seeded, not in `declared_products`):

```text
gaius.theta.consolidation
peer: gaius
kind: cognition
leaf: root.internal.inference.embedding   # LIGHT / ColBERT-Zero
flow: ThetaCycleFlow
```

`gaius.cognition.outputs` is a different seed. Do not overload it.

## Wiki vocabulary (NONNORMATIVE)

Source: Hermes AgentRTC wiki
`current/design/data-product-aspects.md` (sessions as data products)
and the seed zettel
`scratch/2026-09-20/211944_a-useful-adaptation-is-to-make-data-product-aspect.md`.
Not protocol. Not a Signals warehouse table. Considered here because
Theta’s booked session *is* the first concrete instance of that pattern.

| Concept | Role | Instantiable? | Example here |
|---------|------|---------------|--------------|
| **Data Product** | Concrete entity: data + interface + operational commitments | Yes | `gaius.theta.consolidation`; a Theta **session**; the Theta **session series** |
| **Aspect** | Reusable semantic **contract** (properties, constraints, required evidence) | **No** — \(A \cap P = \varnothing\) | `PreparedSessionMaterials`; `Transcript` (sealed vs in-force); `IdentifiableProductAspect` |
| **Profile** | Versioned composition of aspects for a product class | Usually no | (none yet — `SessionSeriesProductProfile` is an open question on the wiki) |
| **Evidence** | Proof of a claim, or an operational observation | Yes | `s3://gaius/resources/<id>/prompt.md`; week \(X_i\); sealed transcript; `hx_reasoning` |

An Aspect does not denote a product. `prompt.md` on rustfs is **evidence**
that a session satisfies `PreparedSessionMaterials`, not “the aspect.”
`hx_reasoning` quality / lineage / delta is the Signals-shaped
**claim–evidence** pair (`AspectClaim` `supportedBy` an artifact). Empty
`hx_*` is a declaration without proof — the failure the wiki exists to
prevent.

The 12-aspect vocabulary stays architecture-neutral (no “mesh,” no
“federated” in the aspect names). Theta needs at least:
`Identifiable`, `Discoverable`, `ContractedInterface`, `Accessible`,
`QualityAssured`, `Observable`, `Provenanced`, `LifecycleManaged`,
`CostTransparent` (LIGHT economics), `Interoperable` (strategy pin /
SKOS↔OWL). `Governed` / `RiskManaged` when the live aperture change is
in play (promotion is a control, not a git convenience).

### Sessions as products (the wiki’s worked example)

The session **series** is a **distinct data product** — the union of
artifacts consumed and produced. Two session-level aspects so far:

1. **Prepared session materials** — *input*. Pre-existing, authored
   before the run, **immutable** from the session’s point of view.
   Contract ~ `ContractedInterfaceAspect` + `ProvenancedProductAspect`.
2. **Transcript** — *output*. Emergent; **in-force** while the session
   is live, then **seals**. Contract ~ `ProvenancedProductAspect` +
   `ObservableProductAspect`. Consumers must not read an in-force
   transcript as final. Live failure:
   wiki `scratch/2026-09-20/212213_friction-discover-reliability-catch-up-appended-to-wrong-session.md`.

**The test** for a level being a product: does it own aspects of its
*own*, or is it a view? A series that only lists sessions is a view.
The moment it owns the consolidated thread (running decisions, standing
prompts, cross-session continuity, its own access rules) it is a
product. Theta’s weekly discourse **owns** the promotion decision. That
answers this note’s earlier “one product vs sibling” question: the
session series is a sibling product, not an object plane of
`gaius.theta.consolidation`.

Self-similarity (Protobuf framing, still NONNORMATIVE): an aspect type
is a **repeated typed entry** in an enclosing envelope. Materials →
session → series. Field numbers and message names *are* the contract.
Thin wire: S3-rooted path + typed contract; bytes stay in object
storage; validate the pointer, then dereference. That is already how
`ServerQuery RESOURCES` works.

**Invite `can-have-attachment`** is an **upper bound**: declaring
attachment possible and supplying none is valid; declaring none and
then supplying one is a violation. Holding a week with an empty
RESOURCES list is therefore nominal *if* the invite declared the
capability. Two pointer forms: URL-embedded session-start metadata
(machine, Connect) vs an **attachment set** (human, pre-session prep).

Open on the wiki and inherited here: is `PreparedSessionMaterials` a
flat record or nested sub-aspects? Theta wants the nested fork —
salient theta-cycle vs salient shadow-strategy are sub-aspects the
evolving `prompt.md` surfaces, not a second product.

### Relabel of the planes below

What this note still calls A–E are **evidence artifacts** of products,
not Aspects. Kept numbered so the rest of the page stays walkable.

| Label | Wiki class | Belongs to |
|-------|------------|------------|
| A `prompt.md` / `materials.md` | Evidence of `PreparedSessionMaterials` | booked **session** (input, immutable) |
| — transcript | Evidence of `Transcript` | booked **session** (output; seal at close) |
| — invite attachment capability | `can-have-attachment` (upper bound) | invite / series contract |
| B week \(X_i\) | Evidence of Quality / Provenance | `gaius.theta.consolidation` |
| C CLT + MaxSim week binding | Evidence of Interoperable / Quality | consolidation |
| D KB week-block | Evidence of Quality (cortical write) | consolidation |
| E shadow aperture delta | Evidence of a **candidate** Risk/Governed claim | consolidation; live membrane only after **sealed** session |
| F `hx_reasoning` | `AspectClaim` + `supportedBy` | every product `tx` |
| session series | **Product** | owns standing prompts, promotion decisions, continuity |
| ledger row | not a product, not an aspect | Nautilus coverage |

Promotion claim: `AspectClaim(consolidation, live-membrane-change)`
is `supportedBy` a **sealed** Theta-session transcript plus the
cherry-pick sha. An in-force call must not promote. Week close must
not promote.

## What is not an Aspect of this product

**`theta_consolidation_runs`.** Coverage, job health, miss / caught-up,
which UTC days encoded. Same role as `gaius.nautilus.backlog` (kind
`ledger`): Nautilus and sitrep may alarm on it. Completing the row means
LIGHT coverage is in, not that information was consolidated.

The daily cognition **Agenda brief** (`agenda_brief.py`, producer-end +
day rollover) is also not this product. That brief is a rolling sitrep.
The Agenda **session** below is a **booked** session whose origin is
Gaius and whose named agent is Theta — a product in the session series,
carrying prepared-materials evidence and, after close, a sealed
transcript.

Daily LIGHT increments (`zndx.window_date`) are **work units**. They
refine week-level aspects; they are not Aspects and not a ShadowStrategy.

---

## A — Prepared session materials (evidence; input aspect)

**First fully specified evidence plane** of the booked Theta session.
Wiki contract: `PreparedSessionMaterials` — immutable from the
session’s point of view. Shape: the AgentRTC supporting-materials
corpus devised 2026-09-19.

### Shape (already in the protocol)

| Piece | Owner | Where |
|-------|--------|--------|
| Calendar row | Gaius Agenda store | `Engine/PutAgendaItem` — title, times, public lede, `origin_project`, `origin_agent`. **Not** prompt/materials. |
| Session prompt | Origin engine | rustfs `s3://<origin_project>/resources/<zettel-id>/prompt.md` |
| Supporting materials | Origin engine | `…/materials.md` (and further named objects) |
| Fetch | Connect | `ServerQuery kind=RESOURCES` against the **origin**, `note_id` = agenda item id. Empty is honest. |

Protocol: `engine_grpc.md` AGENDA vs RESOURCES; Hermes
`hsengine/engine/resources_store.py`, `agenda_put.py`, `agenda_deck.py`.

### Theta binding

| Field | Value |
|-------|--------|
| `origin_project` | `gaius` |
| `origin_agent` | `theta` |
| Object prefix | `s3://gaius/resources/<zettel-id>/` |
| When minted | When the **week** consolidation is ready to be discussed (on-time Monday close, or when Monday–Sunday LIGHT coverage has refined the week aspects — not on each daily increment) |
| Calendar | Gaius writes its own Agenda row (self-Put or `create_item`). Hermes `_AGENTS` allowlist is for Hermes-origin puts and does not name Theta. |

Connect already asks `origin_project` for RESOURCES. Gaius does **not**
yet serve `SERVER_QUERY_KIND_RESOURCES`. Until it does, a Gaius-sourced
Theta session has a calendar row and no briefing body at Connect.

### What the objects are for

**`prompt.md` evolves.** It is not a frozen template. Its job is to
surface **salient sub-aspects** of:

1. **This week's theta-cycle** — what bound, what drifted, what the
   NVAR series did, which CLT/MaxSim links were new, which KG
   candidates were held, what the replaceable KB week-block changed.
2. **The evolving ShadowStrategy** — in Theta's context, the strategy
   that manages **controlled emergence of novel topics** at the
   ColBERT-Zero / Qdrant **content-item Aperture admission membrane**.

Salience is week-local. The prompt must not dump every sub-aspect every
week. A quiet membrane week surfaces drift and KB delta; a week with
aperture-admission candidates surfaces those deltas and asks whether
promotion is appropriate.

**`materials.md` is the briefing corpus** for that booked session. It
co-evolves with the cycle and with any emergent aperture-admission
shadow deltas (Aspect E). It cites the other aspects by URI; it does
not become the SoR for \(X_i\) or the lens snapshot.

This maps onto sdg-strategy **`components/voices/`** (agent-facing
surfaces) as the *family* of prompts, and onto this aspect as the
*instance* for ISO week \(W\). Voices live in the strategy repo;
`prompt.md` is a week product object.

### Quality / lineage / delta / nominal (this aspect)

| Review | Meaning |
|--------|---------|
| Quality | Booked session exists; `prompt.md` and `materials.md` are on rustfs under `gaius`; Connect RESOURCES returns them; public lede is calendar-safe (no dump of the deck). |
| Lineage | `slice_id` (ISO week), `strategy_id` (trunk and any shadow compared), `ThetaCycleFlow` pathspec, code sha, YK LIGHT claim, agenda item id. |
| Delta | This week's briefing vs last week's: which sub-aspects the prompt now surfaces; which shadow aperture deltas appeared or dropped. |
| Nominal | A week that completed LIGHT coverage **and** has discussable aspects yields a booked session. Holding (week still accumulating days) is not failed and not done. Missing the booked session after the week is ready is off-nominal for **this** aspect, distinct from a Nautilus miss on the ledger. |

### Critical coupling — discourse promotes the membrane

**The agenda discussion drives ShadowStrategy promotion.** Cherry-pick /
merge remains the strategy-repo mechanic (`external/sdg-strategy`:
trunk is the one-main lineage; a shadow is a branch). What was missing:
a **gate**.

```
week evidence ready (B–E)
        │
        ▼
book Gaius/Theta session  (series member)
  invite can-have-attachment (upper bound)
  A  prompt.md + materials.md  (PreparedSessionMaterials; immutable)
        │
        ▼
AgentRTC discourse — Theta named
  transcript in-force (must not promote)
        │
        ▼
session close → transcript seals
        │
        ▼
  promote? ──yes──▶ cherry-pick shadow → trunk
        │              materialize lens → live Qdrant aperture
        │              AspectClaim supportedBy sealed transcript + sha
        no
        ▼
  hold the shadow (still a branch; not live)
```

Agentic discourse **elevates** a shadow into the **active aperture
membrane** when it is appropriate to do so — and only from the
**sealed** record of that discourse. Week completion does not
auto-promote. A day's LIGHT increment does not promote. An in-force
call must not promote. Git history alone is not the gate: without
sealed discourse, shadows either rot or get merged by pipeline, both
of which violate **controlled** emergence.

The live membrane today is what ambient cognition already admits
through (`SdgAperture`, ColBERT-Zero MaxSim, unique topic). Promotion
changes that membrane (typically `lens/` C / τ / e / index; sometimes
voices). Effective aperture = `(C, regime params, e, index)` —
`strategy_id` equality is not sufficient (sdg-strategy aperture task).

### Live-tree gaps for prepared-materials evidence

- Gaius does not implement `SERVER_QUERY_KIND_RESOURCES`.
- Gaius does not write `s3://gaius/resources/…` (Hermes writes
  `s3://hermes/resources/…` for Ripley/Grok items).
- No Theta-origin `PutAgendaItem` / `create_item` at week close.
- Hermes `agenda_put._AGENTS` has no `theta` (irrelevant if Gaius
  originates the row).
- Architecture still called the SQL row "the product."

Do not stuff `prompt.md` into the Agenda zettel. That inversion was
already rejected for AgentRTC.

Empty RESOURCES after a declared `can-have-attachment` is valid
(holding). Empty RESOURCES after the week is ready to discuss is
off-nominal for this **evidence**, not a Nautilus miss.

---

## Transcript (evidence; output aspect) — was missing

The wiki’s second session aspect. Produced only once the session has
happened. **In-force** during the call (mutable stream); **sealed** at
session close into a document. Promotion of Aspect E into the live
aperture is `supportedBy` the **sealed** transcript, never the
in-force stream.

| Review | Meaning |
|--------|---------|
| Quality | Sealed object exists, bound to this session id, not appended to another session. |
| Lineage | Agenda item id, `origin_agent=theta`, Connect session id, start/end. |
| Delta | Decisions vs the prepared materials (what was promoted, what was held). |
| Nominal | Seal at **this** session’s close. Referencing another session’s in-force notes as this session’s open items is off-nominal (212213). |

No transcript store is specified yet. Do not reuse an unsealed AgentRTC
context pack as the record.

---

## Session series (distinct product)

Not a container and not a view over weeks. Owns: standing Theta
prompts (the evolving family in sdg-strategy `voices/`), the running
promotion thread, access rules for who may elevate the membrane,
cross-week continuity of shadow vs trunk. Member sessions are inputs
(`dp:consumesProduct`). Consolidation weeks are a **different**
product the series discusses.

Protobuf self-similarity (NONNORMATIVE): series envelope carries
`repeated` session entries; each session carries prepared-materials
entries and, once sealed, a transcript entry.

---

## Aspect B — Week centroid \(X_i\) (NVAR series)

**What.** One durable week vector in a **series of weeks**. Intent
(2025-12-23): \(X_i\) is the embedding centroid for temporal slice \(i\);
NVAR constructs \(O_\mathrm{lin}\) from delayed \(X_{i-ks}\) and predicts
drift. High deviation → consolidation urgency.

**Object plane.** A retained series on RustFS / warehouse (HDF5, parquet,
or Iceberg — pick one when implementing). Keyed by `slice_id` =
`YYYY-WNN`. Same week **replaces** \(X_i\) as daily LIGHT refines it;
it does not append seven day vectors.

**Not.** The in-process `ThetaDynamics.add_slice` running mean, nor the
jsonb `metadata.centroid` on the ledger row. Each Metaflow process
starts with empty history today, so urgency defaults to \(0.5\). That
is a staging estimator, not the series.

| Review | Meaning |
|--------|---------|
| Quality | \(X_i\) exists for the closed week; dimension matches ColBERT-Zero `agg` (ℝ¹²⁸); series has prior weeks so NVAR is defined. |
| Lineage | Encode pathspec, model pin (`lightonai/ColBERT-Zero`), thought ids in the window, `strategy_id`. |
| Delta | \(\|X_i - X_{i-1}\|_2\) and NVAR residual vs prediction. |
| Nominal | On-time: written at Monday close. Backfill: refined in place until the week is complete, then frozen as the week's \(X_i\). |

Without a durable series, "NVAR-mediated consolidation" is a name on a
stateless job.

---

## Aspect C — Week CLT incidence + MaxSim groundings

**What.** Discrete co-activation over `admitted_item × activation` for
the **week**, SKOS-resolved to HermiT-certified OWL IRIs, MaxSim-bound
to the aiming aperture. This is the pairing substrate BERTSubs scores.

**Object plane.** CLT `activation` rows and groundings already have the
right grain in code (`agents/theta/clt_incidence.py`). The aspect is
the **week-level binding set**, replaceable as daily increments merge
into the week — not a stack of seven day-shaped link sets published as
the product.

| Review | Meaning |
|--------|---------|
| Quality | Pairs are SKOS→OWL against `sdg-ontology.owl` only; no classes minted from thought text. |
| Lineage | CLT model, aperture collection, τ, `strategy_id`, thought/item ids. |
| Delta | New / dropped co-activations vs the prior week; disagreement vs a **shadow** aperture on the **same** week. |
| Nominal | BERTSubs runs on the week's accumulated pairs, not on a single day's extract treated as a release. |

This aspect is where **novel topics** first become visible as
admitted-set composition, before anyone changes the membrane.

---

## Aspect D — Replaceable KB week-block

**What.** Cortical write: wikilinks and `[action:search]` wrapped in
`<!-- BEGIN THETA_AUGMENTATION … -->` / `END`, keyed by `slice_id`.
Intent: spend LIGHT so recall improves; economic gate, not a job
counter.

**Object plane.** The markdown KB itself (zettelkasten). One block per
`(document, slice_id)`. Daily refinement **replaces** the week's block;
it does not append a second day's block.

| Review | Meaning |
|--------|---------|
| Quality | Block is keyed and replaceable; holdout markers intact; not a second copy of yesterday. |
| Lineage | KG policy state, BERTSubs scores, `slice_id`, cycle id. |
| Delta | Effectiveness / recall — followed links, not `documents_augmented > 0` on the ledger. |
| Nominal | Overwatch/objective `theta_cycle` should gate on this aspect (and B/C), not on the ledger count. |

Today this is the only partial product the cycle actually writes, and
it is still scored as a ledger side-effect.

---

## Aspect E — ShadowStrategy aperture-admission delta

**What.** A **candidate** change to the content-item admission membrane,
not the live lens. ShadowStrategy remains a **branch** of
`external/sdg-strategy` (lens / voices / knobs / targets). In Theta's
context the shadow's job is **controlled emergence of novel topics**:
which passages/items ColBERT-Zero MaxSim will admit into Qdrant this
week vs last, under `(C, regime params, e, index)`.

**Object plane.** Strategy-repo diff (git) plus a week-level **admission
delta** object: trunk vs shadow on the **same** ISO week — admitted-set
symmetric difference, off-domain share, canary probes, risk of aperture
damage (neighbor concepts losing separation). Bytes on
`s3://signals-dataproducts/gaius/theta/…` or a named object beside
`materials.md` (`aperture-delta.md` is a briefing citation, not the SoR).

**Not.** A finer clock. Not a day window. Not auto-applied at week close.

| Review | Meaning |
|--------|---------|
| Quality | Delta is computed on week artifacts (B/C), same `slice_id`, two `strategy_id`s; effective aperture identity includes e and index. |
| Lineage | Branch point sha, both manifests, both lens snapshots. |
| Delta | This week's shadow vs last week's shadow, **and** shadow vs trunk this week. |
| Nominal | Candidate only. Live membrane unchanged until a **sealed** Theta-session transcript supports the promotion claim. |

Promotion target is the **active aperture membrane** (repo → runtime
materialize of `lens/`). Coupling: sealed session transcript, not the
prepared-materials evidence and not week close.

---

## Aspect F — History (`hx_reasoning`) — not a separate object plane

Every `tx` on `gaius.theta.consolidation` must carry quality / lineage /
delta / nominal. This is the Signals History facet of the **product**,
not a sixth blob. The reviewing agent observes; it does not
re-inventory. `agent_focus` (once seeded) should tell that agent to
read evidence A–E plus the sealed transcript, and to treat the ledger as coverage only.

Empty `hx_*` would make History a changelog of job rows — the failure
mode this product must not repeat.

---

## How the products co-evolve (week loop)

```
UTC days (work units, LIGHT, max_active_runs=1)
        │  refine in place
        ▼
  B  X_i (week centroid, replace)
  C  CLT + MaxSim (week binding set, merge)
  D  KB week-block (replace by slice_id)
  E  shadow vs trunk admission delta (if a shadow is in play)
        │
        ▼
  week ready ──▶ book session (series member)
                     A  prompt.md / materials.md (immutable input)
                     invite attachment set (human prep) + Connect URL (machine)
        │
        ▼
  discourse (transcript in-force)
        │
        ▼
  seal transcript ──▶ promote E? ──▶ live membrane (lens materialize)
```

Prompts and briefing **co-evolve** with the cycle and with E. The
session is not a notification that the DAG succeeded. The series owns
the standing prompt family and the running promotion thread.

## Declared vs live (honest)

| | Live today | Intended |
|--|------------|----------|
| Product id | none (`declared_products` has prospects + cot_reasoning only) | `gaius.theta.consolidation` **and** a Theta session-series product |
| Warehouse row | none | `tx` + `details` + `hx_reasoning` per week / per sealed session |
| A prepared materials | Hermes RESOURCES for Ripley/Grok; Gaius calendar-only | Gaius/Theta booked session + `s3://gaius/resources/…` |
| Transcript | none (context pack is not a sealed record) | sealed at session close; never in-force as final |
| B \(X_i\) | in-process NVAR, empty history per run | durable week series |
| C CLT + MaxSim | in the flow; published as ledger jsonb | week-level binding set as product bytes |
| D KB week-block | BEGIN/END blocks in KB | same, scored as the cortical write |
| E aperture delta | strategy submodule pin; no week admission-delta object | shadow vs trunk on the same week |
| Promotion | cherry-pick in git, ungated | sealed session transcript is the gate |
| Ledger | `theta_consolidation_runs` | remains; Nautilus only |

## What this note does not do

- Unpause `atelier_sdg_classify`.
- Stampede Theta catch-up / `catchup=True`.
- Treat the SQL row as the cortical product.
- Invent ShadowStrategy as a day clock.
- Seed `data-products.json` or implement RESOURCES on Gaius in this
  commit.

## Pointers

- Intent: `docs/scratch/2025-12-23/010000_theta_consolidation_architecture.md`
- Name collision (THS janitor): `docs/scratch/2026-09-14/161500_theta-scratch-ths.md`
- ShadowStrategy × week window: `docs/scratch/2026-09-20/161200_shadowstrategy_theta_week_artifact.md`
- Architecture (what runs): `docs/current/src/architecture/theta.md`
- Strategy repo: `external/sdg-strategy/README.md` (Shadows are branches)
- AgentRTC materials: signals-plugins `hsengine/engine/resources_store.py`
- Wiki (NONNORMATIVE): `$WIKI_PATH/current/design/data-product-aspects.md`
  and `scratch/2026-09-20/211944_a-useful-adaptation-is-to-make-data-product-aspect.md`

## Open questions

1. **Spoken identity.** `origin_agent=theta` names the session source.
   Does AgentRTC still use Ripley as the voice executing Theta's
   `prompt.md`, or is Theta a spoken profile?
2. **Series product id.** Wiki says the series is a distinct product.
   Name (`gaius.theta.sessions`?) and which 12-vocab aspects a
   `SessionSeriesProductProfile` requires — still open on the wiki.
3. **When to book.** Strictly at week-complete, or also a mid-week
   holding session when a shadow delta is already discussable?
   (`can-have-attachment` makes empty materials valid; it does not
   decide whether to book.)
4. **Objective `theta_cycle`.** Move the gate from ledger
   `documents_augmented > 0` onto D (and B/C) in the same change that
   publishes the product, or later?
5. **Transcript seal trigger.** Session close vs series close? May
   consumers reference an in-force transcript at all? (Wiki open
   question; Theta should answer “session close; no” unless we have
   a reason.)
6. **Nested `PreparedSessionMaterials`.** Defer, or take the nested
   fork now (theta-cycle salience vs shadow-strategy salience as
   sub-aspects the prompt surfaces)?
