# Prospects vs AgentRTC / Theta: activity-aligned YK claims

00:50 `#EP.00000016.NOTREADY` was thinking **absent** after YK
`gaius-thinking` `#YK.00000002.NOTADMITTED` (heavy). Hardware util now
is the 02:42 vLLM, not that window.

The deeper drift: **prospects_update is not on the Airflow-activity
claim path** that AgentRTC and Theta use.

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
