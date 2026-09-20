# Gaius

Gaius is the **cognition peer** of the [Signals](./operations/peer-unit.md) lattice. It runs a local thinking lane, keeps a markdown knowledge base, publishes an article surface, and consolidates what it has been thinking about. It attaches to the hub over one wire (`zndx.engine.v1.Engine` on `:50051`, peer id `gaius`), takes its clock from the Signals Airflow, runs its substantive workflows as Metaflow flows under YuniKorn, and settles its data products into the Signals warehouse.

This book is the operator and architecture reference for that peer. Every sentence in `docs/current` describes what runs today; retired paths are named retired in the same paragraph or are gone. The founding framing (Pliny, the 19×19 board, the swarm) lives on [Origins](./concepts/origins.md).

## What runs

| Surface | Current sentence |
|---------|------------------|
| **Engine** | One daemon on `:50051` (`gaius.engine`) hosts the services; TUI, CLI and MCP are thin gRPC clients ([Engine-First](./architecture/engine-first.md)). The native `GaiusService` sits beside the shared `zndx.engine.v1.Engine`. |
| **Inference** | One local thinking lane: Qwen3.8-27B under vLLM, reached only through `Engine/Complete` with optillm methods as first-class capabilities; `instruct` is an operating profile of the same model. No client dials a model or optillm directly ([Inference](./architecture/inference.md)). |
| **Embeddings** | ColBERT-Zero (`lightonai/ColBERT-Zero` via pylate): 128-d per-token vectors scored by MaxSim, a mean `agg` vector per document, Qdrant collection `gaius_kb_colbert_zero`, served to every client by the `EmbedTexts` RPC. There is no vLLM embedding process. Nomic, ColNomic, ColPali and ColQwen are retired (`#EM.00000003.RETIRED`) ([Embeddings](./concepts/embeddings.md)). |
| **Cognition** | The cognition cycle writes `cognition_thoughts`; ambient synthesis (every 20 min) admits buffer windows through the SDG aperture (ColBERT-Zero MaxSim, unique topic) and synthesises on the thinking lane; `/thoughts` answers "what have you been thinking about" from the persisted thoughts; the Agenda brief lands after every producer run and at the day rollover ([Cognition](./architecture/cognition.md)). |
| **Article surface** | Daily curation (Brave, arXiv category RSS) → research → cards → four publish slots a day → `gaius.zndx.org`, with LuxCore-rendered card imagery. Objectives `site_freshness` and `surface_integrity` judge the public page, not the pipeline ([Article Curation](./architecture/article-curation.md)). |
| **Prospects** | A daily check orders the `ProspectsUpdateFlow`: FMP and SEC filings in, per-symbol theses and an Agenda card out; objective `prospects_intelligence` ([Data Pipeline](./architecture/data-pipeline.md)). |
| **Theta cycle** | Monday 06:00 UTC, Airflow DAG `gaius_theta_cycle`, `ThetaCycleFlow`, on the **previous** ISO week: `cognition_thoughts` encoded through `EmbedTexts` for the NVAR drift signal; CLT co-activation over admitted items yields SKOS-grounded OWL class pairs; BERTSubs Intra scores `⊑` on the HermiT-certified SDG TBox; knowledge-gradient selection; KB augmentation; objective `theta_cycle` ([Theta Consolidation](./architecture/theta.md)). |
| **Schedule** | The workload catalogue declares every class (mirrored as inactive pg_cron jobs); the engine syncs it to Signals, which materialises one Airflow DAG per enabled class; a run is an Activity that asserts the class's YuniKorn claims for its duration; the engine starts the work when it sees its own Activity in force ([Metaflow](./architecture/metaflow.md), [pg_cron](./architecture/pgcron.md)). |
| **Workflows** | Substantive work is a `GaiusFlow` on platform Metaflow (Signals metadata service, artifacts on RustFS, Kubernetes under YuniKorn). Flows are engine clients: thinking and embeddings over gRPC, never a local model ([Engine-First and workload execution](./architecture/engine-first.md#engine-first-and-workload-execution)). |
| **Knowledge base** | A markdown zettelkasten at `/raid/signals/var/kb/dev` (`build/dev`): `current/`, `scratch/<date>/`, `archive/`; indexed in Qdrant; Bases and DQL for structured queries ([Knowledge Base](./architecture/knowledge-base.md)). |
| **Storage** | PostgreSQL `zndx_gaius` for state and queues; Qdrant for vectors; the Signals warehouse for data products — Kudu hot tier, Iceberg on RustFS settled tier, Impala across both, `impala_fdw` from Postgres; HX (exchanges, reasoning traces) as Iceberg tables through Polaris ([Lineage](./architecture/lineage.md)). |
| **Verification** | Every scheduled class carries an Objective defined on the surfaced result; probes are Brier-scored forecasts in the efficacy ledger; Nautilus supervises the Operations Backlog beside the engine; Overwatch (ACP + Grok) judges what determinism cannot settle ([Verification](./architecture/verification.md)). |
| **Health** | FMEA-scored health observer, `/health fix <service>` self-healing first, guru meditation codes on every failure ([Health](./architecture/health.md)). |

## The peer

```
   TUI · CLI · MCP ── gRPC ──▶ gaius engine :50051 ──▶ thinking (vLLM, Qwen3.8-27B)
                                     │                ColBERT-Zero (EmbedTexts)
                                     │                cognition · agenda · objectives
                                     │
              zndx.engine.v1 / zndx.scheduler.v1 (signals-protocol)
                                     │
                          Signals engine :50551
                     Airflow (clock) · YuniKorn (admission)
                     Metaflow (flows) · Kudu/Iceberg/Impala (warehouse)
                                     │
                    board :9890 · gaius.zndx.org (article surface)
```

## Getting started

```bash
# Peer unit (devenv graph under systemd)
systemctl status gaius.service
just up                                   # or: just restart-clean

# Thin clients
uv run gaius                              # TUI
uv run gaius-cli --cmd "/health" --format json
uv run gaius-cli --cmd "/gpu status" --format json
uv run gaius-cli --cmd "/objective verify" --format json
```

Next: [System Overview](./architecture/overview.md) for the service map, [Signals Peer Unit](./operations/peer-unit.md) for how the peer attaches, and [Engine-First](./architecture/engine-first.md) for the one rule that shapes the code.
