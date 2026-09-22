# Theta is untuned; success is not defined yet

Aegir already has an effective aperture: admission selectivity and MaxSim
against the live membrane `(C, regime params, e, index)`. That is a thing we
can see working.

Theta does not have that yet. The consolidation procedure — centroid, CLT
incidence, TBox MaxSim, novel pairs, BERTSubs — is running for the first
time on a real week. It is untuned. A green Airflow run, a `completed`
`theta_consolidation_runs` row, `documents_augmented > 0`, or
`#THETA.00000011.NOPAIRS` is an observation, not a verdict. Week completion
does not promote an aperture, and the ledger row is still coverage, not the
cortical product.

Refine Theta empirically. Do not freeze a success metric until a week
artifact can be compared with the aperture the way Aegir's admission
profile can.

First observation, not a result: Metaflow 7498 encode of 2026-W38 wrote
`n=228 week_n=228 dim=(128,) grounded=114` and entered infer (ledger row
20, still running as of this note).
