# Prospects update 84680 did not place

Task 84680 (`prospects_update`, symbols MTN, LLY, DIS, SLB, CHTR, XOM)
was picked up at 2026-10-13 07:00:50 UTC and deferred at 07:10:55 UTC.
Reason `yk_admission`: `#YK.00000002.NOTADMITTED` pod
`prospects-update-84680` never reached Running on
`root.internal.inference.extract`. The pod was deleted after the 600s
net. No later `prospects_update` row exists. The outcomes blob on the
row is the 2026-10-11 sitrep (`last_update_outcomes.json`), not a new
run. The 07:00 check (task 84679) had reported 72 new FMP filings and
90 pending analysis.

The extract leaf was empty for that wait. At 07:01:13 the arbiter
logged `#YK.00000010.INTRALEAF prospects-update@50` with `holders=[]`.
Queue share for `prospects-update` had already APPLIED (1.6s). There
was no standing `article-curate` pod to yield, and none is running now.
`article-curate-84813` admitted later, at 09:07:18, and the task row
completed at 09:42 with returncode 0. Re-running that pod would not
analyze these six symbols.

What filled the box was the two Decision 3.0 light seats. Both
`d3_server.py` processes are still up from 2026-10-12 02:36 and 02:37
UTC (`CUDA_VISIBLE_DEVICES` 5 and 4, ports 8096 and 8097). Thinking
holds GPUs 0–3. `nvidia-smi` shows about 2 GiB free on every card.
YuniKorn currently accounts 5 of 6 GPU tokens (thinking 4 +
`gaius-d3-flash-0` 1) and lists no extract application.
`gaius-d3-flash-1` is not a pod and is not a YuniKorn application, but
the engine still counts it in the light envelope. `live_apps_on_queue`
treats a missing pod (`phase == ""`) as live, and `_ADMITTED` was never
released. Every `clt_skos_admit` since 02:45 UTC defers
`#YK.00000004.ENVELOPE` at cap 2: `['gaius-d3-flash-0',
'gaius-d3-flash-1']`. `d3-flash-0` is priority 80, so admit (20) does
not yield it. `feature_probe` defers `no light YK slot` on the same
in-memory count.

At 07:00 both light tokens were still allocated, so the extract pause
pod could not bind. The same window's ambient synthesize failed
`#YK.00000002.NOTADMITTED` on `gaius-embedding`. By evening the missing
`gaius-d3-flash-1` pod has freed a scheduler token that CUDA does not
have. Ambient task 85509 (20:40 UTC) failed in about two minutes with
`#AMB.00000004.SYNTHFAIL` / `#YK.00000008.GPUCOLLIDE`: vLLM holds
`[0, 1, 2, 3, 4, 5]`.

A new `prospects-update-<id>` claim is the right object. It should wait
until one d3 seat is released as a process, a pod, and an engine
admission together. Admitting it against the current free token would
schedule a pause pod onto a card the orphan `d3_server` still occupies.

Separate hourly failure: `tier_settle` writes the HDF5 tier and then
dies in Impala verify, `#SL.00000025.TIERUP`, `No module named 'impala'`
in the gaius venv (task 85487, 20:20 UTC). Objective verify 85446
(19:38 UTC) failed `site_freshness`, `prospects_intelligence`,
`skos_admission`, `tier_settle`, `theta_cycle`, `ambient_synthesis`,
`ops_backlog`, and `surface_integrity`.
