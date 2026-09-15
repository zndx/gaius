# Prospects vs AgentRTC / Theta: activity-aligned YK claims

Correction (user, 2026-09-15): treating prospects as a GPU claimant that
might evict thinking is a **category error**. `thinking` and `instruct`
are operating profiles of **one** Qwen3.8-27B on **heavy**. Product
workloads are Metaflow; they `Engine/Complete` the engine that hosts
that vLLM (so a spot remote engine can serve them). They do not take
heavy tokens. In-engine tasks should be gone.

00:50 `#EP.00000016.NOTREADY` was thinking **absent** after YK
`gaius-thinking` `#YK.00000002.NOTADMITTED` (heavy). Hardware util now
is the 02:42 vLLM, not that window. The flow was a **client of a missing
endpoint**, not a rival for its GPUs.

The remaining drift: **prospects_check is still `RUNNER_TASK`**
(in-engine, catch-up enqueues the update). The Metaflow should be
Airflow-ordered and Complete whichever engine advertises healthy
thinking/instruct. `lattice.engine_target()` still defaults to
`127.0.0.1:50051`.

Earlier (wrong) frame: **prospects_update is not on the Airflow-activity
claim path** that AgentRTC and Theta use. Keep the table as inventory of
what the code does today, not as the desired claim model.

| | AgentRTC | ThetaCycleFlow | prospects_check | prospects_update |
|---|---|---|---|---|
| Who declares the Activity | Hermes engine | Airflow DAG `gaius_theta_cycle` | Airflow DAG `gaius_prospects_check` | **nobody** |
| Catalogue | n/a (peer kind) | enabled, `runner=metaflow` | enabled, `runner=task` | **not catalogued** |
| Signals `claims` | `agent-rtc` GPU 1 | `light` GPU 1 | **[]** | supervision wants extract 1 + light embedding in analyze; **never asserted** |
| Host sentinel | moshi on GPU 5 | STP `apply_and_admit` LIGHT, STZ on exit | rate-metered | STP EXTRACT 1, STZ in `finally` |
| Queue-share retire | `ReleaseActivity` → `_reconcile_shares` retract | same | skip/fail release (now NOEFFECT) | **no Activity, nothing to retract** |
| Thinking | Cerebras; Gaius thinking stays standing | ColBERT+BERTSubs; no Complete | none | **`depends_on: endpoint.thinking`** via Complete |

`workload_catalog.py` still says prospects_update and "Theta
consolidation" are not catalogued; Theta **is** catalogued (`gaius_theta_cycle`).
Prospects_update is still engine-enqueued from the check (and
engine-catchup), so Airflow never raises extract/light floors for the
Metaflow run. The machine in `gaius.textproto` already has the blueprint
(extract floor 1, embedding protect at analyze priority 60).

Ideal: catalogue `prospects_update` like `article_curate` /
`theta_cycle` — Airflow-ordered Metaflow Activity whose `claims` are
the machine's floors for the run, retracted on release. Catch-up must
not spawn the flow outside that Activity.
