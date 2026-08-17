# Ask availability — YK only, light vs heavy vs offline

Never start leftover vLLM if YuniKorn has not admitted the Ask Sentinel.
Going around YK is how we OOM thinking and contend on 4–5.

## Workload classes

| Class | Queue | Who | Guarantee | Preempt / victim |
|-------|-------|-----|-----------|------------------|
| **Heavy** | `root.internal.inference.heavy` | Thinking 27B (0–3) | 4 GPU | Light/medium **cannot** preempt |
| **Medium** | `root.internal.inference.medium` | Ask SAE 9B TP=2 | 2 GPU | One app, two whole GPUs |
| **Light** | `root.internal.inference.light` | Ask 1.7B (one GPU per app) | 1 GPU | One-GPU deployments only |
| **Offline** | `root.internal.inference.extract` | Docling / article-curate | **0** GPU | Victim when over guarantee |

Ask was never extract. Intra-queue preemption is a YK non-goal — light and
offline **must** be siblings.

## Ask Complete (engine)

1. Preferred leftover if **already HEALTHY** (YK-admitted earlier).
2. Other leftover if healthy.
3. Else **Complete on standing thinking** — share the existing 27B
   process. Do **not** allocate GPUs. Do **not** start a new vLLM.
4. Give up only if thinking is also down **and** `light_wait_available()`
   is false (light leaf will not take another Sentinel).

Settings/boot may `apply_and_admit("ask-agent")` **then** start leftover
vLLM. Complete never calls `start_endpoint` on a cold leftover.

## YK laws (still)

Ask triggers preemption only while **light is under its 2-GPU guarantee**.
Extract running with guarantee 0 is over-guarantee → legal victim.
PriorityClass `federation-ask` > `federation-extract`. Ask
`allow-preemption: false`. Fence on `internal.inference` (and on heavy).

Host-Yield of extract **without** a YK preemption decision is forbidden.

Promote queues: `uv run python -m signals.cli.yk promote` after review.
