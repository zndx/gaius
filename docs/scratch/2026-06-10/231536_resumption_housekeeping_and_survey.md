# Project Resumption: Housekeeping, Commit Catch-Up, and Direction Survey

First session after a ~3-month pause (last commit 2026-03-15). Goals: clean the
repo, land the stranded March work, and build situational awareness on the
prospects/ontology directions and the xAI Grok relationship.

## Commits Landed

| Commit | Summary |
|--------|---------|
| `912c37a` | chore: repo root housekeeping and .gitignore fixes |
| `a5dd5d1` | feat(health): Metaflow stack health check, RCA escalation, self-healing |
| `ebcfcbe` | feat(viz): card visualization render and backfill scripts |
| `36f2e1e` | chore(devenv): drop llama-cpp package and refresh lock |
| `b09a2f4` | docs(scratch): work notes for 2026-03-14/15 sessions |

## Housekeeping Details

- **Bug found**: generic Python `lib/` pattern in .gitignore was ignoring
  `scripts/lib/` — the process helpers (process-helpers.sh, gpu-helpers.sh,
  wait-for-endpoints.py, kubeconfig-sync.sh) were NEVER tracked. A fresh clone
  would have been broken. Fixed by anchoring to `/lib/` and tracking the files.
- Untracked from git: `.qdrant-initialized` (runtime marker, now ignored),
  `=5.0.0rc0`, `acp-incident_01-02.txt`, `glm-4.6v-flash.py`
- Deleted: 15 `metaflow.s3.*` temp dirs, `recursive_glass.blend1`, empty
  `ev/` and `gaius-test/` dirs
- Moved to `build/tmp/root-cleanup-2026-06-10/`: 14 session .txt logs, blender
  guides, 2 concept PNGs, glm script (20 files)
- December stash (WIP on feat/metaflow-docling-flow) archived as patch in the
  same dir and dropped — its healing_events/self-healing content already
  landed in trunk via later commits.

## Metaflow Health Work Re-Verification (2026-06-10)

- `/health`: 17 pass / 8 warn / 6 fail — all failures are 3-months-idle
  symptoms (stale content, overdue periodic tasks, no flow runs)
- RCA notices fire correctly: `curation_pipeline` root cause groups
  `landing_page_pipeline` + `metaflow_stack`
- `/health fix metaflow --dry-run`: all 5 steps present
- FMEA: MF_001..MF_004 now in `fmea_catalog` (MF_004 was missing — the DB had
  been migrated before MF_004 was added to the migration file)
- systemd kubeconfig-sync drop-in proved itself: RKE2 restarted May 17,
  kubeconfig auto-synced 2 min later
- **Gotcha recorded**: dbmate-format migrations run raw through psql execute
  BOTH up and down sections. Apply with
  `sed -n '/migrate:up/,/migrate:down/p' file | grep -v migrate:down | psql ...`
  Note: `schema_migrations` tracking stopped at 20260202100000; migrations
  since have been applied manually.

## Direction Survey: Prospects

**Status: production, was running daily until the pause.** Capital stewardship
system — SEC filings (FMP API), 13F holdings, Cerebras GLM analysis + Grok
synthesis. ~$0.60/prospect full analysis.

- Service: `engine/services/prospects_service.py` + `prospects_analysis.py`
- TUI: `app.py` `_handle_prospects_command` (status/check/update)
- Schema: `20260109000001_prospects_stewardship.sql`; pg_cron task fixed in
  `20260304000001` (24h cooldown gate)
- Watchlist (gitignored `config/prospects/watchlist.conf`): CHTR, DIS, MTN,
  LLY, XOM
- Last sitrep: 2026-03-05. Next steps when paused: monitor daily cron,
  refine synthesis skip logic, Iceberg HX queries for pending work counts.

## Direction Survey: Ontology

**Status: experimental framework complete (Dec 2025), paused awaiting corpus.**

- Production: `src/gaius/data/ontologies/gaius_domain.owl` (58 classes) feeds
  BERTSubs/DeepOnto subsumption in ThetaAgent consolidation. Needs 200-500
  classes for BERTSubsIntraPipeline training (currently skip-gated in tests).
- Experimental: RASE de novo generation in `src/gaius/rase/domains/kb/` — all
  4 verification gates (loads / complex classes / verbalizable / topics
  recoverable) passing on Pizza.owl (94.8%), Equinix Metal (76.7%), Gaius
  domain (53.3%).
- Scripts ready but never run on a real corpus: `ontology_denovo_pipeline.py`,
  `ontology_extraction_dspy.py`, `compare_ontology_extraction.py`
- Planned next step (2025-12-22 notes): Cloudera Private Cloud Base + K8s
  Operator docs as first real corpus.

## Direction Survey: xAI Grok Relationship

Grok is the designated **outsider evaluator** — local-first inference with
xAI for high-stakes judgment (decision dates to 2025-12-01 notes).

Production roles:
1. Article curation flow: research summary + draft (2M context; hard
   requirement, `#ACF.00000002.NOXAI`)
2. MetaAgent Debate: skeptic critique (phase 3) + judge synthesis (phase 5)
3. NiFi SoM/ToM calibration: 6-dimension anchored rubric
4. `evaluate_with_xai` MCP tool + `scripts/xai_review{,_batch}.py` doc reviews

Budget: request-based (50/day, 200/week), grok-4-1-fast at $0.20/$0.50 per M.

Loose ends worth picking up:
- `SynthesisEvaluator` still uses `grok-3-mini-beta` (intentional? undocumented)
- No test coverage for the 2026-03-14 evaluate_with_xai fixes
- Budget exhaustion returns error rather than queueing
- The "fraught" dynamic, per the GTC review cycle: Grok is credible on
  precision/tone (caught wrong filtration space), unreliable on structure —
  use as copy editor, never architect (e696622 records accepted vs rejected
  feedback).
