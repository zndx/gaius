# 2026-W38 landed later and did not become the week in force

The 01:36 note said the cognition loop reads the newest active consolidation. That sentence is retired. Newest meant `created_at`. A backfill of an earlier week lands later, so that ordering would have made 2026-W38 the week the loop proceeds from and pushed 2026-W39 out of force.

Valid time is the ISO slice on the thought (`generation_context.slice_id`). Transaction time is when the row landed (`created_at`, and `updated_at` if that same slice is rewritten). The week in force is the greatest slice at or before the current ISO week. Landed time only breaks a tie inside one slice. A slice after the current week is not in force. Weeks stay zero-padded, so the string order is the ISO order, including the year boundary.

The encode query no longer takes a consolidation as an input. Both of these rows landed in 2026-W40. They are the product of W38 and W39, not thoughts for the W40 centroid. Nothing was re-encoded. `theta_backfill` was not run. Atelier stays paused. No year backfill.

- Thought `d25e41c4-5317-4f4c-a256-fac2ebd47b5f`, slice `2026-W38`, landed `2026-09-29 02:01:13+00`, title "Gaius 2026-W38: State Invariants, Temporal Hypothesis, CFM MT Gap". The thinking model wrote it from the week's 228 thoughts and the 114 groundings already on row 23. Named classes only (DataInput, MachineLearningModel, and the service, storage, and decision labels). It does not mint classes and does not claim subclass or subsumption. "What state must agents preserve?" is the settled frame. Temporal and CFM MT stay hypotheses.
- Row 23 is `completed`, error cleared, metadata cites that thought. Rows 13–22 stay failed, including the earlier NOPAIRS row. Row 24 and thought `b34d5787-894d-4826-8ac9-01f7b7a07bf8` are unchanged.
- With both rows active, the chooser returns 2026-W39. That is the week the loop proceeds from until a later ISO week is written.

The gaius engine was recycled before the insert (pid 2683412, started 01:56:16) so the running cognition loop loaded ISO-week retrieval first. After the insert, Engine/Status coordination was healthy and listed no misses. The voice engine was left up.
